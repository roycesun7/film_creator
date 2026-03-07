"""Lightweight mock API for frontend testing (no Supabase dependency)."""
import json
import os
import sys
import time
import uuid
from pathlib import Path

# Minimal FastAPI + uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

app = FastAPI(title="Video Composer (Test)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = Path(__file__).parent / "data" / "projects"
DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
UPLOADS_DIR = Path(__file__).parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")

# ----------- Project CRUD -----------

def _load(pid: str) -> dict:
    fp = DATA_DIR / f"{pid}.json"
    if not fp.exists():
        raise HTTPException(404, "Project not found")
    return json.loads(fp.read_text())

def _save(data: dict) -> str:
    pid = data.get("id") or uuid.uuid4().hex
    data["id"] = pid
    data.setdefault("updated_at", time.time())
    (DATA_DIR / f"{pid}.json").write_text(json.dumps(data, indent=2))
    return pid

def _summary(data: dict) -> dict:
    tl = data.get("timeline", {})
    tracks = tl.get("tracks", [])
    renders = data.get("render_history", [])
    return {
        "id": data["id"],
        "name": data.get("name", "Untitled"),
        "prompt": data.get("prompt", ""),
        "theme": data.get("theme", "minimal"),
        "created_at": data.get("created_at", 0),
        "updated_at": data.get("updated_at", 0),
        "duration": tl.get("duration", 0),
        "track_count": len(tracks),
        "render_count": len(renders),
    }

@app.get("/api/projects")
def list_projects():
    projects = []
    for fp in DATA_DIR.glob("*.json"):
        try:
            data = json.loads(fp.read_text())
            projects.append(_summary(data))
        except Exception:
            pass
    projects.sort(key=lambda p: p.get("updated_at", 0), reverse=True)
    return {"projects": projects}

class CreateProjectReq(BaseModel):
    name: str = "Untitled Project"
    prompt: str = ""
    theme: str = "minimal"

@app.post("/api/projects")
def create_project(req: CreateProjectReq):
    now = time.time()
    data = {
        "id": uuid.uuid4().hex,
        "name": req.name,
        "prompt": req.prompt,
        "theme": req.theme,
        "created_at": now,
        "updated_at": now,
        "resolution": [1920, 1080],
        "fps": 30,
        "music_path": "",
        "music_volume": 0.3,
        "narrative_summary": "",
        "music_mood": "",
        "timeline": {
            "tracks": [
                {"id": uuid.uuid4().hex[:8], "name": "Video", "type": "video", "clips": [], "text_elements": [], "muted": False, "locked": False, "volume": 1.0},
                {"id": uuid.uuid4().hex[:8], "name": "Audio", "type": "audio", "clips": [], "text_elements": [], "muted": False, "locked": False, "volume": 1.0},
            ],
            "duration": 0,
        },
        "render_history": [],
    }
    _save(data)
    return {"id": data["id"], "project": data}

@app.get("/api/projects/{pid}")
def get_project(pid: str):
    return _load(pid)

class UpdateProjectReq(BaseModel):
    project: dict

@app.put("/api/projects/{pid}")
def update_project(pid: str, req: UpdateProjectReq):
    _load(pid)  # verify exists
    data = req.project
    data["id"] = pid
    data["updated_at"] = time.time()
    _save(data)
    return data

@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    fp = DATA_DIR / f"{pid}.json"
    if fp.exists():
        fp.unlink()
        return {"deleted": True}
    raise HTTPException(404, "Not found")

# ----------- Mock media/search endpoints -----------

# Generate some fake media items for the media browser
MOCK_MEDIA = [
    {"uuid": f"mock-{i:04d}", "path": f"/uploads/mock_{i}.jpg", "media_type": "photo" if i % 3 != 0 else "video",
     "date": f"2025-07-{(i % 28) + 1:02d}", "lat": None, "lon": None, "albums": ["Summer 2025"],
     "labels": ["outdoor", "nature"], "persons": [], "width": 1920, "height": 1080,
     "duration": (5.0 + i * 0.5) if i % 3 == 0 else None, "description": {}, "quality_score": 7.5 + (i % 5) * 0.3}
    for i in range(24)
]

@app.get("/api/media")
def get_media(limit: int = 24, offset: int = 0, sort: str = "date", media_type: str = None):
    items = MOCK_MEDIA
    if media_type:
        items = [m for m in items if m["media_type"] == media_type]
    return {"items": items[offset:offset+limit], "total": len(items), "limit": limit, "offset": offset}

@app.get("/api/media/{media_uuid}")
def get_media_detail(media_uuid: str):
    for m in MOCK_MEDIA:
        if m["uuid"] == media_uuid:
            return m
    raise HTTPException(404, "Not found")

@app.get("/api/media/{media_uuid}/thumbnail")
def get_thumbnail(media_uuid: str):
    # Return a placeholder thumbnail
    from fastapi.responses import Response
    # Generate a simple colored SVG as placeholder
    idx = int(media_uuid.split("-")[-1]) if "-" in media_uuid else 0
    colors = ["#6d28d9", "#2563eb", "#059669", "#d97706", "#dc2626", "#7c3aed", "#0891b2", "#65a30d"]
    color = colors[idx % len(colors)]
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400"><rect width="400" height="400" fill="{color}"/><text x="200" y="200" text-anchor="middle" dominant-baseline="middle" fill="white" font-family="sans-serif" font-size="48">#{idx+1}</text></svg>'
    return Response(content=svg, media_type="image/svg+xml")

class SearchReq(BaseModel):
    query: str
    limit: int = 20
    albums: Optional[list[str]] = None
    persons: Optional[list[str]] = None
    min_quality: Optional[float] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    fast: bool = False

@app.post("/api/search")
def search(req: SearchReq):
    # Return mock results based on query
    results = MOCK_MEDIA[:req.limit]
    return {"results": results, "count": len(results), "query": req.query}

@app.get("/api/stats")
def stats():
    return {
        "total": 24, "photos": 16, "videos": 8,
        "with_embeddings": 20, "with_descriptions": 18,
        "date_range": {"earliest": "2025-06-01", "latest": "2025-08-31"},
        "top_albums": [{"name": "Summer 2025", "count": 24}],
        "top_persons": [],
        "avg_quality": 8.2,
    }

@app.get("/api/videos")
def list_videos():
    return {"videos": []}

@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    return {"id": job_id, "type": "render", "status": "completed", "progress": 100, "message": "Done", "created_at": time.time(), "updated_at": time.time()}

@app.post("/api/upload-music")
async def upload_music():
    return {"path": "/uploads/music/test.mp3", "filename": "test.mp3"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
