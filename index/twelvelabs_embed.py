"""Twelve Labs Marengo embedding integration.

Uses the Embed API v2 with Marengo 3.0, producing 512-d vectors that capture
visual, audio, and temporal information.
"""

from __future__ import annotations

import logging
import time
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


def _file_to_base64(file_path: str) -> str:
    """Read a file and return its base64-encoded contents."""
    import base64
    return base64.b64encode(Path(file_path).read_bytes()).decode("utf-8")


def embed_video(video_path: str) -> list[dict]:
    """Embed a video file using Twelve Labs Marengo 3.0 (Embed API v2).

    Returns a list of segment dicts, each with:
        - embedding: np.ndarray of shape (512,)
        - start_sec: float
        - end_sec: float
    """
    from twelvelabs.types.video_input_request import VideoInputRequest
    from twelvelabs.types.media_source import MediaSource

    client = _get_client()
    logger.info("Creating Twelve Labs v2 video embedding task for %s", Path(video_path).name)

    b64 = _file_to_base64(video_path)

    task_response = client.embed.v_2.tasks.create(
        input_type="video",
        model_name=config.TWELVELABS_MODEL,
        video=VideoInputRequest(
            media_source=MediaSource(base_64_string=b64),
            embedding_scope=["clip"],
        ),
    )
    task_id = task_response.id
    logger.info("Task created: id=%s, waiting for completion...", task_id)

    # Poll for completion (v2 tasks API has no wait_for_done helper)
    max_wait = 300  # 5 minute timeout
    elapsed = 0
    while elapsed < max_wait:
        task_result = client.embed.v_2.tasks.retrieve(task_id)
        if task_result.status == "ready":
            break
        if task_result.status == "failed":
            logger.error("Video embedding task %s failed", task_id)
            return []
        time.sleep(5)
        elapsed += 5
    else:
        logger.error("Video embedding task %s timed out after %ds (status=%s)",
                      task_id, max_wait, task_result.status)
        return []

    segments = []
    if task_result.data:
        for seg in task_result.data:
            segments.append({
                "embedding": _normalize(seg.embedding),
                "start_sec": seg.start_sec or 0.0,
                "end_sec": seg.end_sec or 0.0,
            })

    logger.info("Got %d segments from Twelve Labs v2 for %s", len(segments), Path(video_path).name)
    return segments


def embed_image(image_path: str) -> np.ndarray | None:
    """Embed a single image using Twelve Labs Marengo 3.0 (Embed API v2).

    Returns a 512-d numpy array, or None on failure.
    """
    from twelvelabs.types.image_input_request import ImageInputRequest
    from twelvelabs.types.media_source import MediaSource

    client = _get_client()
    logger.info("Creating Twelve Labs v2 image embedding for %s", Path(image_path).name)

    try:
        b64 = _file_to_base64(image_path)

        response = client.embed.v_2.create(
            input_type="image",
            model_name=config.TWELVELABS_MODEL,
            image=ImageInputRequest(
                media_source=MediaSource(base_64_string=b64),
            ),
        )

        if response.data:
            return _normalize(response.data[0].embedding)
    except Exception as exc:
        logger.error("Twelve Labs v2 image embedding failed for %s: %s", image_path, exc)

    return None


def embed_text(query: str) -> np.ndarray | None:
    """Embed a text query using Twelve Labs Marengo 3.0 (Embed API v2).

    Returns a 512-d numpy array in the same latent space as video/image embeddings.
    """
    from twelvelabs.types.text_input_request import TextInputRequest

    client = _get_client()

    try:
        response = client.embed.v_2.create(
            input_type="text",
            model_name=config.TWELVELABS_MODEL,
            text=TextInputRequest(input_text=query),
        )

        if response.data:
            return _normalize(response.data[0].embedding)
    except Exception as exc:
        logger.error("Twelve Labs v2 text embedding failed for '%s': %s", query, exc)

    return None
