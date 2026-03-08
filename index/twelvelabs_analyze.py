"""Twelve Labs Pegasus video analysis integration.

Uses the Twelve Labs Analyze API (Pegasus 1.2) to get deep structured video
analysis including scene descriptions, energy levels, shot types, camera
movement, subjects, mood, and more.

Requires videos to be indexed in a Twelve Labs index before analysis.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path

import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Persistence paths (dotfiles in project root)
# ---------------------------------------------------------------------------
_INDEX_FILE = config.PROJECT_ROOT / ".twelvelabs_index_id"
_VIDEO_MAP_FILE = config.PROJECT_ROOT / ".twelvelabs_video_map.json"
_ANALYSES_FILE = config.PROJECT_ROOT / ".twelvelabs_analyses.json"

_INDEX_NAME = "video_composer"

# ---------------------------------------------------------------------------
# Lazy client singleton (same pattern as twelvelabs_embed.py)
# ---------------------------------------------------------------------------
_client = None


def _get_client():
    global _client
    if _client is None:
        if not config.USE_TWELVELABS:
            raise RuntimeError("TWELVELABS_API_KEY is not set")
        from twelvelabs import TwelveLabs
        _client = TwelveLabs(api_key=config.TWELVELABS_API_KEY)
    return _client


# ---------------------------------------------------------------------------
# JSON file helpers
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict:
    """Read a JSON file, returning an empty dict if it doesn't exist."""
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read %s: %s", path, exc)
    return {}


def _write_json(path: Path, data: dict) -> None:
    """Atomically write a JSON file."""
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2, default=str))
        tmp.replace(path)
    except OSError as exc:
        logger.error("Failed to write %s: %s", path, exc)
        if tmp.exists():
            tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 1. Index management
# ---------------------------------------------------------------------------

def _get_or_create_index() -> str:
    """Get or create the Twelve Labs index for video analysis.

    Creates an index with Pegasus 1.2 (generation) and Marengo 2.7 (embedding).
    Stores the index_id in a local dotfile for persistence.

    Returns:
        The Twelve Labs index_id string.
    """
    # Check cached index_id first
    if _INDEX_FILE.exists():
        index_id = _INDEX_FILE.read_text().strip()
        if index_id:
            # Verify it still exists on the server
            try:
                client = _get_client()
                idx = client.indexes.retrieve(index_id)
                if idx and idx.id:
                    logger.debug("Using existing Twelve Labs index: %s", index_id)
                    return index_id
            except Exception:
                logger.warning(
                    "Cached index_id %s no longer valid, will recreate",
                    index_id,
                )

    client = _get_client()

    # Check if an index with our name already exists
    try:
        pager = client.indexes.list(index_name=_INDEX_NAME)
        for idx in pager:
            if idx.index_name == _INDEX_NAME and idx.id:
                logger.info(
                    "Found existing Twelve Labs index '%s': %s",
                    _INDEX_NAME, idx.id,
                )
                _INDEX_FILE.write_text(idx.id)
                return idx.id
    except Exception as exc:
        logger.warning("Failed to list indexes: %s", exc)

    # Create a new index
    logger.info("Creating new Twelve Labs index '%s'...", _INDEX_NAME)
    from twelvelabs.indexes.types.indexes_create_request_models_item import (
        IndexesCreateRequestModelsItem,
    )

    response = client.indexes.create(
        index_name=_INDEX_NAME,
        models=[
            IndexesCreateRequestModelsItem(
                model_name="pegasus1.2",
                model_options=["visual", "conversation"],
            ),
            IndexesCreateRequestModelsItem(
                model_name="marengo3.0",
                model_options=["visual", "conversation"],
            ),
        ],
    )

    index_id = response.id
    if not index_id:
        raise RuntimeError("Twelve Labs index creation returned no id")

    _INDEX_FILE.write_text(index_id)
    logger.info("Created Twelve Labs index '%s': %s", _INDEX_NAME, index_id)
    return index_id


# ---------------------------------------------------------------------------
# 2. Video indexing
# ---------------------------------------------------------------------------

def _load_video_map() -> dict[str, str]:
    """Load the uuid -> video_id mapping."""
    return _read_json(_VIDEO_MAP_FILE)


def _save_video_map(mapping: dict[str, str]) -> None:
    """Save the uuid -> video_id mapping."""
    _write_json(_VIDEO_MAP_FILE, mapping)


def get_video_id(video_uuid: str) -> str | None:
    """Look up the Twelve Labs video_id for a given media UUID.

    Returns:
        The TL video_id string, or None if the video hasn't been indexed.
    """
    return _load_video_map().get(video_uuid)


def index_video(video_path: str, video_uuid: str) -> str | None:
    """Upload and index a video in Twelve Labs.

    If the video has already been indexed (uuid exists in the mapping),
    returns the existing video_id without re-indexing.

    Args:
        video_path: Path to the video file on disk.
        video_uuid: The local media UUID for this video.

    Returns:
        The Twelve Labs video_id, or None on failure.
    """
    if not config.USE_TWELVELABS:
        logger.debug("Twelve Labs not configured, skipping video indexing")
        return None

    # Check if already indexed
    existing = get_video_id(video_uuid)
    if existing:
        logger.debug(
            "Video %s already indexed as %s", video_uuid[:8], existing
        )
        return existing

    try:
        client = _get_client()
        index_id = _get_or_create_index()

        p = Path(video_path)
        if not p.exists():
            logger.error("Video file not found: %s", video_path)
            return None

        logger.info(
            "Uploading %s to Twelve Labs index for indexing...", p.name
        )

        # Create an indexing task
        task_response = client.tasks.create(
            index_id=index_id,
            video_file=str(p),
        )
        task_id = task_response.id
        if not task_id:
            logger.error("Task creation returned no id for %s", p.name)
            return None

        logger.info(
            "Indexing task created: id=%s, waiting for completion...", task_id
        )

        # Wait for indexing to complete (can take a while for long videos)
        def _progress_callback(task):
            if task.status:
                logger.debug("Indexing task %s status: %s", task_id, task.status)

        result = client.tasks.wait_for_done(
            task_id,
            sleep_interval=5.0,
            callback=_progress_callback,
        )

        video_id = result.video_id
        if not video_id:
            logger.error(
                "Indexing task %s completed but returned no video_id "
                "(status: %s)",
                task_id,
                result.status,
            )
            return None

        # Store the mapping
        mapping = _load_video_map()
        mapping[video_uuid] = video_id
        _save_video_map(mapping)

        logger.info(
            "Video %s indexed successfully: video_id=%s",
            p.name,
            video_id,
        )
        return video_id

    except Exception as exc:
        logger.error(
            "Failed to index video %s: %s", Path(video_path).name, exc,
            exc_info=True,
        )
        return None


# ---------------------------------------------------------------------------
# 3. Rich video analysis
# ---------------------------------------------------------------------------

@dataclass
class VideoAnalysis:
    """Rich structured analysis of a video clip from Twelve Labs."""

    summary: str = ""                     # 1-2 sentence description
    energy_level: str = "medium"          # very_low, low, medium, high, very_high
    energy_score: float = 0.5             # 0.0 - 1.0
    emotional_tone: str = "neutral"       # joyful, serene, exciting, intimate, dramatic, etc.
    shot_type: str = "medium"             # wide, medium, close_up, extreme_close_up, aerial
    camera_movement: str = "static"       # static, pan, tilt, tracking, handheld, zoom
    key_actions: list[str] = field(default_factory=list)
    subjects: list[str] = field(default_factory=list)
    setting: str = ""                     # outdoor golf course at sunset
    mood: str = ""                        # upbeat and fun
    visual_quality: str = "good"          # excellent, good, fair, poor
    pacing: str = "moderate"              # fast, moderate, slow
    highlight_moments: list[dict] = field(default_factory=list)  # [{time, description}]
    colors: list[str] = field(default_factory=list)
    audio_description: str = ""           # birds chirping, laughter, wind

    def to_dict(self) -> dict:
        """Serialize to a plain dict for JSON storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> VideoAnalysis:
        """Deserialize from a dict, ignoring unknown keys."""
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)


# JSON schema for Twelve Labs structured output
_ANALYSIS_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "1-2 sentence description of the video clip",
        },
        "energy_level": {
            "type": "string",
            "enum": ["very_low", "low", "medium", "high", "very_high"],
            "description": "Overall energy level of the clip",
        },
        "energy_score": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "Numeric energy score from 0.0 (calm) to 1.0 (intense)",
        },
        "emotional_tone": {
            "type": "string",
            "description": "Primary emotional tone (e.g. joyful, serene, exciting, intimate, dramatic, melancholic, tense, playful, nostalgic, neutral)",
        },
        "shot_type": {
            "type": "string",
            "enum": ["wide", "medium", "close_up", "extreme_close_up", "aerial"],
            "description": "Primary shot type / framing",
        },
        "camera_movement": {
            "type": "string",
            "enum": ["static", "pan", "tilt", "tracking", "handheld", "zoom"],
            "description": "Dominant camera movement style",
        },
        "key_actions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of key actions happening in the clip (e.g. 'person swinging golf club')",
        },
        "subjects": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Main subjects visible (e.g. 'person', 'dog', 'mountain')",
        },
        "setting": {
            "type": "string",
            "description": "Description of the location/setting (e.g. 'outdoor golf course at sunset')",
        },
        "mood": {
            "type": "string",
            "description": "Overall mood or vibe (e.g. 'upbeat and fun', 'calm and reflective')",
        },
        "visual_quality": {
            "type": "string",
            "enum": ["excellent", "good", "fair", "poor"],
            "description": "Subjective visual quality assessment",
        },
        "pacing": {
            "type": "string",
            "enum": ["fast", "moderate", "slow"],
            "description": "Perceived pacing / tempo of the clip",
        },
        "highlight_moments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "time": {
                        "type": "number",
                        "description": "Timestamp in seconds",
                    },
                    "description": {
                        "type": "string",
                        "description": "What happens at this moment",
                    },
                },
                "required": ["time", "description"],
            },
            "description": "Notable moments worth highlighting, with timestamps",
        },
        "colors": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Dominant colors or color descriptions (e.g. 'warm sunset orange', 'deep blue sky')",
        },
        "audio_description": {
            "type": "string",
            "description": "Description of audio content (e.g. 'birds chirping, laughter, wind')",
        },
    },
    "required": [
        "summary", "energy_level", "energy_score", "emotional_tone",
        "shot_type", "camera_movement", "key_actions", "subjects",
        "setting", "mood", "visual_quality", "pacing",
        "highlight_moments", "colors", "audio_description",
    ],
}

_ANALYSIS_PROMPT = """\
Analyze this video clip for use in professional video editing. Provide a comprehensive assessment covering:

1. Overall scene description and key actions
2. Energy level (very_low/low/medium/high/very_high) and a numeric energy score (0.0-1.0)
3. Emotional tone (e.g. joyful, serene, exciting, intimate, dramatic, melancholic, tense, playful)
4. Shot composition type (wide/medium/close_up/extreme_close_up/aerial) and camera movement (static/pan/tilt/tracking/handheld/zoom)
5. Subjects visible and the setting/location
6. Overall mood or vibe
7. Visual quality assessment (excellent/good/fair/poor)
8. Pacing (fast/moderate/slow)
9. Notable highlight moments with approximate timestamps in seconds
10. Dominant colors
11. Audio content description (music, speech, ambient sounds, silence)

Be specific and precise. For highlight_moments, provide actual timestamps from the video.\
"""


def _load_analyses() -> dict[str, dict]:
    """Load cached analyses from disk."""
    return _read_json(_ANALYSES_FILE)


def _save_analyses(data: dict[str, dict]) -> None:
    """Save analyses to disk."""
    _write_json(_ANALYSES_FILE, data)


def get_cached_analysis(video_uuid: str) -> VideoAnalysis | None:
    """Look up cached analysis for a video, if available.

    Args:
        video_uuid: The local media UUID.

    Returns:
        A VideoAnalysis instance, or None if no cached analysis exists.
    """
    analyses = _load_analyses()
    if video_uuid in analyses:
        try:
            return VideoAnalysis.from_dict(analyses[video_uuid])
        except Exception as exc:
            logger.warning(
                "Failed to deserialize cached analysis for %s: %s",
                video_uuid[:8], exc,
            )
    return None


def analyze_video(video_path: str, video_uuid: str) -> VideoAnalysis | None:
    """Get deep structured analysis of a video using Twelve Labs Pegasus.

    Indexes the video if not already indexed, then calls the Analyze API
    with a structured JSON schema to get rich editorial metadata.

    Results are cached to disk so repeated calls are free.

    Args:
        video_path: Path to the video file on disk.
        video_uuid: The local media UUID.

    Returns:
        A VideoAnalysis instance, or None on failure.
    """
    if not config.USE_TWELVELABS:
        logger.debug("Twelve Labs not configured, skipping analysis")
        return None

    # Return cached result if available
    cached = get_cached_analysis(video_uuid)
    if cached is not None:
        logger.debug("Returning cached analysis for %s", video_uuid[:8])
        return cached

    try:
        # Ensure the video is indexed
        video_id = index_video(video_path, video_uuid)
        if not video_id:
            logger.error(
                "Cannot analyze %s: video indexing failed", video_uuid[:8]
            )
            return None

        client = _get_client()

        logger.info(
            "Analyzing video %s (video_id=%s) with Pegasus...",
            Path(video_path).name, video_id,
        )

        from twelvelabs.types.response_format import ResponseFormat

        response = client.analyze(
            video_id=video_id,
            prompt=_ANALYSIS_PROMPT,
            temperature=0.1,
            response_format=ResponseFormat(
                type="json_schema",
                json_schema=_ANALYSIS_JSON_SCHEMA,
            ),
        )

        if not response.data:
            logger.error(
                "Analyze API returned no data for %s", video_uuid[:8]
            )
            return None

        # Parse the structured JSON response
        try:
            parsed = json.loads(response.data)
        except json.JSONDecodeError as exc:
            logger.error(
                "Failed to parse analysis JSON for %s: %s\nRaw: %s",
                video_uuid[:8], exc, response.data[:500],
            )
            return None

        analysis = VideoAnalysis.from_dict(parsed)

        # Cache the result
        analyses = _load_analyses()
        analyses[video_uuid] = analysis.to_dict()
        _save_analyses(analyses)

        logger.info(
            "Analysis complete for %s: %s",
            Path(video_path).name, analysis.summary[:80],
        )
        return analysis

    except Exception as exc:
        logger.error(
            "Failed to analyze video %s: %s",
            Path(video_path).name, exc,
            exc_info=True,
        )
        return None


# ---------------------------------------------------------------------------
# 4. Batch analysis
# ---------------------------------------------------------------------------

def analyze_videos_batch(
    items: list[dict],
    force: bool = False,
) -> dict[str, VideoAnalysis]:
    """Analyze multiple videos, returning a uuid -> VideoAnalysis mapping.

    Each item in *items* should have at minimum:
      - 'path': str  -- filesystem path to the video
      - 'uuid': str  -- the media UUID

    Skips videos that already have analysis stored (unless force=True).
    Skips non-video files silently.

    Args:
        items: List of media item dicts with 'path' and 'uuid' keys.
        force: If True, re-analyze even if cached results exist.

    Returns:
        Dict mapping uuid -> VideoAnalysis for all successfully analyzed videos.
    """
    if not config.USE_TWELVELABS:
        logger.debug("Twelve Labs not configured, skipping batch analysis")
        return {}

    results: dict[str, VideoAnalysis] = {}
    total = len(items)

    for i, item in enumerate(items, 1):
        uuid = item.get("uuid", "")
        path = item.get("path", "")

        if not uuid or not path:
            logger.warning("Skipping item with missing uuid or path: %s", item)
            continue

        # Skip non-video files
        ext = Path(path).suffix.lower()
        video_exts = {
            ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm",
            ".mts", ".m2ts", ".flv", ".wmv",
        }
        if ext not in video_exts:
            logger.debug("Skipping non-video file: %s", Path(path).name)
            continue

        # Skip if cached (unless forced)
        if not force:
            cached = get_cached_analysis(uuid)
            if cached is not None:
                logger.debug(
                    "[%d/%d] Using cached analysis for %s",
                    i, total, uuid[:8],
                )
                results[uuid] = cached
                continue

        logger.info(
            "[%d/%d] Analyzing %s...", i, total, Path(path).name
        )
        analysis = analyze_video(path, uuid)
        if analysis is not None:
            results[uuid] = analysis

    logger.info(
        "Batch analysis complete: %d/%d videos analyzed successfully",
        len(results), total,
    )
    return results
