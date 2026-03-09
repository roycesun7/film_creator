"""Apple Photos library integration using osxphotos.

Connects to the user's default Apple Photos library, exports media with
metadata, and extracts video keyframes for downstream embedding.
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import osxphotos
from PIL import Image

from config import OUTPUT_DIR

logger = logging.getLogger(__name__)

KEYFRAME_EXPORT_DIR = OUTPUT_DIR / "keyframes"
KEYFRAME_EXPORT_DIR.mkdir(parents=True, exist_ok=True)

PHOTO_EXPORT_DIR = OUTPUT_DIR / "exports"
PHOTO_EXPORT_DIR.mkdir(parents=True, exist_ok=True)

KEYFRAME_INTERVAL_SEC = 2.0


@dataclass
class MediaItem:
    """Represents a single photo or video from Apple Photos."""

    uuid: str
    path: Optional[str]
    media_type: str  # "photo" or "video"
    date: Optional[datetime]
    location: Optional[tuple[float, float]]  # (lat, lon) or None
    albums: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    persons: list[str] = field(default_factory=list)
    width: int = 0
    height: int = 0
    duration: Optional[float] = None  # seconds, None for photos
    keyframe_paths: list[str] = field(default_factory=list)


def _extract_keyframes(video_path: str, uuid: str) -> list[str]:
    """Extract one keyframe per ~2 seconds from a video file.

    Uses moviepy to read the video and PIL to save individual frames.
    Returns a list of paths to the extracted keyframe images.
    """
    try:
        from moviepy import VideoFileClip
    except ImportError:
        logger.warning("moviepy not installed; skipping keyframe extraction")
        return []

    keyframe_dir = KEYFRAME_EXPORT_DIR / uuid
    keyframe_dir.mkdir(parents=True, exist_ok=True)

    paths: list[str] = []
    try:
        clip = VideoFileClip(video_path)
        duration = clip.duration
        t = 0.0
        frame_idx = 0
        while t < duration:
            frame = clip.get_frame(t)
            img = Image.fromarray(frame)
            out_path = keyframe_dir / f"keyframe_{frame_idx:04d}.jpg"
            img.save(str(out_path), "JPEG", quality=85)
            paths.append(str(out_path))
            frame_idx += 1
            t += KEYFRAME_INTERVAL_SEC
        clip.close()
    except Exception as exc:
        logger.error("Failed to extract keyframes from %s: %s", video_path, exc)

    return paths


def _photo_to_media_item(photo: osxphotos.PhotoInfo) -> MediaItem:
    """Convert an osxphotos PhotoInfo object into a MediaItem."""
    # Determine media type
    is_video = photo.ismovie
    media_type = "video" if is_video else "photo"

    # Location
    location: Optional[tuple[float, float]] = None
    if photo.latitude is not None and photo.longitude is not None:
        location = (photo.latitude, photo.longitude)

    # Albums
    albums = list(photo.albums) if photo.albums else []

    # Apple ML labels
    labels = [lbl.label for lbl in photo.labels] if photo.labels else []

    # Persons / faces
    persons = list(photo.persons) if photo.persons else []

    # Dimensions
    width = photo.width or 0
    height = photo.height or 0

    # Duration (video only)
    duration: Optional[float] = None
    if is_video and photo.duration is not None:
        duration = photo.duration

    # Resolve the file path — use the original file if available
    path: Optional[str] = None
    if photo.path:
        path = photo.path
    else:
        # If the original isn't on disk (iCloud-only), attempt export
        try:
            exported = photo.export(
                str(PHOTO_EXPORT_DIR),
                use_photos_export=True,
            )
            if exported:
                path = exported[0]
        except Exception as exc:
            logger.warning("Could not export %s: %s", photo.uuid, exc)

    # Extract keyframes for videos
    keyframe_paths: list[str] = []
    if is_video and path:
        keyframe_paths = _extract_keyframes(path, photo.uuid)

    return MediaItem(
        uuid=photo.uuid,
        path=path,
        media_type=media_type,
        date=photo.date,
        location=location,
        albums=albums,
        labels=labels,
        persons=persons,
        width=width,
        height=height,
        duration=duration,
        keyframe_paths=keyframe_paths,
    )


def get_media_items(
    limit: Optional[int] = None,
    album: Optional[str] = None,
    date_range: Optional[tuple[datetime, datetime]] = None,
) -> list[MediaItem]:
    """Query the Apple Photos library and return MediaItem objects.

    Args:
        limit: Maximum number of items to return. None for all.
        album: Filter to a specific album name.
        date_range: Tuple of (start, end) datetimes to filter by date taken.

    Returns:
        A list of MediaItem dataclass instances.
    """
    photosdb = osxphotos.PhotosDB()

    query_options: dict = {}
    if album:
        query_options["albums"] = [album]

    all_photos = photosdb.photos(**query_options) if query_options else photosdb.photos()

    # Close the internal SQLite connection before it gets GC'd in a different thread
    try:
        photosdb._db_connection.close()
    except Exception:
        pass

    # Filter to locally-available photos first (skip iCloud-only)
    photos = [p for p in all_photos if p.path is not None]
    logger.info(
        "Found %d total items, %d available locally (%d iCloud-only)",
        len(all_photos), len(photos), len(all_photos) - len(photos),
    )

    # Apply date range filter
    if date_range is not None:
        start_dt, end_dt = date_range
        photos = [
            p
            for p in photos
            if p.date is not None and start_dt <= p.date <= end_dt
        ]

    # Apply limit
    if limit is not None:
        photos = photos[:limit]

    items: list[MediaItem] = []
    for photo in photos:
        try:
            item = _photo_to_media_item(photo)
            items.append(item)
        except Exception as exc:
            logger.error("Error processing photo %s: %s", photo.uuid, exc)

    logger.info("Retrieved %d media items from Apple Photos", len(items))
    return items
