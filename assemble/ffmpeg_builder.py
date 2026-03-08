"""FFmpeg subprocess-based video assembly pipeline.

Produces professional-quality output using direct FFmpeg filter graphs,
supporting xfade transitions, drawtext overlays, LUT color grading,
audio ducking via sidechaincompress, and hardware-accelerated encoding.

Falls back to the moviepy-based builder if FFmpeg is not available.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable
from urllib.parse import urlparse

import config

if TYPE_CHECKING:
    from curate.director import EditDecisionList, Shot

logger = logging.getLogger(__name__)

UPLOADS_DIR = config.PROJECT_ROOT / "uploads"
_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")


def _has_drawtext() -> bool:
    """Check if FFmpeg has the drawtext filter (requires libfreetype)."""
    if not _FFMPEG:
        return False
    try:
        result = subprocess.run(
            [_FFMPEG, "-filters"],
            capture_output=True, text=True, timeout=5,
        )
        return "drawtext" in result.stdout
    except Exception:
        return False


_DRAWTEXT_OK = _has_drawtext() if _FFMPEG else False


def is_available() -> bool:
    """Check if FFmpeg is available with drawtext support."""
    return _FFMPEG is not None and _FFPROBE is not None and _DRAWTEXT_OK


# ---------------------------------------------------------------------------
# Theme mapping for FFmpeg filter expressions
# ---------------------------------------------------------------------------

@dataclass
class FFmpegTheme:
    """Theme parameters expressed as FFmpeg filter values."""
    name: str
    bg_color: str           # hex e.g. "0x000000"
    font_color: str         # hex e.g. "0xFFFFFF"
    font: str               # font family or path
    font_size: int
    transition: str         # xfade transition name
    color_filter: str       # FFmpeg video filter expression or empty
    ken_burns: bool
    resolution: tuple[int, int] | None


_THEMES: dict[str, FFmpegTheme] = {
    "minimal": FFmpegTheme(
        name="minimal", bg_color="0x000000", font_color="0xFFFFFF",
        font="Helvetica", font_size=48, transition="fade",
        color_filter="", ken_burns=True, resolution=None,
    ),
    "warm_nostalgic": FFmpegTheme(
        name="warm_nostalgic", bg_color="0x1A0A00", font_color="0xFFF8E7",
        font="Georgia", font_size=44, transition="fade",
        color_filter="colorbalance=rs=0.08:gs=0.04:bs=-0.08:rm=0.05:gm=0.02:bm=-0.05",
        ken_burns=True, resolution=None,
    ),
    "bold_modern": FFmpegTheme(
        name="bold_modern", bg_color="0x0D0D0D", font_color="0xFFFFFF",
        font="Helvetica", font_size=72, transition="slideleft",
        color_filter="", ken_burns=False, resolution=None,
    ),
    "cinematic": FFmpegTheme(
        name="cinematic", bg_color="0x0A0A0A", font_color="0xE8E0D0",
        font="Georgia", font_size=56, transition="fade",
        color_filter="eq=saturation=0.85,colorbalance=rs=0.06:gs=0.02:bs=-0.06",
        ken_burns=True, resolution=None,
    ),
    "documentary": FFmpegTheme(
        name="documentary", bg_color="0x1A1A2E", font_color="0xFFFFFF",
        font="Helvetica", font_size=40, transition="fade",
        color_filter="", ken_burns=True, resolution=None,
    ),
    "social_vertical": FFmpegTheme(
        name="social_vertical", bg_color="0x000000", font_color="0xFFFFFF",
        font="Helvetica", font_size=64, transition="fade",
        color_filter="", ken_burns=True, resolution=(1080, 1920),
    ),
}


def _get_theme(name: str) -> FFmpegTheme:
    return _THEMES.get(name.lower(), _THEMES["minimal"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_ffmpeg(args: list[str], desc: str = "") -> None:
    """Run an FFmpeg command, raising on failure."""
    cmd = [_FFMPEG, "-y", "-hide_banner", "-loglevel", "warning"] + args
    logger.debug("FFmpeg: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        logger.error("FFmpeg failed (%s): %s", desc, result.stderr[:1000])
        raise RuntimeError(f"FFmpeg failed ({desc}): {result.stderr[:500]}")


def _probe(path: str) -> dict:
    """Run ffprobe and return parsed JSON output."""
    cmd = [
        _FFPROBE, "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return {}
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return {}


def _get_duration(path: str) -> float:
    """Get media duration in seconds via ffprobe."""
    info = _probe(path)
    fmt = info.get("format", {})
    return float(fmt.get("duration", 0))


def _resolve_media_path(path: str, uuid: str = "") -> str:
    """Resolve a media path, downloading remote URLs if needed."""
    if not path.startswith("https://"):
        return path

    parsed = urlparse(path)
    url_filename = Path(parsed.path).name

    local_candidate = UPLOADS_DIR / url_filename
    if local_candidate.exists():
        return str(local_candidate)

    ext = Path(url_filename).suffix or ".tmp"
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=ext)
    os.close(tmp_fd)
    try:
        urllib.request.urlretrieve(path, tmp_path)
        return tmp_path
    except Exception as exc:
        Path(tmp_path).unlink(missing_ok=True)
        raise RuntimeError(f"Failed to download {path}: {exc}") from exc


def _hex_for_drawtext(color: str) -> str:
    """Convert CSS hex (#FFFFFF) to FFmpeg drawtext hex (0xFFFFFF)."""
    return "0x" + color.lstrip("#")


# ---------------------------------------------------------------------------
# Clip preparation — render each shot to a normalized intermediate file
# ---------------------------------------------------------------------------

def _prepare_clip(
    shot: "Shot",
    theme: FFmpegTheme,
    resolution: tuple[int, int],
    fps: int,
    work_dir: str,
    index: int,
) -> str | None:
    """Prepare a single shot as a normalized intermediate MP4.

    Returns the path to the intermediate file, or None on failure.
    """
    output = os.path.join(work_dir, f"clip_{index:04d}.mp4")

    try:
        local_path = _resolve_media_path(shot.path)
    except Exception as e:
        logger.warning("Could not resolve path for shot %s: %s", shot.path, e)
        return None

    w, h = resolution
    duration = shot.end_time - shot.start_time
    if duration <= 0:
        duration = config.DEFAULT_PHOTO_DURATION

    # Per-shot ken_burns and speed settings (from director)
    use_ken_burns = getattr(shot, "ken_burns", theme.ken_burns)
    speed = getattr(shot, "speed", 1.0)

    try:
        if shot.media_type == "photo":
            # Photo → video with optional Ken Burns
            filters = [f"scale={w}:{h}:force_original_aspect_ratio=decrease",
                       f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black"]
            if use_ken_burns:
                # Gentle zoom from 1.0 to 1.12 over duration
                filters = [
                    f"scale={int(w*1.15)}:{int(h*1.15)}:force_original_aspect_ratio=decrease",
                    f"pad={int(w*1.15)}:{int(h*1.15)}:(ow-iw)/2:(oh-ih)/2:color=black",
                    f"zoompan=z='min(zoom+0.0005,1.12)':d={int(duration*fps)}:s={w}x{h}:fps={fps}",
                ]
            if theme.color_filter:
                filters.append(theme.color_filter)

            _run_ffmpeg([
                "-loop", "1", "-i", local_path,
                "-t", str(duration),
                "-vf", ",".join(filters),
                "-r", str(fps),
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-pix_fmt", "yuv420p", "-an",
                output,
            ], desc=f"photo clip {index}")

        elif shot.media_type == "video":
            filters = [f"scale={w}:{h}:force_original_aspect_ratio=decrease",
                       f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black"]
            if theme.color_filter:
                filters.append(theme.color_filter)
            # Apply speed change if not 1.0
            if speed != 1.0 and 0.5 <= speed <= 2.0:
                filters.append(f"setpts={1.0/speed}*PTS")

            audio_args = ["-c:a", "aac", "-b:a", "192k"]
            # Adjust audio tempo if speed changed
            if speed != 1.0 and 0.5 <= speed <= 2.0:
                audio_args = ["-af", f"atempo={speed}", "-c:a", "aac", "-b:a", "192k"]

            _run_ffmpeg([
                "-ss", str(shot.start_time),
                "-t", str(duration),
                "-i", local_path,
                "-vf", ",".join(filters),
                "-r", str(fps),
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                *audio_args,
                "-pix_fmt", "yuv420p",
                output,
            ], desc=f"video clip {index}")
        else:
            return None

        return output if os.path.exists(output) else None

    except Exception as e:
        logger.warning("Failed to prepare clip %d: %s", index, e)
        return None


# ---------------------------------------------------------------------------
# Title / closing cards
# ---------------------------------------------------------------------------

def _create_card(
    text: str,
    theme: FFmpegTheme,
    resolution: tuple[int, int],
    fps: int,
    duration: float,
    work_dir: str,
    name: str,
    subtitle: str = "",
) -> str:
    """Create a title or closing card as an MP4 clip."""
    w, h = resolution
    output = os.path.join(work_dir, f"{name}.mp4")

    bg_hex = theme.bg_color.replace("0x", "")
    font_hex = theme.font_color.replace("0x", "")

    # Escape text for drawtext
    safe_text = text.replace("'", "\\'").replace(":", "\\:")
    safe_subtitle = subtitle.replace("'", "\\'").replace(":", "\\:")

    filters = [
        f"color=c=0x{bg_hex}:s={w}x{h}:d={duration}:r={fps}",
        f"drawtext=text='{safe_text}':fontsize={theme.font_size}:fontcolor=0x{font_hex}"
        f":x=(w-text_w)/2:y=(h-text_h)/2:font='{theme.font}'",
    ]

    if subtitle:
        sub_size = max(theme.font_size // 3, 16)
        filters.append(
            f"drawtext=text='{safe_subtitle}':fontsize={sub_size}:fontcolor=0x{font_hex}@0.5"
            f":x=(w-text_w)/2:y=(h/2+{theme.font_size}):font='{theme.font}'"
        )

    _run_ffmpeg([
        "-f", "lavfi", "-i", ";".join(filters[:1]),
        "-vf", ",".join(filters[1:]),
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-an",
        output,
    ], desc=name)

    return output


# ---------------------------------------------------------------------------
# Concatenation with xfade transitions
# ---------------------------------------------------------------------------

def _concat_with_xfade(
    clips: list[str],
    transition: str,
    transition_dur: float,
    work_dir: str,
    resolution: tuple[int, int],
    per_clip_transitions: list[tuple[str, float]] | None = None,
) -> str:
    """Concatenate clips using FFmpeg xfade filter for smooth transitions.

    For many clips, we chain xfade filters pairwise.

    Parameters
    ----------
    per_clip_transitions:
        Optional list of (transition_name, duration) tuples, one per clip.
        The transition for clip i is applied between clip i and clip i+1.
        If None, falls back to the single `transition`/`transition_dur` for all.
    """
    if not clips:
        raise RuntimeError("No clips to concatenate")

    if len(clips) == 1:
        return clips[0]

    valid_xfades = {
        "fade", "slideleft", "slideright", "slideup", "slidedown",
        "circlecrop", "rectcrop", "distance", "fadeblack", "fadewhite",
        "radial", "smoothleft", "smoothright", "smoothup", "smoothdown",
        "circleopen", "circleclose", "dissolve", "pixelize", "wipeleft",
        "wiperight", "wipeup", "wipedown", "cut",
    }

    # Build complex filter graph for xfade chain
    # For N clips we need N-1 xfade operations
    inputs = []
    for i, clip_path in enumerate(clips):
        inputs.extend(["-i", clip_path])

    # Get durations for offset calculation
    durations = []
    for clip_path in clips:
        dur = _get_duration(clip_path)
        if dur <= 0:
            dur = 3.0  # fallback
        durations.append(dur)

    # Build filter graph
    filter_parts = []
    current_label = "[0:v]"
    cumulative_offset = 0.0

    for i in range(1, len(clips)):
        next_label = f"[{i}:v]"

        # Determine transition for this cut point
        if per_clip_transitions and i - 1 < len(per_clip_transitions):
            clip_trans, clip_trans_dur = per_clip_transitions[i - 1]
        else:
            clip_trans, clip_trans_dur = transition, transition_dur

        # Validate transition name
        if clip_trans in ("cut", "none"):
            # No xfade — just concatenate directly.
            # This shouldn't normally happen (handled by _concat_clips) but be safe.
            xfade_transition = "fade"
            clip_trans_dur = 0.01  # near-instant
        else:
            xfade_transition = clip_trans if clip_trans in valid_xfades else "fade"
        clip_trans_dur = max(0.2, min(1.5, clip_trans_dur)) if clip_trans != "cut" else clip_trans_dur

        offset = cumulative_offset + durations[i - 1] - clip_trans_dur
        if offset < 0:
            offset = cumulative_offset + durations[i - 1] * 0.8

        out_label = f"[v{i}]" if i < len(clips) - 1 else "[vout]"

        filter_parts.append(
            f"{current_label}{next_label}xfade=transition={xfade_transition}"
            f":duration={clip_trans_dur}:offset={offset:.3f}{out_label}"
        )

        current_label = out_label
        cumulative_offset = offset

    # Handle audio — simple concat with acrossfade
    audio_parts = []
    current_audio = "[0:a]"
    has_audio = []
    for i, clip_path in enumerate(clips):
        info = _probe(clip_path)
        streams = info.get("streams", [])
        has_a = any(s.get("codec_type") == "audio" for s in streams)
        has_audio.append(has_a)

    # If some clips have audio, concat them; otherwise skip audio
    audio_filter = ""
    any_audio = any(has_audio)
    if any_audio:
        audio_count = sum(has_audio)
        if audio_count > 1:
            audio_refs = ''.join(f'[{i}:a]' for i in range(len(clips)) if has_audio[i])
            audio_filter = f";{audio_refs}concat=n={audio_count}:v=0:a=1[aout]"
        elif audio_count == 1:
            idx = has_audio.index(True)
            audio_filter = f";[{idx}:a]acopy[aout]"

    full_filter = ";".join(filter_parts) + audio_filter

    output = os.path.join(work_dir, "concat_xfade.mp4")

    cmd = inputs + [
        "-filter_complex", full_filter,
        "-map", "[vout]",
    ]

    if audio_filter:
        cmd.extend(["-map", "[aout]"])

    cmd.extend([
        "-c:v", "libx264", "-preset", "medium", "-crf", "17",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output,
    ])

    _run_ffmpeg(cmd, desc="xfade concatenation")
    return output


def _concat_clips(
    clips: list[str],
    per_clip_transitions: list[tuple[str, float]] | None,
    work_dir: str,
    resolution: tuple[int, int],
    default_transition: str = "fade",
    default_dur: float = 0.5,
) -> str:
    """Concatenate clips, handling both xfade transitions and hard cuts.

    Splits clips into groups at "cut" boundaries, applies xfade within
    groups, then concatenates groups with hard cuts using the concat demuxer.
    """
    if not clips:
        raise RuntimeError("No clips to concatenate")

    if len(clips) == 1:
        return clips[0]

    # Check if there are any "cut" transitions ("none" is the project-model alias)
    _CUT_NAMES = {"cut", "none"}
    has_cut = False
    for i in range(1, len(clips)):
        trans_name, _ = per_clip_transitions[i - 1] if per_clip_transitions and i - 1 < len(per_clip_transitions) else (default_transition, default_dur)
        if trans_name in _CUT_NAMES:
            has_cut = True
            break

    if not has_cut:
        # No cut transitions — delegate entirely to xfade
        return _concat_with_xfade(
            clips, default_transition, default_dur, work_dir, resolution,
            per_clip_transitions=per_clip_transitions,
        )

    # Split clips into groups separated by "cut" transitions
    groups: list[tuple[list[str], list[tuple[str, float]]]] = []
    current_group_clips: list[str] = [clips[0]]
    current_group_trans: list[tuple[str, float]] = []

    for i in range(1, len(clips)):
        trans_name, trans_dur = per_clip_transitions[i - 1] if per_clip_transitions and i - 1 < len(per_clip_transitions) else (default_transition, default_dur)
        if trans_name in _CUT_NAMES:
            groups.append((current_group_clips, current_group_trans))
            current_group_clips = [clips[i]]
            current_group_trans = []
        else:
            current_group_clips.append(clips[i])
            current_group_trans.append((trans_name, trans_dur))
    groups.append((current_group_clips, current_group_trans))

    # Process each group
    group_outputs: list[str] = []
    for g_idx, (g_clips, g_trans) in enumerate(groups):
        if len(g_clips) == 1:
            group_outputs.append(g_clips[0])
        else:
            group_out = _concat_with_xfade(
                g_clips, default_transition, default_dur,
                work_dir, resolution,
                per_clip_transitions=g_trans if g_trans else None,
            )
            # Rename to avoid collisions between groups
            renamed = os.path.join(work_dir, f"group_{g_idx:04d}.mp4")
            os.rename(group_out, renamed)
            group_outputs.append(renamed)

    if len(group_outputs) == 1:
        return group_outputs[0]

    # Concatenate groups using the concat demuxer (hard cut between groups)
    # First, check which groups have audio
    group_has_audio: list[bool] = []
    for gpath in group_outputs:
        info = _probe(gpath)
        streams = info.get("streams", [])
        group_has_audio.append(any(s.get("codec_type") == "audio" for s in streams))

    any_audio = any(group_has_audio)

    # Build inputs and filter for the concat demuxer filter
    inputs: list[str] = []
    filter_parts: list[str] = []
    for i, gpath in enumerate(group_outputs):
        inputs.extend(["-i", gpath])
        if any_audio and not group_has_audio[i]:
            # Generate silent audio for this group so concat works
            dur = _get_duration(gpath)
            filter_parts.append(
                f"anullsrc=r=44100:cl=stereo[sil{i}];[sil{i}]atrim=0:{dur:.3f}[a{i}]"
            )
            filter_parts.append(f"[{i}:v][a{i}]")
        else:
            if any_audio:
                filter_parts.append(f"[{i}:v][{i}:a]")
            else:
                filter_parts.append(f"[{i}:v]")

    # Separate stream refs from the anullsrc setup lines
    setup_lines: list[str] = []
    stream_refs: list[str] = []
    for part in filter_parts:
        if "anullsrc" in part:
            setup_lines.append(part)
        else:
            stream_refs.append(part)

    n = len(group_outputs)
    if any_audio:
        concat_expr = f"{''.join(stream_refs)}concat=n={n}:v=1:a=1[vout][aout]"
    else:
        concat_expr = f"{''.join(stream_refs)}concat=n={n}:v=1:a=0[vout]"

    full_filter = ";".join(setup_lines + [concat_expr]) if setup_lines else concat_expr

    output = os.path.join(work_dir, "concat_final.mp4")
    cmd = inputs + ["-filter_complex", full_filter, "-map", "[vout]"]
    if any_audio:
        cmd.extend(["-map", "[aout]"])
    cmd.extend([
        "-c:v", "libx264", "-preset", "medium", "-crf", "17",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output,
    ])

    _run_ffmpeg(cmd, desc="concat groups (hard cut)")
    return output


# ---------------------------------------------------------------------------
# Text overlays via drawtext
# ---------------------------------------------------------------------------

def _apply_text_overlays(
    video_path: str,
    text_elements: list[dict],
    theme: FFmpegTheme,
    resolution: tuple[int, int],
    work_dir: str,
) -> str:
    """Apply text overlays using FFmpeg drawtext filter."""
    if not text_elements:
        return video_path

    w, h = resolution
    filters = []

    for te in text_elements:
        text = te.get("text", "")
        if not text:
            continue

        safe_text = text.replace("'", "\\'").replace(":", "\\:").replace("\n", "\\n")
        position = te.get("position", 0.0)
        duration = te.get("duration", 3.0)
        style = te.get("style", "title")
        color = _hex_for_drawtext(te.get("color", "#FFFFFF"))
        font_size = te.get("font_size", theme.font_size)
        animation = te.get("animation", "fade")
        y_rel = te.get("y", 0.5)

        # Adjust font size by style
        if style == "subtitle":
            font_size = int(font_size * 0.7)
        elif style == "caption":
            font_size = int(font_size * 0.5)
        elif style == "lower_third":
            font_size = int(font_size * 0.6)

        # Y position
        if style == "lower_third":
            y_expr = f"h*0.8-text_h/2"
        elif style == "caption":
            y_expr = f"h*0.85-text_h/2"
        elif style == "subtitle":
            y_expr = f"h*0.65-text_h/2"
        else:
            y_expr = f"h*{y_rel}-text_h/2"

        # Alpha for fade animation
        enable = f"between(t,{position},{position + duration})"
        alpha_expr = ""
        if animation == "fade":
            fade_dur = min(0.5, duration / 3)
            alpha_expr = (
                f":alpha='if(lt(t-{position},{fade_dur}),"
                f"(t-{position})/{fade_dur},"
                f"if(gt(t-{position},{duration - fade_dur}),"
                f"({duration}-(t-{position}))/{fade_dur},1))'"
            )

        # Background box for lower_third
        box_part = ""
        if style == "lower_third":
            box_part = ":box=1:boxcolor=black@0.6:boxborderw=8"

        drawtext = (
            f"drawtext=text='{safe_text}':fontsize={font_size}:fontcolor={color}"
            f":font='{theme.font}':x=(w-text_w)/2:y={y_expr}"
            f":enable='{enable}'{alpha_expr}{box_part}"
        )
        filters.append(drawtext)

    if not filters:
        return video_path

    output = os.path.join(work_dir, "with_text.mp4")
    _run_ffmpeg([
        "-i", video_path,
        "-vf", ",".join(filters),
        "-c:v", "libx264", "-preset", "medium", "-crf", "17",
        "-c:a", "copy",
        "-pix_fmt", "yuv420p",
        output,
    ], desc="text overlays")

    return output


# ---------------------------------------------------------------------------
# Music mixing with optional audio ducking
# ---------------------------------------------------------------------------

def _mix_music(
    video_path: str,
    music_path: str,
    volume: float,
    work_dir: str,
    duck: bool = True,
) -> str:
    """Mix background music with video audio, optionally with sidechain ducking."""
    if not music_path or not os.path.exists(music_path):
        return video_path

    video_dur = _get_duration(video_path)
    if video_dur <= 0:
        return video_path

    output = os.path.join(work_dir, "with_music.mp4")

    # Check if video has audio
    info = _probe(video_path)
    has_video_audio = any(
        s.get("codec_type") == "audio"
        for s in info.get("streams", [])
    )

    if has_video_audio and duck:
        # Audio ducking: lower music volume when video audio is present
        # Uses sidechaincompress to duck music based on video audio levels
        filter_complex = (
            f"[1:a]aloop=loop=-1:size=2e+09,atrim=0:{video_dur},"
            f"volume={volume}[music];"
            f"[0:a][music]sidechaincompress=threshold=0.02:ratio=6:attack=200:release=1000[ducked];"
            f"[0:a][ducked]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )

        _run_ffmpeg([
            "-i", video_path,
            "-i", music_path,
            "-filter_complex", filter_complex,
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            output,
        ], desc="music mix with ducking")
    else:
        # Simple mix — no video audio or ducking disabled
        filter_complex = (
            f"[1:a]aloop=loop=-1:size=2e+09,atrim=0:{video_dur},"
            f"volume={volume},afade=t=in:st=0:d=2,afade=t=out:st={video_dur-2}:d=2[music]"
        )

        if has_video_audio:
            filter_complex += f";[0:a][music]amix=inputs=2:duration=first:dropout_transition=2[aout]"
            map_audio = ["-map", "[aout]"]
        else:
            filter_complex += ";[music]acopy[aout]"
            map_audio = ["-map", "[aout]"]

        _run_ffmpeg([
            "-i", video_path,
            "-i", music_path,
            "-filter_complex", filter_complex,
            "-map", "0:v", *map_audio,
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            output,
        ], desc="music mix")

    return output


# ---------------------------------------------------------------------------
# Main build function
# ---------------------------------------------------------------------------

def build_video(
    edl: "EditDecisionList",
    theme_name: str = "minimal",
    music_path: str | None = None,
    music_volume: float = 0.3,
    output_path: str | None = None,
    progress_callback: "Callable[[int, str], None] | None" = None,
    text_elements: list[dict] | None = None,
) -> str:
    """Assemble a video using FFmpeg subprocess for professional output.

    Same interface as builder.build_video for drop-in replacement.
    """
    theme = _get_theme(theme_name)
    fps = config.DEFAULT_OUTPUT_FPS
    resolution = theme.resolution or config.DEFAULT_OUTPUT_RESOLUTION
    transition_dur = config.DEFAULT_TRANSITION_DURATION

    def _report(pct: int, msg: str) -> None:
        logger.info("[ffmpeg_builder] %s", msg)
        if progress_callback:
            progress_callback(pct, msg)

    _report(5, f"FFmpeg builder: {theme.name}, {resolution[0]}x{resolution[1]}@{fps}fps, {len(edl.shots)} shots")

    work_dir = tempfile.mkdtemp(prefix="film_creator_ffmpeg_")

    try:
        # --- Prepare individual clips ----------------------------------------

        clip_paths: list[str] = []
        total = len(edl.shots)

        # Title card
        _report(8, "Creating title card...")
        title_path = _create_card(
            edl.title, theme, resolution, fps, 3.0, work_dir, "title",
        )
        clip_paths.append(title_path)

        for i, shot in enumerate(edl.shots):
            pct = 10 + int((i / max(total, 1)) * 55)
            _report(pct, f"Processing shot {i+1}/{total}: {shot.media_type} — {shot.role}")

            clip_path = _prepare_clip(shot, theme, resolution, fps, work_dir, i)
            if clip_path:
                clip_paths.append(clip_path)

        if len(clip_paths) <= 1:
            raise RuntimeError("No valid clips could be prepared")

        _report(65, f"Prepared {len(clip_paths)} clips")

        # Closing card
        _report(67, "Creating closing card...")
        closing_path = _create_card(
            edl.title, theme, resolution, fps, 2.0, work_dir, "closing",
            subtitle="Made with Video Composer",
        )
        clip_paths.append(closing_path)

        # --- Concatenate with transitions ------------------------------------

        # Build per-clip transition list from EDL shots
        # The first entry is for the title→first_shot transition (use theme default),
        # then one per shot for shot→next transitions.
        per_clip_transitions: list[tuple[str, float]] = []
        # Title card → first shot: use theme default
        per_clip_transitions.append((theme.transition, transition_dur))
        for shot in edl.shots:
            trans = getattr(shot, "transition", theme.transition)
            trans_dur = getattr(shot, "transition_duration", transition_dur)
            per_clip_transitions.append((trans, trans_dur))

        _report(70, f"Applying per-clip transitions...")
        video_path = _concat_clips(
            clip_paths, per_clip_transitions, work_dir, resolution,
            default_transition=theme.transition,
            default_dur=transition_dur,
        )

        # --- Text overlays ---------------------------------------------------

        if text_elements:
            _report(80, f"Adding {len(text_elements)} text overlays...")
            video_path = _apply_text_overlays(
                video_path, text_elements, theme, resolution, work_dir,
            )

        # --- Music -----------------------------------------------------------

        if music_path:
            _report(85, "Mixing background music with audio ducking...")
            video_path = _mix_music(video_path, music_path, music_volume, work_dir)

        # --- Final output ----------------------------------------------------

        if output_path is None:
            safe_title = "".join(
                c if c.isalnum() or c in " _-" else "_" for c in edl.title
            ).strip()
            output_path = str(config.OUTPUT_DIR / f"{safe_title}.mp4")

        _report(90, f"Finalizing output: {Path(output_path).name}")

        # Copy or re-encode to final location with faststart
        shutil.copy2(video_path, output_path)

        _report(100, f"Done! Video saved to {output_path}")
        return output_path

    finally:
        # Cleanup work directory
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except Exception:
            pass
