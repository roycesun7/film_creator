"""Royalty-free music library integration via the Jamendo API.

Searches for and downloads royalty-free music tracks from Jamendo
based on mood, genre, and BPM/speed requirements. All tracks on
Jamendo are released under Creative Commons licenses.

API docs: https://developer.jamendo.com/v3.0/tracks
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

JAMENDO_API_BASE = "https://api.jamendo.com/v3.0"
JAMENDO_CLIENT_ID = os.getenv("JAMENDO_CLIENT_ID", "")

# Simple in-memory cache: key -> (timestamp, results)
_search_cache: dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class MusicTrack:
    """A royalty-free music track from the library."""

    id: str
    title: str
    artist: str
    duration: int  # seconds
    bpm: int | None
    genre: str
    mood: str
    preview_url: str  # streaming URL (96 kbps MP3)
    download_url: str  # full quality download
    license: str  # e.g. "CC BY-NC-SA 3.0"
    tags: list[str] = field(default_factory=list)
    image_url: str = ""


def _track_to_dict(track: MusicTrack) -> dict:
    """Convert a MusicTrack to a JSON-serializable dict."""
    return asdict(track)


# ---------------------------------------------------------------------------
# Mood / genre mapping
# ---------------------------------------------------------------------------

# Maps natural-language mood keywords to Jamendo search tags and speed values
_MOOD_TAG_MAP: dict[str, dict] = {
    "happy": {"tags": ["happy", "upbeat", "fun"], "speed": "high"},
    "upbeat": {"tags": ["upbeat", "energetic", "happy"], "speed": "high"},
    "sad": {"tags": ["sad", "melancholy", "emotional"], "speed": "low"},
    "melancholy": {"tags": ["sad", "melancholy"], "speed": "low"},
    "epic": {"tags": ["epic", "cinematic", "dramatic"], "speed": "high"},
    "cinematic": {"tags": ["cinematic", "epic", "film"], "speed": "medium"},
    "chill": {"tags": ["chill", "relaxing", "ambient"], "speed": "low"},
    "relaxing": {"tags": ["relaxing", "chill", "calm"], "speed": "low"},
    "dramatic": {"tags": ["dramatic", "intense", "epic"], "speed": "medium"},
    "romantic": {"tags": ["romantic", "love", "soft"], "speed": "low"},
    "energetic": {"tags": ["energetic", "upbeat", "powerful"], "speed": "veryhigh"},
    "ambient": {"tags": ["ambient", "atmospheric", "chill"], "speed": "verylow"},
    "dark": {"tags": ["dark", "intense", "mysterious"], "speed": "medium"},
    "inspirational": {"tags": ["inspirational", "uplifting", "motivational"], "speed": "medium"},
    "nostalgic": {"tags": ["nostalgic", "retro", "emotional"], "speed": "medium"},
    "peaceful": {"tags": ["peaceful", "calm", "nature"], "speed": "verylow"},
}

# Maps genre keywords to Jamendo fuzzytags
_GENRE_TAG_MAP: dict[str, list[str]] = {
    "pop": ["pop"],
    "rock": ["rock"],
    "electronic": ["electronic", "electro"],
    "classical": ["classical", "orchestral"],
    "jazz": ["jazz"],
    "acoustic": ["acoustic"],
    "hip-hop": ["hiphop", "rap"],
    "ambient": ["ambient"],
    "folk": ["folk"],
    "indie": ["indie"],
    "country": ["country"],
    "r&b": ["rnb", "soul"],
    "metal": ["metal"],
    "blues": ["blues"],
    "reggae": ["reggae"],
    "latin": ["latin"],
    "world": ["world"],
    "funk": ["funk"],
    "soul": ["soul"],
    "lofi": ["lofi"],
}


def _is_available() -> bool:
    """Check if the music library API is configured and available."""
    return bool(JAMENDO_CLIENT_ID)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search_music(
    query: str = "",
    mood: str = "",
    genre: str = "",
    min_bpm: int | None = None,
    max_bpm: int | None = None,
    min_duration: int = 30,
    max_duration: int = 300,
    limit: int = 20,
) -> list[MusicTrack]:
    """Search for royalty-free music tracks via the Jamendo API.

    Parameters
    ----------
    query:
        Free-text search (searches track name, artist, tags).
    mood:
        Mood filter (e.g. "happy", "sad", "epic", "chill").
    genre:
        Genre filter (e.g. "pop", "electronic", "classical").
    min_bpm / max_bpm:
        BPM range filter (mapped to Jamendo's speed parameter).
    min_duration / max_duration:
        Duration range in seconds.
    limit:
        Maximum number of results (1-200).

    Returns
    -------
    list[MusicTrack]
        Matching tracks sorted by relevance.
    """
    if not _is_available():
        logger.warning("Jamendo API not configured (set JAMENDO_CLIENT_ID env var)")
        return []

    # Build query parameters
    params: dict[str, str] = {
        "client_id": JAMENDO_CLIENT_ID,
        "format": "json",
        "limit": str(min(max(1, limit), 200)),
        "include": "musicinfo+licenses",
        "audioformat": "mp32",
        "order": "relevance",
        "imagesize": "200",
    }

    if query:
        params["search"] = query

    # Build tag list from mood + genre
    tags: list[str] = []

    if mood:
        mood_lower = mood.lower().strip()
        mood_info = _MOOD_TAG_MAP.get(mood_lower)
        if mood_info:
            tags.extend(mood_info["tags"][:2])
            # Set speed if no BPM specified
            if min_bpm is None and max_bpm is None:
                params["speed"] = mood_info["speed"]
        else:
            # Use mood as a raw tag
            tags.append(mood_lower)

    if genre:
        genre_lower = genre.lower().strip()
        genre_tags = _GENRE_TAG_MAP.get(genre_lower)
        if genre_tags:
            tags.extend(genre_tags[:1])
        else:
            tags.append(genre_lower)

    # Use fuzzytags (OR logic) for broader matching
    if tags:
        params["fuzzytags"] = "+".join(tags)

    # Map BPM range to Jamendo speed parameter
    if min_bpm is not None or max_bpm is not None:
        speed = _bpm_to_speed(min_bpm, max_bpm)
        if speed:
            params["speed"] = speed

    # Duration filter
    if min_duration or max_duration:
        dur_min = max(0, min_duration) if min_duration else 0
        dur_max = max_duration if max_duration else 600
        params["durationbetween"] = f"{dur_min}_{dur_max}"

    # Check cache
    cache_key = hashlib.md5(urlencode(sorted(params.items())).encode()).hexdigest()
    if cache_key in _search_cache:
        cached_time, cached_results = _search_cache[cache_key]
        if time.time() - cached_time < _CACHE_TTL:
            logger.debug("Returning cached results for key %s", cache_key[:8])
            return [_dict_to_track(r) for r in cached_results]

    # Make API request
    try:
        url = f"{JAMENDO_API_BASE}/tracks/"
        logger.info("Jamendo search: %s", urlencode(params))
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.error("Jamendo API request failed: %s", exc)
        return []

    if data.get("headers", {}).get("status") != "success":
        logger.warning("Jamendo API returned non-success: %s", data.get("headers", {}))
        return []

    results = data.get("results", [])

    # Cache raw results
    _search_cache[cache_key] = (time.time(), results)

    # Evict old cache entries
    now = time.time()
    expired = [k for k, (t, _) in _search_cache.items() if now - t > _CACHE_TTL]
    for k in expired:
        del _search_cache[k]

    return [_dict_to_track(r) for r in results]


def _dict_to_track(raw: dict) -> MusicTrack:
    """Convert a Jamendo API result dict to a MusicTrack."""
    # Extract music info if available
    music_info = raw.get("musicinfo") or {}
    tags_info = music_info.get("tags") or {}

    # Collect all tags
    all_tags: list[str] = []
    for tag_group in ("genres", "instruments", "vartags"):
        group_tags = tags_info.get(tag_group, [])
        if isinstance(group_tags, list):
            all_tags.extend(group_tags)

    # Determine genre from tags
    genres = tags_info.get("genres", [])
    genre = genres[0] if genres else ""

    # Determine mood from vartags
    vartags = tags_info.get("vartags", [])
    mood = vartags[0] if vartags else ""

    # Map speed to approximate BPM
    speed_str = music_info.get("speed", "")
    bpm = _speed_to_approx_bpm(speed_str)

    # License info — Jamendo returns a dict like {"ccnc": "true", "ccnd": "true", ...}
    licenses = raw.get("licenses", {})
    license_url = raw.get("license_ccurl", "")
    if isinstance(licenses, dict) and any(v == "true" for v in licenses.values()):
        parts = ["CC"]
        parts.append("BY")
        if licenses.get("ccnc") == "true":
            parts.append("NC")
        if licenses.get("ccnd") == "true":
            parts.append("ND")
        if licenses.get("ccsa") == "true":
            parts.append("SA")
        license_str = " ".join(parts) if len(parts) > 1 else "Creative Commons"
    elif "by-nc-sa" in license_url:
        license_str = "CC BY-NC-SA"
    elif "by-nc-nd" in license_url:
        license_str = "CC BY-NC-ND"
    elif "by-nc" in license_url:
        license_str = "CC BY-NC"
    elif "by-sa" in license_url:
        license_str = "CC BY-SA"
    elif "by-nd" in license_url:
        license_str = "CC BY-ND"
    elif "by" in license_url:
        license_str = "CC BY"
    else:
        license_str = "Creative Commons"

    return MusicTrack(
        id=str(raw.get("id", "")),
        title=raw.get("name", "Unknown"),
        artist=raw.get("artist_name", "Unknown"),
        duration=int(raw.get("duration", 0)),
        bpm=bpm,
        genre=genre,
        mood=mood,
        preview_url=raw.get("audio", ""),
        download_url=raw.get("audiodownload", "") or raw.get("audio", ""),
        license=license_str,
        tags=all_tags,
        image_url=raw.get("image", "") or raw.get("album_image", ""),
    )


def _bpm_to_speed(min_bpm: int | None, max_bpm: int | None) -> str | None:
    """Map a BPM range to Jamendo's speed parameter.

    Jamendo speed values: verylow, low, medium, high, veryhigh
    Approximate BPM mapping:
        verylow: < 70
        low: 70-100
        medium: 100-130
        high: 130-160
        veryhigh: > 160
    """
    if min_bpm is None and max_bpm is None:
        return None

    avg = 0
    if min_bpm and max_bpm:
        avg = (min_bpm + max_bpm) / 2
    elif min_bpm:
        avg = min_bpm + 15
    elif max_bpm:
        avg = max_bpm - 15

    if avg < 70:
        return "verylow"
    elif avg < 100:
        return "low"
    elif avg < 130:
        return "medium"
    elif avg < 160:
        return "high"
    else:
        return "veryhigh"


def _speed_to_approx_bpm(speed: str) -> int | None:
    """Map Jamendo speed string to an approximate BPM value."""
    mapping = {
        "verylow": 60,
        "low": 85,
        "medium": 115,
        "high": 145,
        "veryhigh": 175,
    }
    return mapping.get(speed.lower()) if speed else None


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_track(track: MusicTrack, output_dir: str) -> str:
    """Download a music track to disk.

    Parameters
    ----------
    track:
        The MusicTrack to download.
    output_dir:
        Directory to save the downloaded file.

    Returns
    -------
    str
        Local file path of the downloaded track.
    """
    if not track.download_url:
        raise ValueError(f"Track {track.id} has no download URL")

    os.makedirs(output_dir, exist_ok=True)

    # Create a safe filename
    safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in track.title).strip()
    safe_title = safe_title[:50] or "track"
    filename = f"jamendo_{track.id}_{safe_title}.mp3"
    filepath = os.path.join(output_dir, filename)

    # Skip if already downloaded
    if os.path.exists(filepath):
        logger.info("Track already downloaded: %s", filepath)
        return filepath

    # Download with the client_id appended if needed
    download_url = track.download_url
    if JAMENDO_CLIENT_ID and "client_id" not in download_url:
        separator = "&" if "?" in download_url else "?"
        download_url = f"{download_url}{separator}client_id={JAMENDO_CLIENT_ID}"

    logger.info("Downloading track %s: %s", track.id, track.title)
    try:
        resp = requests.get(download_url, timeout=120, stream=True)
        resp.raise_for_status()
        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        logger.info("Downloaded to: %s", filepath)
        return filepath
    except requests.RequestException as exc:
        # Clean up partial file
        if os.path.exists(filepath):
            os.unlink(filepath)
        raise RuntimeError(f"Failed to download track {track.id}: {exc}") from exc


# ---------------------------------------------------------------------------
# Suggest music (AI director integration)
# ---------------------------------------------------------------------------

def suggest_music(
    music_mood: str,
    target_duration: float = 60.0,
    limit: int = 10,
) -> list[MusicTrack]:
    """Suggest music tracks based on the AI director's music_mood recommendation.

    Parses the natural-language mood string into search parameters and returns
    matching tracks.

    Parameters
    ----------
    music_mood:
        Natural language mood description from the AI director,
        e.g. "upbeat indie pop with driving rhythm".
    target_duration:
        Target video duration in seconds (used to filter track length).
    limit:
        Maximum number of results.

    Returns
    -------
    list[MusicTrack]
        Matching tracks sorted by relevance.
    """
    if not music_mood:
        return []

    mood_lower = music_mood.lower()

    # Parse mood keywords
    detected_mood = ""
    for mood_key in _MOOD_TAG_MAP:
        if mood_key in mood_lower:
            detected_mood = mood_key
            break

    # Parse genre keywords
    detected_genre = ""
    for genre_key in _GENRE_TAG_MAP:
        if genre_key in mood_lower:
            detected_genre = genre_key
            break

    # If no structured mood/genre found, use the whole string as a query
    query = ""
    if not detected_mood and not detected_genre:
        query = music_mood

    # Set duration range around the target
    min_dur = max(30, int(target_duration * 0.5))
    max_dur = max(120, int(target_duration * 2.5))

    return search_music(
        query=query,
        mood=detected_mood,
        genre=detected_genre,
        min_duration=min_dur,
        max_duration=max_dur,
        limit=limit,
    )


def get_track_by_id(track_id: str) -> MusicTrack | None:
    """Fetch a single track by its Jamendo ID.

    Parameters
    ----------
    track_id:
        The Jamendo track ID.

    Returns
    -------
    MusicTrack or None
        The track if found, else None.
    """
    if not _is_available():
        logger.warning("Jamendo API not configured (set JAMENDO_CLIENT_ID env var)")
        return None

    params = {
        "client_id": JAMENDO_CLIENT_ID,
        "format": "json",
        "id": track_id,
        "include": "musicinfo+licenses",
        "audioformat": "mp32",
        "imagesize": "200",
    }

    try:
        url = f"{JAMENDO_API_BASE}/tracks/"
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.error("Jamendo API request failed: %s", exc)
        return None

    results = data.get("results", [])
    if not results:
        return None

    return _dict_to_track(results[0])
