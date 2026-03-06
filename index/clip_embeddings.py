"""CLIP embedding generation using open_clip.

Provides functions to embed images and text into a shared 512-dim vector
space for semantic search and retrieval.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import torch
from PIL import Image

from config import CLIP_MODEL, CLIP_PRETRAINED, CLIP_EMBEDDING_DIM

logger = logging.getLogger(__name__)

MAX_CLIP_DIM = 512  # Max pixels on long side before CLIP preprocessing

# Module-level cache for lazy-loaded model components
_model: Optional[torch.nn.Module] = None
_preprocess = None
_tokenizer = None
_device: Optional[torch.device] = None


def _get_device() -> torch.device:
    """Select the best available device (MPS for Apple Silicon, else CPU)."""
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _load_model():
    """Lazy-load the CLIP model, preprocessor, and tokenizer.

    Cached at module level so subsequent calls are free.
    """
    global _model, _preprocess, _tokenizer, _device

    if _model is not None:
        return

    import open_clip

    _device = _get_device()
    logger.info("Loading CLIP model %s/%s on %s", CLIP_MODEL, CLIP_PRETRAINED, _device)

    _model, _, _preprocess = open_clip.create_model_and_transforms(
        CLIP_MODEL, pretrained=CLIP_PRETRAINED
    )
    _tokenizer = open_clip.get_tokenizer(CLIP_MODEL)
    _model = _model.to(_device)
    _model.eval()

    logger.info("CLIP model loaded successfully")


def _downsize_image(img: Image.Image, max_dim: int = MAX_CLIP_DIM) -> Image.Image:
    """Resize an image so its longest side is at most *max_dim* pixels.

    The CLIP preprocessor handles the final resize to 224x224, but
    pre-shrinking avoids loading very large images into GPU memory.
    """
    if max(img.size) > max_dim:
        ratio = max_dim / max(img.size)
        new_size = (int(img.width * ratio), int(img.height * ratio))
        img = img.resize(new_size, Image.LANCZOS)
    return img


def embed_image(image_path: str) -> np.ndarray:
    """Embed a single image and return a L2-normalized 512-dim vector.

    Args:
        image_path: Absolute path to the image file.

    Returns:
        A numpy array of shape (512,) with unit L2 norm.
    """
    _load_model()

    img = _downsize_image(Image.open(image_path).convert("RGB"))
    tensor = _preprocess(img).unsqueeze(0).to(_device)

    with torch.no_grad():
        features = _model.encode_image(tensor)

    embedding = features.cpu().numpy().astype(np.float32).squeeze(0)
    norm = np.linalg.norm(embedding)
    if norm > 0:
        embedding = embedding / norm

    return embedding


def embed_images(image_paths: list[str]) -> np.ndarray:
    """Embed multiple images in a batch.

    Args:
        image_paths: List of absolute paths to image files.

    Returns:
        A numpy array of shape (N, 512) with each row L2-normalized.
    """
    if not image_paths:
        return np.empty((0, CLIP_EMBEDDING_DIM), dtype=np.float32)

    _load_model()

    tensors = []
    valid_indices: list[int] = []
    for idx, path in enumerate(image_paths):
        try:
            img = _downsize_image(Image.open(path).convert("RGB"))
            tensors.append(_preprocess(img))
            valid_indices.append(idx)
        except Exception as exc:
            logger.warning("Could not load image %s: %s", path, exc)

    if not tensors:
        return np.empty((0, CLIP_EMBEDDING_DIM), dtype=np.float32)

    batch = torch.stack(tensors).to(_device)

    with torch.no_grad():
        features = _model.encode_image(batch)

    embeddings = features.cpu().numpy().astype(np.float32)

    # L2-normalize each row
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-8)
    embeddings = embeddings / norms

    return embeddings


def embed_text(text: str) -> np.ndarray:
    """Embed a text query into the same vector space as images.

    Args:
        text: A natural-language query string.

    Returns:
        A numpy array of shape (512,) with unit L2 norm.
    """
    _load_model()

    tokens = _tokenizer([text]).to(_device)

    with torch.no_grad():
        features = _model.encode_text(tokens)

    embedding = features.cpu().numpy().astype(np.float32).squeeze(0)
    norm = np.linalg.norm(embedding)
    if norm > 0:
        embedding = embedding / norm

    return embedding
