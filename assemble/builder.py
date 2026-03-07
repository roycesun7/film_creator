"""Main video assembly pipeline.

Takes an EditDecisionList from the curation layer and assembles a final
video using moviepy 2.x, applying themes, transitions, title cards, and
optional background music.
"""

from __future__ import annotations

import logging
import tempfile
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Callable
from urllib.parse import urlparse

import numpy as np
from moviepy import (
    AudioFileClip,
    ColorClip,
    CompositeVideoClip,
    ImageClip,
    TextClip,
    VideoFileClip,
    concatenate_videoclips,
    vfx,
    afx,
)

import config
from assemble.themes import (
    Theme,
    apply_color_filter,
    apply_ken_burns,
    fit_to_resolution,
    get_theme,
)

if TYPE_CHECKING:
    from curate.director import EditDecisionList, Shot

logger = logging.getLogger(__name__)

UPLOADS_DIR = config.PROJECT_ROOT / "uploads"


def _print_progress(msg: str) -> None:
    """Print a timestamped progress message."""
    print(f"[assemble] {msg}")


# ---------------------------------------------------------------------------
# Media path resolution (local files and Supabase Storage URLs)
# ---------------------------------------------------------------------------

def _resolve_media_path(shot: "Shot") -> str:
    """Resolve a shot's path to a local file path.

    If ``shot.path`` is a URL (starts with ``https://``), the function first
    checks whether a local copy already exists in the ``uploads/`` directory.
    The expected filename format is ``{uuid}{ext}``.  If a local copy is found,
    its path is returned; otherwise the file is downloaded to a temp location.

    For regular local paths the value is returned unchanged.
    """
    path = shot.path

    if not path.startswith("https://"):
        return path

    # Extract filename from URL (last path segment)
    parsed = urlparse(path)
    url_filename = Path(parsed.path).name  # e.g. "abc123.jpg"

    # Check for a local copy in uploads/
    local_candidate = UPLOADS_DIR / url_filename
    if local_candidate.exists():
        logger.debug("Using local copy for %s: %s", path, local_candidate)
        return str(local_candidate)

    # Download to a temporary file
    _print_progress(f"Downloading remote media: {url_filename}")
    ext = Path(url_filename).suffix or ".tmp"
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=ext)
    try:
        urllib.request.urlretrieve(path, tmp_path)
    except Exception as exc:
        logger.warning("Failed to download %s: %s", path, exc)
        raise
    finally:
        # Close the file descriptor opened by mkstemp
        import os
        os.close(tmp_fd)

    return tmp_path


# ---------------------------------------------------------------------------
# Individual clip preparation
# ---------------------------------------------------------------------------

def _prepare_photo_clip(
    shot: "Shot",
    theme: Theme,
    resolution: tuple[int, int],
    fps: int,
) -> "VideoFileClip | None":
    """Create a video clip from a still photo.

    Uses Ken Burns if enabled in the theme, otherwise a static clip with
    a subtle zoom applied.
    """
    duration = shot.end_time - shot.start_time
    if duration <= 0:
        duration = config.DEFAULT_PHOTO_DURATION
    try:
        local_path = _resolve_media_path(shot)
        if theme.ken_burns_enabled:
            clip = apply_ken_burns(local_path, duration, fps, resolution)
        else:
            # Static clip — letterbox/pillarbox to maintain aspect ratio
            fitted_array = fit_to_resolution(local_path, resolution, theme.bg_color)
            clip = (
                ImageClip(fitted_array)
                .with_duration(duration)
                .with_fps(fps)
            )
        return clip
    except Exception as exc:
        logger.warning("Failed to load photo %s: %s", shot.path, exc)
        _print_progress(f"WARNING: skipping photo {shot.path} ({exc})")
        return None


def _prepare_video_clip(
    shot: "Shot",
    resolution: tuple[int, int],
    fps: int,
    bg_color: str = "#000000",
) -> "VideoFileClip | None":
    """Load and trim a video clip according to the shot's time range."""
    raw_clip = None
    try:
        local_path = _resolve_media_path(shot)
        raw_clip = VideoFileClip(local_path)
        subclip = raw_clip.subclipped(shot.start_time, shot.end_time)
        clip = fit_to_resolution(subclip, resolution, bg_color)
        return clip
    except Exception as exc:
        if raw_clip is not None:
            try:
                raw_clip.close()
            except Exception:
                pass
        logger.warning("Failed to load video %s: %s", shot.path, exc)
        _print_progress(f"WARNING: skipping video {shot.path} ({exc})")
        return None


# ---------------------------------------------------------------------------
# Title card
# ---------------------------------------------------------------------------

def _create_title_card(
    title: str,
    theme: Theme,
    duration: float,
    resolution: tuple[int, int],
    fps: int,
) -> CompositeVideoClip:
    """Create a title card clip showing the video title over the theme bg."""
    from assemble.themes import _hex_to_rgb

    bg_rgb = _hex_to_rgb(theme.bg_color)
    font_rgb = _hex_to_rgb(theme.font_color)

    bg = (
        ColorClip(size=resolution, color=bg_rgb)
        .with_duration(duration)
        .with_fps(fps)
    )

    try:
        txt = (
            TextClip(
                text=title,
                font=theme.font,
                font_size=theme.font_size,
                color=theme.font_color,
                text_align="center",
                size=resolution,
                method="caption",
            )
            .with_duration(duration)
            .with_position("center")
        )
    except Exception:
        # TextClip can fail if the font isn't available; fall back to default
        _print_progress(
            f"WARNING: font '{theme.font}' not found, falling back to default"
        )
        txt = (
            TextClip(
                text=title,
                font_size=theme.font_size,
                color=theme.font_color,
                text_align="center",
                size=resolution,
                method="caption",
            )
            .with_duration(duration)
            .with_position("center")
        )

    title_card = CompositeVideoClip([bg, txt], size=resolution).with_duration(duration)

    # Fade in
    title_card = title_card.with_effects([vfx.CrossFadeIn(min(1.0, duration))])
    return title_card


# ---------------------------------------------------------------------------
# Closing card
# ---------------------------------------------------------------------------

def _create_closing_card(
    theme: Theme,
    duration: float,
    resolution: tuple[int, int],
    fps: int,
    title: str = "",
) -> CompositeVideoClip:
    """Create a closing card with optional title and branding text.

    Shows the video title (if provided) and a subtle
    "Made with Video Composer" line, using the theme's font settings.
    """
    from assemble.themes import _hex_to_rgb

    bg_rgb = _hex_to_rgb(theme.bg_color)

    bg = (
        ColorClip(size=resolution, color=bg_rgb)
        .with_duration(duration)
        .with_fps(fps)
    )

    layers = [bg]

    # Branding text — small and centred
    branding_text = "Made with Video Composer"
    branding_size = max(theme.font_size // 3, 16)
    try:
        branding = (
            TextClip(
                text=branding_text,
                font=theme.font,
                font_size=branding_size,
                color=theme.font_color,
                text_align="center",
                size=resolution,
                method="caption",
            )
            .with_duration(duration)
            .with_position("center")
        )
    except Exception:
        branding = (
            TextClip(
                text=branding_text,
                font_size=branding_size,
                color=theme.font_color,
                text_align="center",
                size=resolution,
                method="caption",
            )
            .with_duration(duration)
            .with_position("center")
        )
    layers.append(branding)

    closing_card = CompositeVideoClip(layers, size=resolution).with_duration(duration)
    closing_card = closing_card.with_effects([vfx.CrossFadeOut(min(1.0, duration))])
    return closing_card


# ---------------------------------------------------------------------------
# Text overlays
# ---------------------------------------------------------------------------

def _create_text_overlay(
    text_data: dict,
    theme: Theme,
    resolution: tuple[int, int],
    fps: int,
) -> CompositeVideoClip | None:
    """Create a text overlay clip from a TextElement dict.

    Supports styles: title, subtitle, caption, lower_third
    Supports animations: fade, slide_up, none
    """
    text = text_data.get("text", "")
    if not text:
        return None

    duration = text_data.get("duration", 3.0)
    style = text_data.get("style", "title")
    animation = text_data.get("animation", "fade")
    color = text_data.get("color", theme.font_color)
    font_size = text_data.get("font_size", theme.font_size)
    bg_color_hex = text_data.get("bg_color", "")

    # Adjust font size by style
    if style == "subtitle":
        font_size = int(font_size * 0.7)
    elif style == "caption":
        font_size = int(font_size * 0.5)
    elif style == "lower_third":
        font_size = int(font_size * 0.6)

    try:
        txt_clip = TextClip(
            text=text,
            font=theme.font,
            font_size=font_size,
            color=color,
            text_align="center",
            method="caption",
            size=(int(resolution[0] * 0.8), None),
        ).with_duration(duration)
    except Exception:
        txt_clip = TextClip(
            text=text,
            font_size=font_size,
            color=color,
            text_align="center",
            method="caption",
            size=(int(resolution[0] * 0.8), None),
        ).with_duration(duration)

    # Position based on style
    rel_y = text_data.get("y", 0.5)
    if style == "lower_third":
        txt_clip = txt_clip.with_position(("center", 0.8), relative=True)
    elif style == "caption":
        txt_clip = txt_clip.with_position(("center", 0.85), relative=True)
    elif style == "subtitle":
        txt_clip = txt_clip.with_position(("center", 0.65), relative=True)
    else:
        txt_clip = txt_clip.with_position(("center", rel_y), relative=True)

    # Add background bar for lower_third style
    if style == "lower_third" and not bg_color_hex:
        bg_color_hex = "#000000"

    # Apply animation
    effects = []
    if animation == "fade":
        fade_dur = min(0.5, duration / 3)
        effects.append(vfx.CrossFadeIn(fade_dur))
        effects.append(vfx.CrossFadeOut(fade_dur))
    elif animation == "slide_up":
        effects.append(vfx.CrossFadeIn(0.3))
        effects.append(vfx.CrossFadeOut(0.3))

    if effects:
        txt_clip = txt_clip.with_effects(effects)

    return txt_clip


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------

def _apply_transitions(
    clips: list,
    transition_type: str,
    transition_dur: float,
) -> list:
    """Return a list of clips with transition effects applied.

    For 'crossfade': clips overlap by transition_dur with cross-dissolve.
    For 'fade_black': each clip fades out, next fades in.
    For 'slide_left': falls back to crossfade for MVP.
    """
    if not clips:
        return clips

    effective_type = transition_type
    if effective_type == "slide_left":
        effective_type = "crossfade"  # MVP fallback

    processed: list = []

    if effective_type == "crossfade":
        current_start = 0.0
        for i, clip in enumerate(clips):
            if i > 0:
                clip = clip.with_effects([vfx.CrossFadeIn(transition_dur)])
                current_start = current_start + processed[-1].duration - transition_dur
                clip = clip.with_start(current_start)
            else:
                clip = clip.with_start(0)
            processed.append(clip)
            if i == 0:
                current_start = 0.0

    elif effective_type == "fade_black":
        for i, clip in enumerate(clips):
            clip = clip.with_effects([
                vfx.CrossFadeIn(transition_dur),
                vfx.CrossFadeOut(transition_dur),
            ])
            processed.append(clip)

    return processed


# ---------------------------------------------------------------------------
# Music
# ---------------------------------------------------------------------------

def _prepare_music(
    music_path: str,
    video_duration: float,
    volume: float = 0.3,
    fade_dur: float = 2.0,
) -> "AudioFileClip | None":
    """Load background music, loop if needed, and apply fades."""
    try:
        audio = AudioFileClip(music_path)
        if audio.duration < video_duration:
            # Loop the music to cover the full video
            repeats = int(video_duration / audio.duration) + 1
            from moviepy import concatenate_audioclips

            audio = concatenate_audioclips([audio] * repeats)
        # Trim to video length
        audio = audio.subclipped(0, video_duration)
        # Apply fades and volume
        audio = audio.with_effects([
            afx.AudioFadeIn(fade_dur),
            afx.AudioFadeOut(fade_dur),
            afx.MultiplyVolume(factor=volume),
        ])
        return audio
    except Exception as exc:
        logger.warning("Failed to load music %s: %s", music_path, exc)
        _print_progress(f"WARNING: could not load music ({exc})")
        return None


# ---------------------------------------------------------------------------
# Main build function
# ---------------------------------------------------------------------------

def build_video(
    edl: "EditDecisionList",
    theme_name: str = "minimal",
    music_path: str | None = None,
    output_path: str | None = None,
    progress_callback: "Callable[[int, str], None] | None" = None,
    text_elements: list[dict] | None = None,
) -> str:
    """Assemble a final video from an EditDecisionList.

    Args:
        edl: The edit decision list produced by the curation layer.
        theme_name: Name of the visual theme to apply.
        music_path: Optional path to a background music file.
        output_path: Where to write the final MP4. Defaults to
            ``config.OUTPUT_DIR / "{edl.title}.mp4"``.
        progress_callback: Optional function called with (percent, message)
            during assembly for progress reporting.
        text_elements: Optional list of text overlay dicts from the
            project timeline's text track.

    Returns:
        The absolute path to the rendered video file as a string.
    """
    theme = get_theme(theme_name)
    fps = config.DEFAULT_OUTPUT_FPS
    resolution = theme.resolution_override or config.DEFAULT_OUTPUT_RESOLUTION
    transition_dur = config.DEFAULT_TRANSITION_DURATION

    _print_progress(f"Theme: {theme.name}")
    _print_progress(f"Resolution: {resolution[0]}x{resolution[1]} @ {fps}fps")
    _print_progress(f"Shots to process: {len(edl.shots)}")

    def _report(pct: int, msg: str) -> None:
        _print_progress(msg)
        if progress_callback:
            progress_callback(pct, msg)

    # --- Build individual clips -------------------------------------------

    shot_clips: list = []
    total_shots = len(edl.shots)
    for i, shot in enumerate(edl.shots):
        shot_msg = (
            f"Processing shot {i + 1}/{total_shots}: "
            f"{shot.media_type} — {shot.role} — {Path(shot.path).name}"
        )
        # Map shot progress to 10-70% range
        shot_pct = 10 + int((i / max(total_shots, 1)) * 60)
        _report(shot_pct, shot_msg)

        if shot.media_type == "photo":
            clip = _prepare_photo_clip(shot, theme, resolution, fps)
        elif shot.media_type == "video":
            clip = _prepare_video_clip(shot, resolution, fps, theme.bg_color)
        else:
            _print_progress(f"WARNING: unknown media type '{shot.media_type}', skipping")
            continue

        if clip is None:
            continue

        # Apply color grading
        clip = apply_color_filter(clip, theme)
        shot_clips.append(clip)

    if not shot_clips:
        raise RuntimeError("No valid shots could be loaded — cannot build video.")

    _report(70, f"Loaded {len(shot_clips)} clips successfully")

    # --- Title card -------------------------------------------------------

    title_dur = 3.0
    _report(72, "Creating title card...")
    title_card = _create_title_card(edl.title, theme, title_dur, resolution, fps)
    title_card = apply_color_filter(title_card, theme)

    # --- Closing card -----------------------------------------------------

    closing_dur = 2.0
    _report(75, "Creating closing card...")
    closing_card = _create_closing_card(theme, closing_dur, resolution, fps, title=edl.title)

    all_clips = [title_card] + shot_clips + [closing_card]

    # --- Transitions ------------------------------------------------------

    _report(78, f"Applying transitions ({theme.transition_type})...")

    if theme.transition_type == "fade_black":
        # For fade-through-black, apply fades and concatenate sequentially
        processed = _apply_transitions(all_clips, "fade_black", transition_dur)
        final_video = concatenate_videoclips(processed, padding=-transition_dur)
    else:
        # crossfade / slide_left (MVP fallback)
        processed = _apply_transitions(all_clips, theme.transition_type, transition_dur)
        final_video = CompositeVideoClip(processed, size=resolution)

    _print_progress(f"Video duration: {final_video.duration:.1f}s")

    # --- Text overlays ----------------------------------------------------

    if text_elements:
        _report(80, "Adding text overlays...")
        text_clips = []
        for te in text_elements:
            overlay = _create_text_overlay(te, theme, resolution, fps)
            if overlay is not None:
                position = te.get("position", 0.0)
                overlay = overlay.with_start(position)
                text_clips.append(overlay)

        if text_clips:
            # Composite text overlays on top of the main video
            final_video = CompositeVideoClip(
                [final_video] + text_clips,
                size=resolution,
            ).with_duration(final_video.duration)

    # --- Music ------------------------------------------------------------

    if music_path is not None:
        _report(82, "Adding background music...")
        music = _prepare_music(music_path, final_video.duration)
        if music is not None:
            if final_video.audio is not None:
                from moviepy import CompositeAudioClip

                final_video = final_video.with_audio(
                    CompositeAudioClip([final_video.audio, music])
                )
            else:
                final_video = final_video.with_audio(music)

    # --- Export ------------------------------------------------------------

    if output_path is None:
        safe_title = "".join(
            c if c.isalnum() or c in " _-" else "_" for c in edl.title
        ).strip()
        output_path = str(config.OUTPUT_DIR / f"{safe_title}.mp4")

    _report(85, f"Encoding video to {Path(output_path).name}...")
    try:
        final_video.write_videofile(
            output_path,
            fps=fps,
            codec="libx264",
            audio_codec="aac",
            preset="medium",
            logger="bar",
        )
    finally:
        # Cleanup: close all clips to release file handles
        final_video.close()
        for clip in shot_clips:
            try:
                clip.close()
            except Exception:
                pass
        try:
            title_card.close()
        except Exception:
            pass
        try:
            closing_card.close()
        except Exception:
            pass

    _print_progress(f"Done! Video saved to {output_path}")
    return output_path
