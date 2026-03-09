"""Project persistence layer.

A Project wraps a multi-track timeline that can be saved, edited, and
re-rendered.  Projects are stored as JSON files under ``data/projects/``.
"""

from __future__ import annotations

import json
import logging
import time
import uuid as uuid_mod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import config

logger = logging.getLogger(__name__)

PROJECTS_DIR = config.PROJECT_ROOT / "data" / "projects"
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ClipEffect:
    """A visual or audio effect applied to a clip."""
    type: str  # "ken_burns", "color_filter", "speed", "crop"
    params: dict = field(default_factory=dict)


@dataclass
class Transition:
    """Transition between this clip and the next."""
    type: str = "crossfade"  # "crossfade", "fade_black", "slide_left", "wipe", "none"
    duration: float = 0.5


@dataclass
class Clip:
    """A clip on a video or audio track."""
    id: str = field(default_factory=lambda: uuid_mod.uuid4().hex[:12])
    media_uuid: str = ""       # references a media item in the library
    media_path: str = ""       # resolved file path
    media_type: str = "photo"  # "photo" or "video"
    in_point: float = 0.0      # source start time (for videos)
    out_point: float = 0.0     # source end time (for videos) or duration (for photos)
    position: float = 0.0      # position on the timeline (seconds from start)
    duration: float = 3.0      # display duration on timeline
    volume: float = 1.0        # audio volume (0-1)
    effects: list[ClipEffect] = field(default_factory=list)
    transition: Transition = field(default_factory=Transition)
    role: str = "highlight"    # from the AI director: opener, highlight, b-roll, transition, closer
    reason: str = ""           # AI reasoning for this shot


@dataclass
class TextElement:
    """A text overlay on the text track."""
    id: str = field(default_factory=lambda: uuid_mod.uuid4().hex[:12])
    text: str = ""
    position: float = 0.0       # position on timeline (seconds)
    duration: float = 3.0
    x: float = 0.5              # relative position (0-1) on screen
    y: float = 0.5
    font_size: int = 48
    font_family: str = "Helvetica"
    color: str = "#FFFFFF"
    bg_color: str = ""          # empty = transparent
    animation: str = "fade"     # "fade", "slide_up", "typewriter", "none"
    style: str = "title"        # "title", "subtitle", "caption", "lower_third"


@dataclass
class Track:
    """A single track in the timeline."""
    id: str = field(default_factory=lambda: uuid_mod.uuid4().hex[:8])
    name: str = "Video 1"
    type: str = "video"         # "video", "audio", "text"
    clips: list[Clip] = field(default_factory=list)
    text_elements: list[TextElement] = field(default_factory=list)
    muted: bool = False
    locked: bool = False
    volume: float = 1.0         # track-level volume (for audio tracks)


@dataclass
class Timeline:
    """Multi-track timeline."""
    tracks: list[Track] = field(default_factory=list)
    duration: float = 0.0       # computed total duration

    def compute_duration(self) -> float:
        """Recompute total duration from tracks."""
        max_end = 0.0
        for track in self.tracks:
            for clip in track.clips:
                end = clip.position + clip.duration
                if end > max_end:
                    max_end = end
            for te in track.text_elements:
                end = te.position + te.duration
                if end > max_end:
                    max_end = end
        self.duration = max_end
        return max_end


@dataclass
class RenderRecord:
    """Record of a completed render."""
    id: str = field(default_factory=lambda: uuid_mod.uuid4().hex[:12])
    output_path: str = ""
    rendered_at: float = field(default_factory=time.time)
    theme: str = "minimal"
    resolution: str = "1920x1080"
    duration: float = 0.0


@dataclass
class Project:
    """A film project with multi-track timeline."""
    id: str = field(default_factory=lambda: uuid_mod.uuid4().hex)
    name: str = "Untitled Project"
    prompt: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    theme: str = "minimal"
    resolution: tuple[int, int] = (1920, 1080)
    fps: int = 30
    music_path: str = ""
    music_volume: float = 0.3
    timeline: Timeline = field(default_factory=Timeline)
    render_history: list[RenderRecord] = field(default_factory=list)
    narrative_summary: str = ""
    music_mood: str = ""


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def _project_to_dict(project: Project) -> dict:
    """Convert a Project to a JSON-serializable dict."""
    d = asdict(project)
    # Tuples become lists in asdict, keep resolution as list
    return d


def _dict_to_project(d: dict) -> Project:
    """Reconstruct a Project from a dict."""
    timeline_data = d.pop("timeline", {})
    render_data = d.pop("render_history", [])

    # Reconstruct resolution tuple
    res = d.get("resolution", [1920, 1080])
    if isinstance(res, list):
        d["resolution"] = tuple(res)

    tracks = []
    for td in timeline_data.get("tracks", []):
        clips = [Clip(**{k: v for k, v in c.items() if k != "effects" and k != "transition"},
                       effects=[ClipEffect(**e) for e in c.get("effects", [])],
                       transition=Transition(**c["transition"]) if "transition" in c else Transition())
                 for c in td.get("clips", [])]
        text_elements = [TextElement(**te) for te in td.get("text_elements", [])]
        tracks.append(Track(
            id=td.get("id", ""),
            name=td.get("name", ""),
            type=td.get("type", "video"),
            clips=clips,
            text_elements=text_elements,
            muted=td.get("muted", False),
            locked=td.get("locked", False),
            volume=td.get("volume", 1.0),
        ))

    timeline = Timeline(tracks=tracks, duration=timeline_data.get("duration", 0.0))
    renders = [RenderRecord(**r) for r in render_data]

    return Project(timeline=timeline, render_history=renders, **d)


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------

def save_project(project: Project) -> str:
    """Save a project to disk. Returns the project ID."""
    project.updated_at = time.time()
    project.timeline.compute_duration()
    path = PROJECTS_DIR / f"{project.id}.json"
    with open(path, "w") as f:
        json.dump(_project_to_dict(project), f, indent=2)
    logger.info("Saved project %s (%s)", project.id, project.name)
    return project.id


def load_project(project_id: str) -> Project:
    """Load a project from disk."""
    path = PROJECTS_DIR / f"{project_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Project {project_id} not found")
    with open(path) as f:
        data = json.load(f)
    return _dict_to_project(data)


def list_projects() -> list[dict]:
    """List all projects (summary info only)."""
    projects = []
    for path in sorted(PROJECTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with open(path) as f:
                data = json.load(f)
            projects.append({
                "id": data["id"],
                "name": data["name"],
                "prompt": data.get("prompt", ""),
                "theme": data.get("theme", "minimal"),
                "created_at": data.get("created_at", 0),
                "updated_at": data.get("updated_at", 0),
                "duration": data.get("timeline", {}).get("duration", 0),
                "track_count": len(data.get("timeline", {}).get("tracks", [])),
                "render_count": len(data.get("render_history", [])),
            })
        except Exception as e:
            logger.warning("Failed to read project %s: %s", path, e)
    return projects


def delete_project(project_id: str) -> bool:
    """Delete a project file."""
    path = PROJECTS_DIR / f"{project_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False


# ---------------------------------------------------------------------------
# EDL → Project conversion
# ---------------------------------------------------------------------------

def edl_to_project(
    edl_data: dict,
    prompt: str = "",
    theme: str = "minimal",
    music_path: str = "",
    music_volume: float = 0.3,
) -> Project:
    """Convert an EDL response (from the AI director) into a Project with timeline.

    This bridges the existing prompt→EDL workflow with the new project model.
    The EDL shots become clips on a main video track, positioned sequentially.
    """
    project = Project(
        name=edl_data.get("title", "Untitled"),
        prompt=prompt,
        theme=theme,
        music_path=music_path,
        music_volume=music_volume,
        narrative_summary=edl_data.get("narrative_summary", ""),
        music_mood=edl_data.get("music_mood", ""),
    )

    # Create default tracks
    video_track = Track(name="Main Video", type="video")
    text_track = Track(name="Titles", type="text")
    audio_track = Track(name="Music", type="audio")

    # Convert shots to clips with transitions and effects
    current_position = 3.0  # leave room for title card
    for shot_data in edl_data.get("shots", []):
        duration = shot_data.get("end_time", 0) - shot_data.get("start_time", 0)
        if duration <= 0:
            duration = 3.0

        # Map director's transition choice to Transition object
        trans_type = shot_data.get("transition", "cut")
        # Normalize xfade names to our model's names
        trans_map = {"cut": "none", "fade": "crossfade", "fadeblack": "fade_black",
                     "fadewhite": "fade_white", "slideleft": "slide_left",
                     "slideright": "slide_right", "smoothleft": "smooth_left",
                     "smoothright": "smooth_right", "wipeleft": "wipe_left",
                     "wiperight": "wipe_right", "dissolve": "crossfade",
                     "circleopen": "crossfade", "circleclose": "crossfade",
                     "radial": "crossfade", "pixelize": "crossfade"}
        trans_type = trans_map.get(trans_type, trans_type)
        trans_dur = shot_data.get("transition_duration", 0.0)

        # Build effects list from director hints
        effects = []
        if shot_data.get("ken_burns", shot_data.get("media_type") == "photo"):
            effects.append(ClipEffect(type="ken_burns", params={}))
        speed = shot_data.get("speed", 1.0)
        if speed != 1.0:
            effects.append(ClipEffect(type="speed", params={"rate": speed}))

        clip = Clip(
            media_uuid=shot_data.get("uuid", ""),
            media_path=shot_data.get("path", ""),
            media_type=shot_data.get("media_type", "photo"),
            in_point=shot_data.get("start_time", 0),
            out_point=shot_data.get("end_time", 0),
            position=current_position,
            duration=duration,
            role=shot_data.get("role", "highlight"),
            reason=shot_data.get("reason", ""),
            transition=Transition(type=trans_type, duration=trans_dur),
            effects=effects,
        )
        video_track.clips.append(clip)
        current_position += duration

    # Add title text element
    title_text = TextElement(
        text=edl_data.get("title", ""),
        position=0.0,
        duration=3.0,
        y=0.5,
        font_size=56,
        animation="fade",
        style="title",
    )
    text_track.text_elements.append(title_text)

    # Add music clip if provided
    if music_path:
        music_clip = Clip(
            media_path=music_path,
            media_type="audio",
            position=0.0,
            duration=current_position + 2.0,  # extend past video
            volume=music_volume,
        )
        audio_track.clips.append(music_clip)

    project.timeline.tracks = [video_track, text_track, audio_track]
    project.timeline.compute_duration()

    return project
