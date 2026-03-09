"""FastAPI backend wrapping the existing video-composer pipeline."""

from __future__ import annotations

import hashlib
import io
import logging
import os
import sys
import threading
import time
import uuid as uuid_mod
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Ensure project root is on sys.path so local imports work
sys.path.insert(0, str(Path(__file__).parent))

import config
from index.store import (
    init_db, list_media, count_media, get_media_by_uuids,
    search_by_description, get_all_embeddings, delete_media, delete_all_media,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("api")

app = FastAPI(title="Video Composer", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173",
                    "http://localhost:5174", "http://127.0.0.1:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve generated videos
os.makedirs(str(config.OUTPUT_DIR), exist_ok=True)
app.mount("/output", StaticFiles(directory=str(config.OUTPUT_DIR)), name="output")

# Uploaded media storage
UPLOADS_DIR = config.PROJECT_ROOT / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".tiff", ".bmp", ".gif"}
ALLOWED_VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
ALLOWED_AUDIO_EXT = {".mp3", ".wav", ".aac", ".m4a", ".ogg", ".flac", ".wma"}

# Music uploads directory
MUSIC_DIR = config.PROJECT_ROOT / "uploads" / "music"
MUSIC_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Thumbnail cache
# ---------------------------------------------------------------------------
THUMB_DIR = config.PROJECT_ROOT / ".thumbnails"
THUMB_DIR.mkdir(exist_ok=True)
THUMB_SIZE = (400, 400)


def _get_thumbnail_path(original_path: str) -> Path:
    h = hashlib.md5(original_path.encode()).hexdigest()
    return THUMB_DIR / f"{h}.jpg"


def _generate_thumbnail(original_path: str) -> Path:
    thumb_path = _get_thumbnail_path(original_path)
    if thumb_path.exists():
        return thumb_path
    try:
        from PIL import Image
        img = Image.open(original_path)
        img.thumbnail(THUMB_SIZE, Image.LANCZOS)
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(str(thumb_path), "JPEG", quality=80)
        return thumb_path
    except Exception as exc:
        logger.warning("Thumbnail generation failed for %s: %s", original_path, exc)
        raise


# ---------------------------------------------------------------------------
# Background job tracking
# ---------------------------------------------------------------------------
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _update_job(job_id: str, **kwargs):
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update(kwargs)
            _jobs[job_id]["updated_at"] = time.time()


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class SearchRequest(BaseModel):
    query: str
    albums: Optional[list[str]] = None
    persons: Optional[list[str]] = None
    min_quality: Optional[float] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    limit: int = 20
    fast: bool = False


class IndexRequest(BaseModel):
    limit: Optional[int] = 50
    album: Optional[str] = None
    after: Optional[str] = None
    before: Optional[str] = None
    describe: bool = False
    force: bool = False


class PreviewRequest(BaseModel):
    prompt: str
    duration: float = 60.0
    albums: Optional[list[str]] = None
    persons: Optional[list[str]] = None
    min_quality: Optional[float] = None
    num_candidates: int = 30
    uuids: Optional[list[str]] = None


class GenerateRequest(BaseModel):
    prompt: str
    duration: float = 60.0
    theme: str = "minimal"
    music: Optional[str] = None
    albums: Optional[list[str]] = None
    persons: Optional[list[str]] = None
    min_quality: Optional[float] = None
    num_candidates: int = 30
    uuids: Optional[list[str]] = None


class CustomShotInput(BaseModel):
    uuid: str
    start_time: float
    end_time: float
    role: str = "highlight"
    reason: str = ""


class CustomGenerateRequest(BaseModel):
    shots: list[CustomShotInput]
    title: str = "Custom Video"
    theme: str = "minimal"
    music_path: Optional[str] = None


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
def startup():
    init_db()


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@app.get("/api/stats")
def get_stats():
    from index.store import _get_client
    client = _get_client()

    # All media
    all_resp = client.table("media").select("uuid, media_type, date, albums, persons, quality_score, description, embedding, clip_embedding").execute()
    rows = all_resp.data or []

    total = len(rows)
    photos = sum(1 for r in rows if r.get("media_type") == "photo")
    videos = sum(1 for r in rows if r.get("media_type") == "video")
    with_emb = sum(1 for r in rows if r.get("embedding") is not None or r.get("clip_embedding") is not None)
    with_desc = sum(1 for r in rows if r.get("description") and r["description"] != {})

    dates = [r["date"] for r in rows if r.get("date")]
    earliest = min(dates) if dates else None
    latest = max(dates) if dates else None

    # Top albums
    album_counts: dict[str, int] = {}
    for row in rows:
        for album in (row.get("albums") or []):
            album_counts[album] = album_counts.get(album, 0) + 1
    top_albums = sorted(album_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # Top persons
    person_counts: dict[str, int] = {}
    for row in rows:
        for person in (row.get("persons") or []):
            person_counts[person] = person_counts.get(person, 0) + 1
    top_persons = sorted(person_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # Average quality
    quality_scores = [r["quality_score"] for r in rows if r.get("quality_score") is not None]
    avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else None

    return {
        "total": total,
        "photos": photos,
        "videos": videos,
        "with_embeddings": with_emb,
        "with_descriptions": with_desc,
        "date_range": {"earliest": earliest, "latest": latest} if earliest else None,
        "top_albums": [{"name": n, "count": c} for n, c in top_albums],
        "top_persons": [{"name": n, "count": c} for n, c in top_persons],
        "avg_quality": round(avg_quality, 1) if avg_quality else None,
    }


# ---------------------------------------------------------------------------
# Media browsing
# ---------------------------------------------------------------------------

@app.get("/api/media")
def get_media(
    limit: int = Query(24, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort: str = Query("date", pattern="^(date|quality|recent)$"),
    media_type: str | None = Query(None, pattern="^(photo|video)$"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
):
    items = list_media(limit=limit, offset=offset, sort_by=sort, media_type=media_type,
                       date_from=date_from, date_to=date_to)
    total = count_media(media_type=media_type, date_from=date_from, date_to=date_to)
    # Add has_embedding flag, then strip the large embedding vectors
    for item in items:
        item["has_embedding"] = item.get("embedding") is not None
        item.pop("embedding", None)
        item.pop("clip_embedding", None)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@app.get("/api/media/{media_uuid}")
def get_media_detail(media_uuid: str):
    items = get_media_by_uuids([media_uuid])
    if not items:
        raise HTTPException(status_code=404, detail="Media not found")
    item = items[0]
    item["has_embedding"] = item.get("embedding") is not None
    item.pop("embedding", None)
    item.pop("clip_embedding", None)
    return item


def _resolve_local_path(path: str, media_uuid: str) -> str | None:
    """Return a local file path for a media item, checking local uploads first."""
    # Check if it's already a local path
    if os.path.exists(path):
        return path
    # Check if local copy exists in uploads/
    for f in UPLOADS_DIR.iterdir():
        if f.stem == media_uuid:
            return str(f)
    return None


@app.get("/api/media/{media_uuid}/thumbnail")
def get_thumbnail(media_uuid: str):
    items = get_media_by_uuids([media_uuid])
    if not items:
        raise HTTPException(status_code=404, detail="Media not found")
    path = items[0].get("path", "")
    media_type = items[0].get("media_type", "photo")

    # If path is a Supabase Storage URL, check for a cached thumbnail or
    # try to use the local copy in uploads/
    local_path = _resolve_local_path(path, media_uuid)

    if local_path is None:
        # No local file — redirect to storage URL for images
        if media_type == "photo" and path.startswith("http"):
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url=path)
        raise HTTPException(status_code=404, detail="Source file not found")

    if media_type == "video":
        try:
            import subprocess
            thumb_path = _get_thumbnail_path(local_path)
            if not thumb_path.exists():
                subprocess.run(
                    ["ffmpeg", "-y", "-i", local_path, "-ss", "1", "-vframes", "1",
                     "-vf", f"scale={THUMB_SIZE[0]}:-1", str(thumb_path)],
                    capture_output=True, timeout=10,
                )
            if thumb_path.exists():
                return FileResponse(str(thumb_path), media_type="image/jpeg")
        except Exception:
            pass
        raise HTTPException(status_code=404, detail="Could not generate video thumbnail")

    try:
        thumb_path = _generate_thumbnail(local_path)
        return FileResponse(str(thumb_path), media_type="image/jpeg")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/media/{media_uuid}/video")
def serve_video(media_uuid: str):
    """Serve the original video file for playback."""
    items = get_media_by_uuids([media_uuid])
    if not items:
        raise HTTPException(status_code=404, detail="Media not found")
    item = items[0]
    if item.get("media_type") != "video":
        raise HTTPException(status_code=400, detail="Not a video")
    path = item.get("path", "")

    # Try local file first, then redirect to Supabase Storage
    local_path = _resolve_local_path(path, media_uuid)

    if local_path:
        ext = Path(local_path).suffix.lower()
        content_types = {
            ".mp4": "video/mp4", ".mov": "video/quicktime", ".m4v": "video/mp4",
            ".avi": "video/x-msvideo", ".mkv": "video/x-matroska", ".webm": "video/webm",
        }
        return FileResponse(local_path, media_type=content_types.get(ext, "video/mp4"))

    if path.startswith("http"):
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=path)

    raise HTTPException(status_code=404, detail="Source file not found")


@app.delete("/api/media/{media_uuid}")
def delete_media_item(media_uuid: str):
    from index.store import get_media_by_uuids

    # Look up the record first so we can clean up files
    items = get_media_by_uuids([media_uuid])
    if not items:
        raise HTTPException(status_code=404, detail="Media not found")

    item = items[0]
    path = item.get("path", "")

    # Delete keyframe embeddings + storage files
    try:
        from index.store import _get_client
        client = _get_client()
        client.table("keyframe_embeddings").delete().eq("media_uuid", media_uuid).execute()
    except Exception as exc:
        logger.warning("Failed to delete keyframe embeddings for %s: %s", media_uuid[:8], exc)

    if "supabase.co/storage" in path:
        try:
            from index.store import _get_client
            sb = _get_client()
            storage_filename = Path(urlparse(path).path).name
            sb.storage.from_("media").remove([storage_filename])
        except Exception as exc:
            logger.warning("Failed to delete from Supabase Storage for %s: %s", media_uuid[:8], exc)

    try:
        from index.store import _get_client
        _get_client().storage.from_("thumbnails").remove([f"{media_uuid}.jpg"])
    except Exception:
        pass

    # Delete local file(s)
    for ext in (".jpg", ".jpeg", ".png", ".heic", ".mp4", ".mov", ".m4v", ".webp"):
        local = UPLOADS_DIR / f"{media_uuid}{ext}"
        if local.exists():
            local.unlink(missing_ok=True)

    # Delete DB record
    if delete_media(media_uuid):
        return {"deleted": True, "uuid": media_uuid}
    raise HTTPException(status_code=404, detail="Media not found")


# ---------------------------------------------------------------------------
# File upload
# ---------------------------------------------------------------------------

def _extract_creation_date(file_path: str, media_type: str) -> str | None:
    """Extract the original creation date from a media file.

    Photos: EXIF DateTimeOriginal / DateTimeDigitized / DateTime
    Videos: ffprobe format tags (creation_time, com.apple.quicktime.creationdate)
    Falls back to file modification time if no embedded metadata found.
    """
    creation_date = None

    if media_type == "photo":
        try:
            from PIL import Image
            img = Image.open(file_path)
            exif = img.getexif()
            if exif:
                # Try root EXIF: DateTimeOriginal (36867), DateTimeDigitized (36868), DateTime (306)
                for tag_id in (36867, 36868, 306):
                    val = exif.get(tag_id)
                    if val and isinstance(val, str):
                        try:
                            dt = datetime.strptime(val, "%Y:%m:%d %H:%M:%S")
                            creation_date = dt.isoformat()
                        except (ValueError, TypeError):
                            pass
                        if creation_date:
                            break
                # Also check ExifIFD SubIFD for DateTimeOriginal/Digitized
                if not creation_date:
                    try:
                        sub = exif.get_ifd(0x8769)  # ExifIFD
                    except Exception:
                        sub = None
                    if sub:
                        for tag_id in (36867, 36868):
                            val = sub.get(tag_id)
                            if val and isinstance(val, str):
                                try:
                                    dt = datetime.strptime(val, "%Y:%m:%d %H:%M:%S")
                                    creation_date = dt.isoformat()
                                except (ValueError, TypeError):
                                    pass
                                if creation_date:
                                    break
        except Exception as exc:
            logger.debug("EXIF extraction failed for %s: %s", file_path, exc)
    else:
        # Video: use ffprobe to get creation_time from format tags
        try:
            import subprocess, json as _json
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_format", file_path],
                capture_output=True, text=True, timeout=10,
            )
            info = _json.loads(result.stdout)
            tags = info.get("format", {}).get("tags", {})
            # Try various tag names (case-insensitive in ffprobe output)
            for key in ("creation_time", "com.apple.quicktime.creationdate", "date"):
                val = tags.get(key)
                if val:
                    # ffprobe dates are usually ISO format: 2024-07-15T14:30:00.000000Z
                    try:
                        # Strip timezone suffix for consistent storage
                        clean = val.replace("Z", "").split("+")[0].split(".")[0]
                        dt = datetime.fromisoformat(clean)
                        creation_date = dt.isoformat()
                    except (ValueError, TypeError):
                        pass
                    break
        except Exception as exc:
            logger.debug("Video date extraction failed for %s: %s", file_path, exc)

    # Fall back to file modification time
    if not creation_date:
        try:
            mtime = Path(file_path).stat().st_mtime
            creation_date = datetime.fromtimestamp(mtime).isoformat()
        except Exception:
            creation_date = datetime.utcnow().isoformat()

    return creation_date


def _get_media_dimensions(file_path: str, media_type: str):
    """Extract width, height, and duration from a media file."""
    width, height, duration = 0, 0, None
    if media_type == "photo":
        try:
            from PIL import Image
            img = Image.open(file_path)
            width, height = img.size
        except Exception:
            pass
    else:
        try:
            import subprocess, json as _json
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_streams", file_path],
                capture_output=True, text=True, timeout=10,
            )
            info = _json.loads(result.stdout)
            for stream in info.get("streams", []):
                if stream.get("codec_type") == "video":
                    width = int(stream.get("width", 0))
                    height = int(stream.get("height", 0))
                    dur = stream.get("duration")
                    if dur:
                        duration = float(dur)
                    break
        except Exception:
            pass
    return width, height, duration


def _embed_with_twelvelabs(file_path: str, media_type: str, media_uuid: str):
    """Use Twelve Labs Marengo for embedding. Returns (primary_embedding, segment_list)."""
    from index.twelvelabs_embed import embed_image, embed_video
    from index.store import upsert_keyframe_embedding

    if media_type == "video":
        segments = embed_video(file_path)
        if segments:
            import numpy as np
            # Primary embedding = average of all segments (more representative than first only)
            all_embs = np.stack([seg["embedding"] for seg in segments])
            primary = all_embs.mean(axis=0)
            primary = primary / np.linalg.norm(primary)  # re-normalize
            # Store all segments as keyframe embeddings for temporal search
            for i, seg in enumerate(segments):
                upsert_keyframe_embedding(media_uuid, i, seg["start_sec"], seg["embedding"])
            return primary
    else:
        emb = embed_image(file_path)
        if emb is not None:
            return emb
    return None


def _embed_with_clip(file_path: str, media_type: str):
    """Fallback: use local CLIP for embedding."""
    from index.clip_embeddings import embed_image
    embed_path = file_path
    if media_type == "video":
        thumb_path = _get_thumbnail_path(file_path)
        if not thumb_path.exists():
            import subprocess
            subprocess.run(
                ["ffmpeg", "-y", "-i", file_path, "-ss", "1", "-vframes", "1",
                 str(thumb_path)],
                capture_output=True, timeout=10,
            )
        if thumb_path.exists():
            embed_path = str(thumb_path)
    return embed_image(embed_path)


def _energy_to_quality(analysis) -> float:
    """Map a VideoAnalysis energy_score into a quality_score-compatible value.

    Higher energy clips get a slight quality boost to surface them during
    search ranking, but the base is the visual_quality assessment.
    """
    quality_map = {"excellent": 9.0, "good": 7.0, "fair": 5.0, "poor": 3.0}
    base = quality_map.get(analysis.visual_quality, 7.0)
    # Add up to 1 point for high energy
    return round(base + analysis.energy_score, 1)


def _process_upload_embedding(file_path: str, media_uuid: str, media_type: str, describe: bool = True):
    """Background: compute embedding (Twelve Labs or CLIP) and optionally AI-describe."""
    from index.store import update_embedding, upsert_media, get_media_by_uuids
    try:
        embedding = None

        if config.USE_TWELVELABS:
            try:
                embedding = _embed_with_twelvelabs(file_path, media_type, media_uuid)
            except Exception as exc:
                logger.warning("Twelve Labs embedding failed for %s, falling back to CLIP: %s",
                               media_uuid[:8], exc)

        if embedding is None:
            try:
                embedding = _embed_with_clip(file_path, media_type)
            except Exception as exc:
                logger.warning("CLIP embedding also failed for %s: %s", media_uuid[:8], exc)

        if embedding is not None:
            update_embedding(media_uuid, embedding)

        if describe:
            try:
                from index.vision_describe import describe_image
                import tempfile
                describe_path = file_path
                tmp_frame = None
                if media_type == "video":
                    # Extract a mid-point frame for description
                    tmp_frame = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
                    items_for_dur = get_media_by_uuids([media_uuid])
                    mid = (items_for_dur[0].get("duration", 5) / 2) if items_for_dur else 2
                    subprocess.run(
                        ["ffmpeg", "-y", "-ss", str(mid), "-i", file_path,
                         "-frames:v", "1", "-q:v", "2", tmp_frame.name],
                        capture_output=True, timeout=10,
                    )
                    if Path(tmp_frame.name).stat().st_size > 0:
                        describe_path = tmp_frame.name
                    else:
                        describe_path = None  # skip if extraction failed

                if describe_path:
                    description = describe_image(describe_path)
                    quality_score = description.get("quality_score")
                    items = get_media_by_uuids([media_uuid])
                    if items:
                        item = items[0]
                        item["description"] = description
                        item["quality_score"] = quality_score
                        labels = description.get("subjects", [])
                        if description.get("activity"):
                            labels.append(description["activity"])
                        item["labels"] = labels
                        upsert_media(item)
                    logger.info("AI description generated for %s", media_uuid[:8])

                if tmp_frame:
                    Path(tmp_frame.name).unlink(missing_ok=True)
            except Exception as exc:
                logger.warning("Vision describe failed for %s: %s", media_uuid[:8], exc)

        # After embedding and description, trigger TL analysis for videos
        if media_type == "video" and config.USE_TWELVELABS:
            try:
                from index.twelvelabs_analyze import analyze_video
                logger.info("Running Twelve Labs video analysis for %s", media_uuid[:8])
                analysis = analyze_video(file_path, media_uuid)
                if analysis:
                    logger.info("TL analysis complete: %s", analysis.summary[:60])
                    # Store energy-derived quality score in the media record
                    from index.store import _get_client as get_supabase
                    client = get_supabase()
                    client.table("media").update({
                        "quality_score": _energy_to_quality(analysis),
                    }).eq("uuid", media_uuid).execute()
            except Exception as exc:
                logger.warning("TL analysis failed for %s: %s", media_uuid[:8], exc)

        logger.info("Embedding processed: %s (%s) [%s]", media_uuid[:8], media_type,
                     "Twelve Labs" if config.USE_TWELVELABS and embedding is not None else "CLIP")
    except Exception as exc:
        logger.error("Failed to process embedding for %s: %s", media_uuid, exc, exc_info=True)


def _upload_to_supabase_storage(content: bytes, bucket: str, path: str, content_type: str) -> str:
    """Upload a file to Supabase Storage and return the public URL."""
    from index.store import _get_client
    client = _get_client()
    client.storage.from_(bucket).upload(path, content, {"content-type": content_type})
    return f"{config.SUPABASE_URL}/storage/v1/object/public/{bucket}/{path}"


@app.post("/api/upload")
async def upload_files(files: list[UploadFile] = File(...), describe: bool = Query(True)):
    """Upload photos/videos from the user's filesystem."""
    from index.store import upsert_media
    results = []
    for file in files:
        ext = Path(file.filename or "").suffix.lower()

        if ext in ALLOWED_IMAGE_EXT:
            media_type = "photo"
        elif ext in ALLOWED_VIDEO_EXT:
            media_type = "video"
        else:
            results.append({"filename": file.filename, "error": f"Unsupported file type: {ext}"})
            continue

        media_uuid = str(uuid_mod.uuid4())
        safe_name = f"{media_uuid}{ext}"

        content = await file.read()

        # Save locally for embedding computation (Twelve Labs needs a file path)
        dest = UPLOADS_DIR / safe_name
        dest.write_bytes(content)
        file_path = str(dest)

        # Convert HEIC to JPEG — HEIC isn't supported by PIL, Twelve Labs, or most tools
        if ext == ".heic":
            jpeg_name = f"{media_uuid}.jpg"
            jpeg_path = UPLOADS_DIR / jpeg_name
            try:
                subprocess.run(
                    ["sips", "-s", "format", "jpeg", file_path, "--out", str(jpeg_path)],
                    capture_output=True, timeout=30, check=True,
                )
                file_path = str(jpeg_path)
                safe_name = jpeg_name
                ext = ".jpg"
                content = jpeg_path.read_bytes()
                # Remove the original HEIC
                dest.unlink(missing_ok=True)
                logger.info("Converted HEIC to JPEG: %s", jpeg_name)
            except Exception as exc:
                logger.warning("HEIC conversion failed for %s: %s", media_uuid[:8], exc)

        # Upload to Supabase Storage
        content_types = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
            ".heic": "image/heic", ".webp": "image/webp", ".gif": "image/gif",
            ".mp4": "video/mp4", ".mov": "video/quicktime", ".m4v": "video/mp4",
            ".avi": "video/x-msvideo", ".mkv": "video/x-matroska", ".webm": "video/webm",
        }
        try:
            storage_url = _upload_to_supabase_storage(
                content, "media", safe_name, content_types.get(ext, "application/octet-stream")
            )
        except Exception as exc:
            logger.warning("Supabase Storage upload failed for %s: %s", safe_name, exc)
            storage_url = None

        # Get dimensions and creation date immediately so the record is useful right away
        width, height, duration = _get_media_dimensions(file_path, media_type)
        creation_date = _extract_creation_date(file_path, media_type)

        # Store the Supabase storage path, but keep local path for embedding
        record = {
            "uuid": media_uuid,
            "path": storage_url or file_path,
            "media_type": media_type,
            "date": creation_date,
            "lat": None,
            "lon": None,
            "albums": [],
            "labels": [],
            "persons": [],
            "width": width,
            "height": height,
            "duration": duration,
            "description": {},
            "embedding": None,
            "quality_score": None,
        }
        upsert_media(record)

        # Compute embedding (and optionally describe) in background thread
        thread = threading.Thread(
            target=_process_upload_embedding,
            args=(file_path, media_uuid, media_type, describe),
            daemon=True,
        )
        thread.start()

        results.append({
            "filename": file.filename,
            "uuid": media_uuid,
            "media_type": media_type,
            "status": "processing",
        })

    return {"uploaded": len([r for r in results if "error" not in r]), "results": results}


# ---------------------------------------------------------------------------
# Music upload
# ---------------------------------------------------------------------------

@app.post("/api/upload-music")
async def upload_music(file: UploadFile = File(...)):
    """Upload a music/audio file for use as video soundtrack."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_AUDIO_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format: {ext}. Allowed: {', '.join(sorted(ALLOWED_AUDIO_EXT))}",
        )

    safe_name = f"{uuid_mod.uuid4().hex[:12]}{ext}"
    dest = MUSIC_DIR / safe_name
    content = await file.read()
    dest.write_bytes(content)

    return {
        "path": str(dest),
        "filename": file.filename or safe_name,
    }


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@app.post("/api/search")
def search_media(req: SearchRequest):
    if req.fast:
        results = search_by_description(query=req.query, limit=req.limit)
    else:
        from curate.search import hybrid_search
        date_range = None
        if req.date_from or req.date_to:
            date_range = (req.date_from or "", req.date_to or "")
        results = hybrid_search(
            query=req.query,
            albums=req.albums,
            persons=req.persons,
            date_range=date_range,
            min_quality=req.min_quality,
            limit=req.limit,
        )
    for r in results:
        r.pop("embedding", None)
    return {"results": results, "count": len(results), "query": req.query}


# ---------------------------------------------------------------------------
# Indexing (background task)
# ---------------------------------------------------------------------------

def _run_index_job(job_id: str, req: IndexRequest):
    try:
        from index.apple_photos import get_media_items
        from index.clip_embeddings import embed_image, embed_images
        from index.vision_describe import describe_image
        from index.store import upsert_media, upsert_keyframe_embedding, get_indexed_uuids

        _update_job(job_id, status="running",
                    message="Reading Apple Photos library (requires Full Disk Access)...")

        date_range = None
        if req.after or req.before:
            start = datetime.fromisoformat(req.after) if req.after else datetime.min
            end = datetime.fromisoformat(req.before) if req.before else datetime.max
            date_range = (start, end)

        try:
            items = get_media_items(limit=req.limit, album=req.album, date_range=date_range)
        except Exception as exc:
            _update_job(job_id, status="failed",
                        message=f"Failed to read Apple Photos. Grant Full Disk Access to your terminal and restart it. Error: {exc}")
            return
        _update_job(job_id, message=f"Found {len(items)} locally-available items")

        if not items:
            _update_job(job_id, status="completed", message="No items found", progress=100)
            return

        if not req.force:
            existing = get_indexed_uuids()
            items = [i for i in items if i.uuid not in existing]
            if not items:
                _update_job(job_id, status="completed", message="All items already indexed", progress=100)
                return

        total = len(items)
        for idx, item in enumerate(items):
            pct = int((idx / total) * 100)
            _update_job(job_id, progress=pct, message=f"Processing {idx+1}/{total}: {item.uuid[:8]}...")

            if item.path is None:
                continue

            embed_path = item.path if item.media_type == "photo" else (
                item.keyframe_paths[0] if item.keyframe_paths else None
            )

            embedding = None
            if embed_path:
                try:
                    embedding = embed_image(embed_path)
                except Exception:
                    pass

            description = {}
            quality_score = None
            if req.describe and embed_path:
                try:
                    description = describe_image(embed_path)
                    quality_score = description.get("quality_score")
                except Exception:
                    pass

            record = {
                "uuid": item.uuid,
                "path": item.path,
                "media_type": item.media_type,
                "date": item.date.isoformat() if item.date else None,
                "lat": item.location[0] if item.location else None,
                "lon": item.location[1] if item.location else None,
                "albums": item.albums,
                "labels": item.labels,
                "persons": item.persons,
                "width": item.width,
                "height": item.height,
                "duration": item.duration,
                "description": description,
                "embedding": embedding,
                "quality_score": quality_score,
            }
            upsert_media(record)

            if item.media_type == "video" and item.keyframe_paths:
                kf_embs = embed_images(item.keyframe_paths)
                for ki, (kpath, kemb) in enumerate(zip(item.keyframe_paths, kf_embs)):
                    upsert_keyframe_embedding(item.uuid, ki, ki * 2.0, kemb)

        _update_job(job_id, status="completed", progress=100,
                    message=f"Indexed {total} items successfully")

    except Exception as exc:
        logger.error("Index job %s failed: %s", job_id, exc, exc_info=True)
        _update_job(job_id, status="failed", message=str(exc))


@app.post("/api/index")
def start_indexing(req: IndexRequest):
    job_id = str(uuid_mod.uuid4())[:8]
    with _jobs_lock:
        _jobs[job_id] = {
            "id": job_id,
            "type": "index",
            "status": "queued",
            "progress": 0,
            "message": "Starting...",
            "created_at": time.time(),
            "updated_at": time.time(),
        }
    thread = threading.Thread(target=_run_index_job, args=(job_id, req), daemon=True)
    thread.start()
    return {"job_id": job_id, "status": "queued"}


# ---------------------------------------------------------------------------
# Preview (EDL)
# ---------------------------------------------------------------------------

@app.post("/api/preview")
def preview_video(req: PreviewRequest):
    from curate.search import hybrid_search
    from curate.director import create_edit_decision_list
    from dataclasses import asdict

    if req.uuids:
        candidates = get_media_by_uuids(req.uuids)
        # Strip embeddings from candidates
        for c in candidates:
            c.pop("embedding", None)
            c.pop("clip_embedding", None)
    else:
        candidates = hybrid_search(
            query=req.prompt,
            albums=req.albums,
            persons=req.persons,
            min_quality=req.min_quality,
            limit=req.num_candidates,
        )

    if not candidates:
        raise HTTPException(status_code=404, detail="No matching media found. Index some media first.")

    edl = create_edit_decision_list(
        candidates=candidates,
        prompt=req.prompt,
        target_duration=req.duration,
    )

    shots = []
    for shot in edl.shots:
        shots.append({
            "uuid": shot.uuid,
            "path": shot.path,
            "media_type": shot.media_type,
            "start_time": shot.start_time,
            "end_time": shot.end_time,
            "duration": shot.end_time - shot.start_time,
            "role": shot.role,
            "reason": shot.reason,
        })

    return {
        "title": edl.title,
        "narrative_summary": edl.narrative_summary,
        "music_mood": edl.music_mood,
        "estimated_duration": edl.estimated_duration,
        "shots": shots,
    }


# ---------------------------------------------------------------------------
# Generate (background task)
# ---------------------------------------------------------------------------

def _run_generate_job(job_id: str, req: GenerateRequest):
    try:
        from curate.search import hybrid_search
        from curate.director import create_edit_decision_list
        from assemble import get_build_video
        build_video = get_build_video()

        _update_job(job_id, status="running", message="Searching for matching clips...")

        if req.uuids:
            candidates = get_media_by_uuids(req.uuids)
            for c in candidates:
                c.pop("embedding", None)
                c.pop("clip_embedding", None)
        else:
            candidates = hybrid_search(
                query=req.prompt,
                albums=req.albums,
                persons=req.persons,
                min_quality=req.min_quality,
                limit=req.num_candidates,
            )

        if not candidates:
            _update_job(job_id, status="failed", message="No matching media found")
            return

        _update_job(job_id, progress=20, message=f"Found {len(candidates)} clips. AI director planning...")

        edl = create_edit_decision_list(
            candidates=candidates,
            prompt=req.prompt,
            target_duration=req.duration,
        )

        _update_job(job_id, progress=40, message=f"EDL ready: {len(edl.shots)} shots. Rendering...")

        def _on_progress(pct: int, msg: str):
            # Map builder's 10-85% to our 40-95% range
            mapped = 40 + int((pct / 100) * 55)
            _update_job(job_id, progress=min(mapped, 95), message=msg)

        output_path = build_video(
            edl=edl,
            theme_name=req.theme,
            music_path=req.music,
            progress_callback=_on_progress,
        )

        filename = Path(output_path).name
        _update_job(job_id, status="completed", progress=100,
                    message="Video rendered successfully",
                    output_path=f"/output/{filename}",
                    title=edl.title)

    except Exception as exc:
        logger.error("Generate job %s failed: %s", job_id, exc, exc_info=True)
        _update_job(job_id, status="failed", message=str(exc))


@app.post("/api/generate")
def start_generate(req: GenerateRequest):
    job_id = str(uuid_mod.uuid4())[:8]
    with _jobs_lock:
        _jobs[job_id] = {
            "id": job_id,
            "type": "generate",
            "status": "queued",
            "progress": 0,
            "message": "Starting...",
            "created_at": time.time(),
            "updated_at": time.time(),
        }
    thread = threading.Thread(target=_run_generate_job, args=(job_id, req), daemon=True)
    thread.start()
    return {"job_id": job_id, "status": "queued"}


# ---------------------------------------------------------------------------
# Custom generate (user-reordered EDL)
# ---------------------------------------------------------------------------

def _run_custom_generate_job(job_id: str, req: CustomGenerateRequest):
    try:
        from curate.director import Shot as DShot, EditDecisionList
        from assemble import get_build_video
        build_video = get_build_video()

        _update_job(job_id, status="running", message="Resolving media paths...")

        # Look up actual file paths for each shot UUID
        uuids = [s.uuid for s in req.shots]
        media_items = get_media_by_uuids(uuids)
        path_map = {m["uuid"]: m for m in media_items}

        shots = []
        for s in req.shots:
            info = path_map.get(s.uuid)
            if not info:
                logger.warning("UUID %s not found, skipping", s.uuid)
                continue

            # Resolve to local path if possible
            local_path = _resolve_local_path(info.get("path", ""), s.uuid)
            path = local_path or info.get("path", "")

            shots.append(DShot(
                uuid=s.uuid,
                path=path,
                media_type=info.get("media_type", "photo"),
                start_time=s.start_time,
                end_time=s.end_time,
                role=s.role,
                reason=s.reason,
            ))

        if not shots:
            _update_job(job_id, status="failed", message="No valid shots found")
            return

        edl = EditDecisionList(
            shots=shots,
            title=req.title,
            narrative_summary=f"Custom edit with {len(shots)} shots",
            estimated_duration=sum(s.end_time - s.start_time for s in shots),
            music_mood="custom",
        )

        _update_job(job_id, progress=40, message=f"Rendering {len(shots)} shots...")

        def _on_progress(pct: int, msg: str):
            mapped = 40 + int((pct / 100) * 55)
            _update_job(job_id, progress=min(mapped, 95), message=msg)

        output_path = build_video(
            edl=edl,
            theme_name=req.theme,
            music_path=req.music_path,
            progress_callback=_on_progress,
        )

        filename = Path(output_path).name
        _update_job(job_id, status="completed", progress=100,
                    message="Video rendered successfully",
                    output_path=f"/output/{filename}",
                    title=req.title)

    except Exception as exc:
        logger.error("Custom generate job %s failed: %s", job_id, exc, exc_info=True)
        _update_job(job_id, status="failed", message=str(exc))


@app.post("/api/generate-custom")
def start_custom_generate(req: CustomGenerateRequest):
    if not req.shots:
        raise HTTPException(status_code=400, detail="At least one shot is required")
    job_id = str(uuid_mod.uuid4())[:8]
    with _jobs_lock:
        _jobs[job_id] = {
            "id": job_id,
            "type": "generate-custom",
            "status": "queued",
            "progress": 0,
            "message": "Starting custom render...",
            "created_at": time.time(),
            "updated_at": time.time(),
        }
    thread = threading.Thread(target=_run_custom_generate_job, args=(job_id, req), daemon=True)
    thread.start()
    return {"job_id": job_id, "status": "queued"}


# ---------------------------------------------------------------------------
# Job status
# ---------------------------------------------------------------------------

@app.get("/api/jobs/{job_id}")
def get_job_status(job_id: str):
    with _jobs_lock:
        if job_id not in _jobs:
            raise HTTPException(status_code=404, detail="Job not found")
        return dict(_jobs[job_id])


@app.get("/api/jobs")
def list_jobs():
    with _jobs_lock:
        return {"jobs": [dict(j) for j in _jobs.values()]}


# ---------------------------------------------------------------------------
# Generated videos listing
# ---------------------------------------------------------------------------

@app.get("/api/videos")
def list_videos():
    videos = []
    for f in sorted(config.OUTPUT_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = f.stat()
        videos.append({
            "filename": f.name,
            "path": f"/output/{f.name}",
            "size_mb": round(stat.st_size / 1_048_576, 1),
            "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return {"videos": videos}


@app.delete("/api/videos/{filename}")
def delete_video(filename: str):
    # Validate filename: no path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    filepath = (config.OUTPUT_DIR / filename).resolve()
    # Ensure resolved path is still within OUTPUT_DIR
    if not str(filepath).startswith(str(config.OUTPUT_DIR.resolve())):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Video not found")
    filepath.unlink()
    # Also remove cached thumbnail if it exists
    thumb = _get_thumbnail_path(str(filepath))
    if thumb.exists():
        thumb.unlink()
    return {"deleted": True, "filename": filename}


@app.get("/api/videos/{filename}/thumbnail")
def get_video_thumbnail(filename: str):
    # Validate filename: no path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    filepath = (config.OUTPUT_DIR / filename).resolve()
    if not str(filepath).startswith(str(config.OUTPUT_DIR.resolve())):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Video not found")
    thumb_path = _get_thumbnail_path(str(filepath))
    if not thumb_path.exists():
        try:
            import subprocess
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(filepath), "-ss", "1", "-vframes", "1",
                 "-vf", f"scale={THUMB_SIZE[0]}:-1", str(thumb_path)],
                capture_output=True, timeout=10,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Thumbnail generation failed: {exc}")
    if not thumb_path.exists():
        raise HTTPException(status_code=500, detail="Thumbnail generation produced no output")
    return FileResponse(str(thumb_path), media_type="image/jpeg")


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

from projects import (
    Project as ProjectModel,
    Track,
    save_project,
    load_project,
    list_projects as list_projects_fn,
    delete_project as delete_project_fn,
    edl_to_project,
    _project_to_dict,
    _dict_to_project,
)


class CreateProjectRequest(BaseModel):
    name: str = "Untitled Project"
    prompt: str = ""
    theme: str = "minimal"


class UpdateProjectRequest(BaseModel):
    """Accepts a full or partial project dict for saving."""
    project: dict


@app.get("/api/projects")
def api_list_projects():
    return {"projects": list_projects_fn()}


@app.post("/api/projects")
def api_create_project(req: CreateProjectRequest):
    project = ProjectModel(name=req.name, prompt=req.prompt, theme=req.theme)
    # Create default tracks so the timeline is usable immediately
    project.timeline.tracks = [
        Track(name="Main Video", type="video"),
        Track(name="Titles", type="text"),
        Track(name="Music", type="audio"),
    ]
    project_id = save_project(project)
    return {"id": project_id, "project": _project_to_dict(project)}


@app.get("/api/projects/{project_id}")
def api_get_project(project_id: str):
    try:
        project = load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    return _project_to_dict(project)


@app.put("/api/projects/{project_id}")
def api_update_project(project_id: str, req: UpdateProjectRequest):
    try:
        existing = load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")

    # Merge the incoming dict into the existing project
    data = req.project
    data["id"] = project_id  # prevent ID change
    data["created_at"] = existing.created_at  # preserve creation time
    project = _dict_to_project(data)
    save_project(project)
    return _project_to_dict(project)


@app.delete("/api/projects/{project_id}")
def api_delete_project(project_id: str):
    if delete_project_fn(project_id):
        return {"deleted": True}
    raise HTTPException(status_code=404, detail="Project not found")


@app.post("/api/projects/{project_id}/preview")
def api_project_preview(project_id: str):
    """Generate an EDL from the project's prompt, convert to timeline, and save.

    Returns a job_id immediately. Poll /api/jobs/{job_id} for progress.
    When complete, the job will have status='completed' and the updated project data.
    """
    try:
        project = load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")

    if not project.prompt:
        raise HTTPException(status_code=400, detail="Project has no prompt")

    job_id = uuid_mod.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {
            "id": job_id,
            "type": "ai_arrange",
            "status": "queued",
            "progress": 0,
            "message": "Starting AI arrangement...",
            "created_at": time.time(),
            "updated_at": time.time(),
            "project_id": project_id,
        }

    thread = threading.Thread(
        target=_run_ai_arrange,
        args=(job_id, project_id),
        daemon=True,
    )
    thread.start()

    return {"job_id": job_id}


def _run_ai_arrange(job_id: str, project_id: str):
    """Background thread: search media, enrich clips, analyze music, run AI director."""
    try:
        _update_job(job_id, status="running", progress=5, message="Loading project...")
        project = load_project(project_id)

        # Step 1: Search for candidate clips
        _update_job(job_id, progress=10, message="Searching media library...")

        from curate.search import hybrid_search
        from curate.director import create_edit_decision_list
        from dataclasses import asdict as dc_asdict

        candidates = hybrid_search(query=project.prompt, limit=30)
        for c in candidates:
            c.pop("embedding", None)
            c.pop("clip_embedding", None)

        _update_job(job_id, progress=25, message=f"Found {len(candidates)} clips. Enriching with AI analysis...")

        # Step 2: Enrich candidates with TL Analyze data
        if config.USE_TWELVELABS:
            try:
                from index.twelvelabs_analyze import get_cached_analysis, analyze_video
                for c in candidates:
                    if c.get("media_type") == "video":
                        analysis = get_cached_analysis(c["uuid"])
                        if analysis is None and c.get("path"):
                            # Try to analyze on-the-fly (expensive but worth it)
                            local_path = _resolve_local_path(c["path"], c["uuid"])
                            if local_path:
                                analysis = analyze_video(local_path, c["uuid"])
                        if analysis:
                            # Merge analysis fields into the candidate dict
                            ad = analysis.to_dict()
                            c["energy_score"] = ad.get("energy_score", 0.5)
                            c["energy_level"] = ad.get("energy_level", "medium")
                            c["emotional_tone"] = ad.get("emotional_tone", "neutral")
                            c["shot_type"] = ad.get("shot_type", "medium")
                            c["camera_movement"] = ad.get("camera_movement", "static")
                            c["key_actions"] = ad.get("key_actions", [])
                            c["mood"] = ad.get("mood", "")
                            c["pacing"] = ad.get("pacing", "moderate")
                            c["audio_description"] = ad.get("audio_description", "")
                            c["highlight_moments"] = ad.get("highlight_moments", [])
            except Exception as exc:
                logger.warning("TL enrichment failed, continuing without: %s", exc)

        # Step 3: Analyze music track (if project has one)
        music_data = None
        if project.music_path and Path(project.music_path).exists():
            _update_job(job_id, progress=40, message="Analyzing music track...")
            try:
                from curate.music_analysis import analyze_music, get_cut_points
                from dataclasses import asdict as music_asdict
                analysis = analyze_music(project.music_path)
                cut_points = get_cut_points(analysis)
                music_data = {
                    "bpm": analysis.bpm,
                    "sections": [music_asdict(s) for s in analysis.sections],
                    "strong_beats": analysis.strong_beats,
                    "cut_points": cut_points,
                    "buildups": analysis.buildups,
                    "drops": analysis.drops,
                }
            except Exception as exc:
                logger.warning("Music analysis failed: %s", exc)

        _update_job(job_id, progress=50, message="AI director is designing the story...")

        # Step 4: Scale target duration to available content
        total_source = sum(c.get("duration") or 3.0 for c in candidates)
        target_dur = max(15.0, min(120.0, total_source * 0.4))

        edl = create_edit_decision_list(
            candidates=candidates,
            prompt=project.prompt,
            target_duration=target_dur,
            music_analysis=music_data,
        )

        if not edl.shots:
            _update_job(job_id, status="failed", message="AI director produced no shots. Try a different prompt or add more media.")
            return

        _update_job(job_id, progress=80, message=f"Arranged {len(edl.shots)} shots. Building timeline...")

        # Convert EDL to project timeline
        new_project = edl_to_project(
            edl_data=dc_asdict(edl),
            prompt=project.prompt,
            theme=project.theme,
            music_path=project.music_path,
            music_volume=project.music_volume,
        )
        # Auto-select music if none set but the director suggested a mood
        if not new_project.music_path and new_project.music_mood:
            try:
                from curate.music_library import suggest_music, download_track, _is_available
                if _is_available():
                    _update_job(job_id, progress=85, message="Selecting music track...")
                    suggestions = suggest_music(
                        new_project.music_mood,
                        target_duration=new_project.timeline.duration,
                    )
                    if suggestions:
                        track = suggestions[0]
                        music_dir = str(config.PROJECT_ROOT / "downloads" / "music")
                        music_file = download_track(track, music_dir)
                        new_project.music_path = music_file
                        logger.info(
                            "Auto-selected music: '%s' by %s (mood: %s)",
                            track.title, track.artist, new_project.music_mood,
                        )
                        # Update the audio track with the new music
                        for t in new_project.timeline.tracks:
                            if t.type == "audio":
                                from projects import Clip as ClipModel
                                music_clip = ClipModel(
                                    media_path=music_file,
                                    media_type="audio",
                                    position=0.0,
                                    duration=new_project.timeline.duration + 2.0,
                                    volume=new_project.music_volume,
                                )
                                t.clips = [music_clip]
                                break
                    else:
                        logger.info("No music tracks found for mood: %s", new_project.music_mood)
                else:
                    logger.debug("Jamendo API not configured, skipping auto music selection")
            except Exception as exc:
                logger.warning("Auto music selection failed (non-fatal): %s", exc)

        # Preserve original project metadata
        new_project.id = project.id
        new_project.created_at = project.created_at
        new_project.render_history = project.render_history
        new_project.resolution = project.resolution
        new_project.fps = project.fps

        save_project(new_project)

        _update_job(
            job_id,
            status="completed",
            progress=100,
            message=f"Done! {len(edl.shots)} shots arranged.",
            project=_project_to_dict(new_project),
        )

    except Exception as exc:
        logger.exception("AI arrange failed for project %s", project_id)
        _update_job(job_id, status="failed", progress=0, message=str(exc))


@app.post("/api/projects/{project_id}/render")
def api_project_render(project_id: str, background_tasks: BackgroundTasks):
    """Render a project's timeline to video."""
    try:
        project = load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")

    video_track = None
    for track in project.timeline.tracks:
        if track.type == "video" and track.clips:
            video_track = track
            break

    if not video_track or not video_track.clips:
        raise HTTPException(status_code=400, detail="No video clips in timeline")

    job_id = uuid_mod.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {
            "id": job_id,
            "type": "project_render",
            "status": "queued",
            "progress": 0,
            "message": "Queued for rendering...",
            "created_at": time.time(),
            "updated_at": time.time(),
            "project_id": project_id,
        }

    thread = threading.Thread(
        target=_run_project_render,
        args=(job_id, project_id),
        daemon=True,
    )
    thread.start()

    return {"job_id": job_id}


def _run_project_render(job_id: str, project_id: str):
    """Background thread: render a project's timeline using the assembly pipeline."""
    try:
        _update_job(job_id, status="running", progress=5, message="Loading project...")

        project = load_project(project_id)
        video_track = None
        for track in project.timeline.tracks:
            if track.type == "video" and track.clips:
                video_track = track
                break

        if not video_track:
            _update_job(job_id, status="failed", message="No video clips found")
            return

        # Convert project timeline clips back to EDL format for the assembly pipeline
        from curate.director import Shot, EditDecisionList

        shots = []
        for clip in video_track.clips:
            # Map project transition names back to xfade names
            trans_type = clip.transition.type if clip.transition else "fade"
            trans_rmap = {"none": "cut", "crossfade": "fade", "fade_black": "fadeblack",
                          "fade_white": "fadewhite", "slide_left": "slideleft",
                          "slide_right": "slideright", "smooth_left": "smoothleft",
                          "smooth_right": "smoothright", "wipe_left": "wipeleft",
                          "wipe_right": "wiperight", "dissolve": "dissolve",
                          "circleopen": "circleopen", "circleclose": "circleclose",
                          "radial": "radial", "pixelize": "pixelize"}
            trans_type = trans_rmap.get(trans_type, trans_type)
            trans_dur = clip.transition.duration if clip.transition else 0.5

            # Detect ken_burns and speed from clip effects
            has_ken_burns = any(e.type == "ken_burns" for e in clip.effects)
            speed = 1.0
            for e in clip.effects:
                if e.type == "speed":
                    speed = e.params.get("rate", 1.0)

            shots.append(Shot(
                uuid=clip.media_uuid,
                path=clip.media_path,
                media_type=clip.media_type,
                start_time=clip.in_point,
                end_time=clip.out_point if clip.out_point > clip.in_point else clip.in_point + clip.duration,
                role=clip.role,
                reason=clip.reason,
                transition=trans_type,
                transition_duration=trans_dur,
                ken_burns=has_ken_burns,
                speed=speed,
            ))

        edl = EditDecisionList(
            shots=shots,
            title=project.name,
            narrative_summary=project.narrative_summary,
            estimated_duration=project.timeline.duration,
            music_mood=project.music_mood,
        )

        _update_job(job_id, progress=10, message="Starting video assembly...")

        from assemble import get_build_video
        build_video = get_build_video()

        # Collect text elements from text tracks
        text_elements = []
        for track in project.timeline.tracks:
            if track.type == "text" and not track.muted:
                for te in track.text_elements:
                    text_elements.append({
                        "text": te.text,
                        "position": te.position,
                        "duration": te.duration,
                        "x": te.x,
                        "y": te.y,
                        "font_size": te.font_size,
                        "color": te.color,
                        "bg_color": te.bg_color,
                        "animation": te.animation,
                        "style": te.style,
                    })

        def progress_cb(pct: int, msg: str):
            _update_job(job_id, progress=pct, message=msg)

        output = build_video(
            edl=edl,
            theme_name=project.theme,
            music_path=project.music_path or None,
            music_volume=project.music_volume,
            progress_callback=progress_cb,
            text_elements=text_elements or None,
        )

        # Record render in project history
        from projects import RenderRecord
        record = RenderRecord(
            output_path=f"/output/{Path(output).name}",
            theme=project.theme,
            resolution=f"{project.resolution[0]}x{project.resolution[1]}",
            duration=project.timeline.duration,
        )
        project.render_history.append(record)
        save_project(project)

        _update_job(
            job_id,
            status="completed",
            progress=100,
            message="Video rendered!",
            output_path=f"/output/{Path(output).name}",
            title=project.name,
        )

    except Exception as exc:
        logger.exception("Project render failed for %s", project_id)
        _update_job(job_id, status="failed", message=str(exc))


# ---------------------------------------------------------------------------
# Project music upload / delete
# ---------------------------------------------------------------------------

@app.post("/api/projects/{project_id}/music")
async def api_upload_music(project_id: str, file: UploadFile = File(...)):
    """Upload a music track for a project."""
    try:
        project = load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_AUDIO_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format: {ext}. Allowed: {', '.join(sorted(ALLOWED_AUDIO_EXT))}",
        )

    # Save music file
    music_dir = config.PROJECT_ROOT / "uploads" / "music"
    music_dir.mkdir(parents=True, exist_ok=True)

    music_filename = f"{project_id}{ext}"
    music_path = music_dir / music_filename

    content = await file.read()
    with open(music_path, "wb") as f:
        f.write(content)

    # Update project
    project.music_path = str(music_path)
    save_project(project)

    # Optionally analyze the music immediately
    result: dict = {"music_path": str(music_path), "filename": file.filename}
    try:
        from curate.music_analysis import analyze_music
        analysis = analyze_music(str(music_path))
        result["bpm"] = analysis.bpm
        result["duration"] = analysis.duration
        result["sections"] = len(analysis.sections)
    except Exception:
        pass

    return result


@app.delete("/api/projects/{project_id}/music")
def api_delete_music(project_id: str):
    """Remove the music track from a project."""
    try:
        project = load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")

    if not project.music_path:
        raise HTTPException(status_code=404, detail="Project has no music track")

    # Delete the file if it exists
    music_file = Path(project.music_path)
    if music_file.exists():
        music_file.unlink(missing_ok=True)

    # Clear from project
    old_path = project.music_path
    project.music_path = ""
    save_project(project)

    return {"deleted": True, "music_path": old_path}


@app.get("/api/projects/{project_id}/music/file")
def api_get_music_file(project_id: str):
    """Serve the project's music file for browser playback."""
    try:
        project = load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")

    if not project.music_path:
        raise HTTPException(status_code=404, detail="Project has no music track")

    music_file = Path(project.music_path)
    if not music_file.exists():
        raise HTTPException(status_code=404, detail="Music file not found on disk")

    ext = music_file.suffix.lower()
    content_types = {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".aac": "audio/aac",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
    }
    return FileResponse(str(music_file), media_type=content_types.get(ext, "audio/mpeg"))


# ---------------------------------------------------------------------------
# Royalty-free music library (Jamendo)
# ---------------------------------------------------------------------------

@app.get("/api/music/search")
def api_search_music(
    query: str = Query("", description="Free-text search query"),
    mood: str = Query("", description="Mood filter (happy, sad, epic, chill, dramatic, romantic, etc.)"),
    genre: str = Query("", description="Genre filter (pop, electronic, classical, rock, etc.)"),
    min_duration: int = Query(30, description="Minimum duration in seconds"),
    max_duration: int = Query(300, description="Maximum duration in seconds"),
    limit: int = Query(20, ge=1, le=50, description="Max results"),
):
    """Search the royalty-free music library (Jamendo)."""
    from curate.music_library import search_music, _track_to_dict, _is_available
    if not _is_available():
        raise HTTPException(
            status_code=503,
            detail="Music library not configured. Set the JAMENDO_CLIENT_ID environment variable.",
        )
    try:
        tracks = search_music(
            query=query,
            mood=mood,
            genre=genre,
            min_duration=min_duration,
            max_duration=max_duration,
            limit=limit,
        )
        return {"tracks": [_track_to_dict(t) for t in tracks], "count": len(tracks)}
    except Exception as exc:
        logger.error("Music search failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Music search failed: {exc}")


@app.get("/api/music/status")
def api_music_library_status():
    """Check if the music library API is configured and available."""
    from curate.music_library import _is_available
    return {"available": _is_available()}


class SelectLibraryMusicRequest(BaseModel):
    track_id: str


@app.post("/api/projects/{project_id}/music/library")
def api_select_library_music(project_id: str, body: SelectLibraryMusicRequest):
    """Select a track from the Jamendo library, download it, and set it as project music."""
    from curate.music_library import get_track_by_id, download_track, _is_available
    if not _is_available():
        raise HTTPException(
            status_code=503,
            detail="Music library not configured. Set the JAMENDO_CLIENT_ID environment variable.",
        )

    # Load project
    try:
        project = load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")

    # Find the track
    track = get_track_by_id(body.track_id)
    if not track:
        raise HTTPException(status_code=404, detail=f"Track {body.track_id} not found in library")

    # Download to uploads/music/
    music_dir = str(config.PROJECT_ROOT / "uploads" / "music")
    try:
        local_path = download_track(track, music_dir)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"Download failed: {exc}")

    # Set as project music
    project.music_path = local_path
    save_project(project)

    # Analyze with librosa
    result: dict = {
        "music_path": local_path,
        "filename": f"{track.title} - {track.artist}.mp3",
        "track": {
            "id": track.id,
            "title": track.title,
            "artist": track.artist,
            "license": track.license,
        },
    }
    try:
        from curate.music_analysis import analyze_music
        analysis = analyze_music(local_path)
        result["bpm"] = analysis.bpm
        result["duration"] = analysis.duration
        result["sections"] = len(analysis.sections)
    except Exception:
        result["duration"] = track.duration
        result["bpm"] = track.bpm

    return result


@app.get("/api/projects/{project_id}/music/suggest")
def api_suggest_music(project_id: str):
    """Suggest music tracks based on the project's music_mood from the AI director."""
    from curate.music_library import suggest_music, _track_to_dict, _is_available
    if not _is_available():
        raise HTTPException(
            status_code=503,
            detail="Music library not configured. Set the JAMENDO_CLIENT_ID environment variable.",
        )

    # Load project
    try:
        project = load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")

    if not project.music_mood:
        raise HTTPException(status_code=400, detail="Project has no music_mood set. Run the AI director first.")

    # Calculate target duration from timeline
    target_duration = project.timeline.duration if project.timeline.duration > 0 else 60.0

    try:
        tracks = suggest_music(
            music_mood=project.music_mood,
            target_duration=target_duration,
            limit=10,
        )
        return {
            "tracks": [_track_to_dict(t) for t in tracks],
            "count": len(tracks),
            "music_mood": project.music_mood,
        }
    except Exception as exc:
        logger.error("Music suggest failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Music suggestion failed: {exc}")


# ---------------------------------------------------------------------------
# Twelve Labs media analysis
# ---------------------------------------------------------------------------

@app.post("/api/media/{uuid}/analyze")
def api_analyze_media(uuid: str, background_tasks: BackgroundTasks):
    """Trigger Twelve Labs deep analysis for a media item."""
    if not config.USE_TWELVELABS:
        raise HTTPException(status_code=400, detail="Twelve Labs is not configured (TWELVELABS_API_KEY not set)")

    items = get_media_by_uuids([uuid])
    if not items:
        raise HTTPException(status_code=404, detail="Media not found")

    item = items[0]
    if item.get("media_type") != "video":
        raise HTTPException(status_code=400, detail="Analysis is only available for video media")

    # Check for cached analysis first
    from index.twelvelabs_analyze import get_cached_analysis
    cached = get_cached_analysis(uuid)
    if cached is not None:
        return {"status": "cached", "analysis": cached.to_dict()}

    # Resolve local path for analysis
    local_path = _resolve_local_path(item.get("path", ""), uuid)
    if not local_path:
        raise HTTPException(status_code=400, detail="Source video file not found locally")

    # Run analysis in background
    def _run_analysis(video_path: str, video_uuid: str):
        try:
            from index.twelvelabs_analyze import analyze_video
            analysis = analyze_video(video_path, video_uuid)
            if analysis:
                logger.info("Background TL analysis complete for %s: %s", video_uuid[:8], analysis.summary[:60])
                # Update quality score
                from index.store import _get_client as get_supabase
                client = get_supabase()
                client.table("media").update({
                    "quality_score": _energy_to_quality(analysis),
                }).eq("uuid", video_uuid).execute()
        except Exception as exc:
            logger.error("Background TL analysis failed for %s: %s", video_uuid[:8], exc)

    background_tasks.add_task(_run_analysis, local_path, uuid)

    return {"status": "processing", "message": f"Analysis started for {uuid[:8]}"}

