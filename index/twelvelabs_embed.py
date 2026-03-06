"""Twelve Labs Marengo embedding integration.

Replaces CLIP with Twelve Labs' multimodal video-native embeddings.
Produces 1024-d vectors that capture visual, audio, and temporal information.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

import config

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        from twelvelabs import TwelveLabs
        _client = TwelveLabs(api_key=config.TWELVELABS_API_KEY)
    return _client


def _normalize(vec: list[float]) -> np.ndarray:
    embedding = np.array(vec, dtype=np.float32)
    norm = np.linalg.norm(embedding)
    if norm > 0:
        embedding = embedding / norm
    return embedding


def _file_tuple(file_path: str) -> tuple[str, bytes, str]:
    """Build a (filename, content, content_type) tuple for the SDK."""
    p = Path(file_path)
    ext = p.suffix.lower()
    content_types = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".heic": "image/heic", ".webp": "image/webp", ".gif": "image/gif",
        ".tiff": "image/tiff", ".bmp": "image/bmp",
        ".mp4": "video/mp4", ".mov": "video/quicktime", ".m4v": "video/mp4",
        ".avi": "video/x-msvideo", ".mkv": "video/x-matroska", ".webm": "video/webm",
    }
    ct = content_types.get(ext, "application/octet-stream")
    return (p.name, p.read_bytes(), ct)


def embed_video(video_path: str) -> list[dict]:
    """Embed a video file using Twelve Labs Marengo.

    Returns a list of segment dicts, each with:
        - embedding: np.ndarray of shape (1024,)
        - start_sec: float
        - end_sec: float
    """
    client = _get_client()
    logger.info("Creating Twelve Labs video embedding task for %s", Path(video_path).name)

    task_response = client.embed.tasks.create(
        model_name=config.TWELVELABS_MODEL,
        video_file=_file_tuple(video_path),
    )
    task_id = task_response.id
    logger.info("Task created: id=%s, waiting for completion...", task_id)

    client.embed.tasks.wait_for_done(task_id, sleep_interval=3)
    task_result = client.embed.tasks.retrieve(task_id)

    segments = []
    if task_result.video_embedding and task_result.video_embedding.segments:
        for seg in task_result.video_embedding.segments:
            segments.append({
                "embedding": _normalize(seg.float_),
                "start_sec": getattr(seg, 'start_offset_sec', 0.0),
                "end_sec": getattr(seg, 'end_offset_sec', 0.0),
            })

    logger.info("Got %d segments from Twelve Labs for %s", len(segments), Path(video_path).name)
    return segments


def embed_image(image_path: str) -> np.ndarray | None:
    """Embed a single image using Twelve Labs Marengo.

    Returns a 1024-d numpy array, or None on failure.
    """
    client = _get_client()
    logger.info("Creating Twelve Labs image embedding for %s", Path(image_path).name)

    try:
        response = client.embed.create(
            model_name=config.TWELVELABS_MODEL,
            image_file=_file_tuple(image_path),
        )

        if response.image_embedding and response.image_embedding.segments:
            return _normalize(response.image_embedding.segments[0].float_)
    except Exception as exc:
        logger.error("Twelve Labs image embedding failed for %s: %s", image_path, exc)

    return None


def embed_text(query: str) -> np.ndarray | None:
    """Embed a text query using Twelve Labs Marengo.

    Returns a 1024-d numpy array in the same latent space as video/image embeddings.
    """
    client = _get_client()

    try:
        response = client.embed.create(
            model_name=config.TWELVELABS_MODEL,
            text=query,
        )

        if response.text_embedding and response.text_embedding.segments:
            return _normalize(response.text_embedding.segments[0].float_)
    except Exception as exc:
        logger.error("Twelve Labs text embedding failed for '%s': %s", query, exc)

    return None
