"""Image description using Claude Vision.

Sends images to Claude and receives structured descriptions useful for
video editing decisions — subject identification, mood, quality scoring, etc.
"""

from __future__ import annotations

import base64
import io
import logging
import mimetypes
import time
from pathlib import Path

from PIL import Image

import anthropic

from config import ANTHROPIC_API_KEY, VISION_MODEL

logger = logging.getLogger(__name__)

MAX_VISION_DIM = 1568

SYSTEM_PROMPT = (
    "You are a professional video editor and cinematographer evaluating footage "
    "and photographs for inclusion in a curated video project. Analyze each image "
    "with an expert eye for visual storytelling, composition, color, and emotional "
    "impact. Be precise and concise in your descriptions."
)

DESCRIBE_PROMPT = """\
Analyze this image and provide a structured JSON description with exactly these keys:

- "summary": A 1-2 sentence description of the image.
- "subjects": A list of strings identifying what or who is in the image.
- "setting": A string describing the setting (indoor/outdoor, location type).
- "mood": A string describing the emotional tone or atmosphere.
- "colors": A list of strings naming the dominant colors.
- "activity": A string describing what is happening in the image.
- "quality_score": An integer from 1-10 rating how visually interesting and technically good this image is for use in a video (10 = stunning, 1 = unusable).

Respond with ONLY the JSON object, no markdown fencing or extra text."""

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """Lazy-initialize the Anthropic client."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def _encode_image(image_path: str) -> tuple[str, str]:
    """Read an image file, resize if too large, and return (base64_data, media_type).

    Images larger than MAX_VISION_DIM on either dimension are downscaled
    (maintaining aspect ratio) to save API tokens and latency.

    Args:
        image_path: Absolute path to the image.

    Returns:
        Tuple of (base64-encoded string, MIME type string).
    """
    path = Path(image_path)
    img = Image.open(path)

    # Resize if either dimension exceeds max
    if max(img.size) > MAX_VISION_DIM:
        ratio = MAX_VISION_DIM / max(img.size)
        new_size = (int(img.width * ratio), int(img.height * ratio))
        img = img.resize(new_size, Image.LANCZOS)

    # Convert to JPEG bytes
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=85)
    data = buf.getvalue()
    media_type = "image/jpeg"

    return base64.standard_b64encode(data).decode("utf-8"), media_type


def describe_image(image_path: str) -> dict:
    """Send a single image to Claude Vision and get a structured description.

    Args:
        image_path: Absolute path to the image file.

    Returns:
        A dict with keys: summary, subjects, setting, mood, colors, activity,
        quality_score.
    """
    import json

    client = _get_client()
    b64_data, media_type = _encode_image(image_path)

    message = client.messages.create(
        model=VISION_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": DESCRIBE_PROMPT,
                    },
                ],
            }
        ],
    )

    raw_text = message.content[0].text.strip()

    # Parse the JSON response, stripping markdown fences if present
    if raw_text.startswith("```"):
        lines = raw_text.split("\n")
        # Remove first and last fence lines
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw_text = "\n".join(lines)

    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.error("Failed to parse Claude response as JSON: %s", raw_text)
        result = {
            "summary": raw_text,
            "subjects": [],
            "setting": "unknown",
            "mood": "unknown",
            "colors": [],
            "activity": "unknown",
            "quality_score": 5,
        }

    # Ensure all expected keys exist with sensible defaults
    defaults = {
        "summary": "",
        "subjects": [],
        "setting": "unknown",
        "mood": "unknown",
        "colors": [],
        "activity": "unknown",
        "quality_score": 5,
    }
    for key, default in defaults.items():
        if key not in result:
            result[key] = default

    return result


def describe_images_batch(
    image_paths: list[str],
    batch_size: int = 5,
) -> list[dict]:
    """Process multiple images with rate limiting.

    Sends images to Claude Vision in sequential calls, pausing between
    batches to respect rate limits.

    Args:
        image_paths: List of absolute paths to image files.
        batch_size: Number of images to process before pausing.

    Returns:
        A list of description dicts, one per image. Failed images get a
        fallback dict with default values.
    """
    from tqdm import tqdm

    results: list[dict] = []
    total = len(image_paths)

    for i, path in enumerate(tqdm(image_paths, desc="[vision] Describing images", unit="img")):
        try:
            desc = describe_image(path)
            results.append(desc)
        except Exception as exc:
            tqdm.write(f"[vision] Failed to describe {path}: {exc}")
            results.append({
                "summary": "Description failed",
                "subjects": [],
                "setting": "unknown",
                "mood": "unknown",
                "colors": [],
                "activity": "unknown",
                "quality_score": 5,
            })

        # Rate-limit: pause after each batch
        if (i + 1) % batch_size == 0 and (i + 1) < total:
            time.sleep(2.0)

    return results
