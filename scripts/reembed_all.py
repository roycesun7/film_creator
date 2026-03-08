#!/usr/bin/env python
"""Re-embed all media using Marengo 3.0 after migration from 2.7.

Run this script once after applying the Supabase migration that changed
the embedding columns from vector(1024) to vector(512).

Usage:
    python scripts/reembed_all.py [--dry-run] [--videos-only] [--images-only]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from urllib.parse import urlparse

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import config
from index import store
from index.twelvelabs_embed import embed_video, embed_image

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

UPLOADS_DIR = config.PROJECT_ROOT / "uploads"


def _resolve_local_path(path: str, uuid: str) -> str | None:
    """Resolve a media path to a local file, checking uploads dir for Supabase URLs."""
    # If it's already a local path and exists, use it
    if not path.startswith("http") and Path(path).exists():
        return path

    # Try to find in uploads/ by UUID-based filename
    if UPLOADS_DIR.is_dir():
        for f in UPLOADS_DIR.iterdir():
            if f.stem == uuid or f.name.startswith(uuid):
                return str(f)

    # Try extracting filename from URL
    if path.startswith("http"):
        url_filename = Path(urlparse(path).path).name
        local = UPLOADS_DIR / url_filename
        if local.exists():
            return str(local)

    return None


def reembed_all(dry_run: bool = False, videos_only: bool = False, images_only: bool = False):
    """Re-compute embeddings for all media using Marengo 3.0."""
    if not config.USE_TWELVELABS:
        logger.error("TWELVELABS_API_KEY is not set. Cannot re-embed.")
        sys.exit(1)

    logger.info("Model: %s, Embedding dim: %d", config.TWELVELABS_MODEL, config.TWELVELABS_EMBEDDING_DIM)

    # Fetch all media records
    client = store._get_client()
    resp = client.table("media").select("uuid, path, media_type").execute()
    all_media = resp.data

    if not all_media:
        logger.info("No media records found. Nothing to re-embed.")
        return

    logger.info("Found %d media records to re-embed.", len(all_media))

    video_exts = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".mts", ".m2ts", ".flv", ".wmv"}
    image_exts = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif", ".tiff", ".bmp"}

    success_count = 0
    fail_count = 0
    skip_count = 0

    for i, item in enumerate(all_media, 1):
        uuid = item["uuid"]
        raw_path = item.get("path", "")
        media_type = item.get("media_type", "")

        # Resolve Supabase Storage URLs to local file paths
        path = _resolve_local_path(raw_path, uuid) if raw_path else None

        ext = Path(path).suffix.lower() if path else ""

        is_video = media_type == "video" or ext in video_exts
        is_image = media_type == "photo" or ext in image_exts

        if videos_only and not is_video:
            skip_count += 1
            continue
        if images_only and not is_image:
            skip_count += 1
            continue

        if not path:
            logger.warning("[%d/%d] File not found, skipping: %s", i, len(all_media), raw_path)
            skip_count += 1
            continue

        if dry_run:
            logger.info("[%d/%d] DRY RUN: would re-embed %s (%s)", i, len(all_media), Path(path).name, media_type)
            continue

        try:
            if is_video:
                logger.info("[%d/%d] Embedding video: %s", i, len(all_media), Path(path).name)
                segments = embed_video(path)
                if segments:
                    # Primary embedding = mean of all segment embeddings
                    mean_emb = np.mean([s["embedding"] for s in segments], axis=0)
                    norm = np.linalg.norm(mean_emb)
                    if norm > 0:
                        mean_emb = mean_emb / norm
                    store.update_embedding(uuid, mean_emb)

                    # Update keyframe embeddings
                    store.delete_keyframe_embeddings(uuid)
                    for seg_idx, seg in enumerate(segments):
                        store.upsert_keyframe_embedding(
                            media_uuid=uuid,
                            keyframe_index=seg_idx,
                            timestamp=seg.get("start_sec"),
                            embedding=seg["embedding"],
                        )
                    logger.info("  -> %d segments stored", len(segments))
                    success_count += 1
                else:
                    logger.warning("  -> No segments returned")
                    fail_count += 1

            elif is_image:
                logger.info("[%d/%d] Embedding image: %s", i, len(all_media), Path(path).name)
                emb = embed_image(path)
                if emb is not None:
                    store.update_embedding(uuid, emb)
                    success_count += 1
                else:
                    logger.warning("  -> Embedding failed")
                    fail_count += 1
            else:
                logger.debug("[%d/%d] Unknown media type, skipping: %s", i, len(all_media), path)
                skip_count += 1

        except Exception as exc:
            logger.error("[%d/%d] Failed to embed %s: %s", i, len(all_media), Path(path).name, exc)
            fail_count += 1

    logger.info(
        "Re-embedding complete: %d succeeded, %d failed, %d skipped (out of %d total)",
        success_count, fail_count, skip_count, len(all_media),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-embed all media with Marengo 3.0")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    parser.add_argument("--videos-only", action="store_true", help="Only re-embed videos")
    parser.add_argument("--images-only", action="store_true", help="Only re-embed images")
    args = parser.parse_args()

    reembed_all(dry_run=args.dry_run, videos_only=args.videos_only, images_only=args.images_only)
