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
logger = logging.getLogger("api")

app = FastAPI(title="Video Composer", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
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
    # Strip embeddings from response (they're large binary blobs)
    for item in items:
        item.pop("embedding", None)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@app.get("/api/media/{media_uuid}")
def get_media_detail(media_uuid: str):
    items = get_media_by_uuids([media_uuid])
    if not items:
        raise HTTPException(status_code=404, detail="Media not found")
    item = items[0]
    item.pop("embedding", None)
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
    if delete_media(media_uuid):
        return {"deleted": True, "uuid": media_uuid}
    raise HTTPException(status_code=404, detail="Media not found")


# ---------------------------------------------------------------------------
# File upload
# ---------------------------------------------------------------------------

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
            # Primary embedding = first segment (or could average all)
            primary = segments[0]["embedding"]
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


def _process_upload_embedding(file_path: str, media_uuid: str, media_type: str, describe: bool = False):
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

        if describe and media_type == "photo":
            try:
                from index.vision_describe import describe_image
                description = describe_image(file_path)
                quality_score = description.get("quality_score")
                items = get_media_by_uuids([media_uuid])
                if items:
                    item = items[0]
                    item["description"] = description
                    item["quality_score"] = quality_score
                    upsert_media(item)
                logger.info("AI description generated for %s", media_uuid[:8])
            except Exception as exc:
                logger.warning("Vision describe failed for %s: %s", media_uuid[:8], exc)

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
async def upload_files(files: list[UploadFile] = File(...), describe: bool = Query(False)):
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

        # Get dimensions immediately so the record is useful right away
        width, height, duration = _get_media_dimensions(file_path, media_type)

        # Store the Supabase storage path, but keep local path for embedding
        record = {
            "uuid": media_uuid,
            "path": storage_url or file_path,
            "media_type": media_type,
            "date": datetime.utcnow().isoformat(),
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
        from assemble.builder import build_video

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
        from assemble.builder import build_video

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
