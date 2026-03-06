"""Main video assembly pipeline.

Takes an EditDecisionList from the curation layer and assembles a final
video using moviepy 2.x, applying themes, transitions, title cards, and
optional background music.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

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


def _print_progress(msg: str) -> None:
    """Print a timestamped progress message."""
    print(f"[assemble] {msg}")


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
        if theme.ken_burns_enabled:
            clip = apply_ken_burns(shot.path, duration, fps, resolution)
        else:
            # Static clip — letterbox/pillarbox to maintain aspect ratio
            fitted_array = fit_to_resolution(shot.path, resolution, theme.bg_color)
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
        raw_clip = VideoFileClip(shot.path)
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
) -> CompositeVideoClip:
    """Create a closing card — a solid bg_color clip with a fade-out effect."""
    from assemble.themes import _hex_to_rgb

    bg_rgb = _hex_to_rgb(theme.bg_color)

    bg = (
        ColorClip(size=resolution, color=bg_rgb)
        .with_duration(duration)
        .with_fps(fps)
    )

    closing_card = CompositeVideoClip([bg], size=resolution).with_duration(duration)
    closing_card = closing_card.with_effects([vfx.CrossFadeOut(min(1.0, duration))])
    return closing_card


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
) -> str:
    """Assemble a final video from an EditDecisionList.

    Args:
        edl: The edit decision list produced by the curation layer.
        theme_name: Name of the visual theme to apply.
        music_path: Optional path to a background music file.
        output_path: Where to write the final MP4. Defaults to
            ``config.OUTPUT_DIR / "{edl.title}.mp4"``.

    Returns:
        The absolute path to the rendered video file as a string.
    """
    theme = get_theme(theme_name)
    fps = config.DEFAULT_OUTPUT_FPS
    resolution = config.DEFAULT_OUTPUT_RESOLUTION
    transition_dur = config.DEFAULT_TRANSITION_DURATION

    _print_progress(f"Theme: {theme.name}")
    _print_progress(f"Resolution: {resolution[0]}x{resolution[1]} @ {fps}fps")
    _print_progress(f"Shots to process: {len(edl.shots)}")

    # --- Build individual clips -------------------------------------------

    shot_clips: list = []
    for i, shot in enumerate(edl.shots):
        _print_progress(
            f"Processing shot {i + 1}/{len(edl.shots)}: "
            f"{shot.media_type} — {shot.role} — {Path(shot.path).name}"
        )
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

    _print_progress(f"Loaded {len(shot_clips)} clips successfully")

    # --- Title card -------------------------------------------------------

    title_dur = 3.0
    _print_progress("Creating title card...")
    title_card = _create_title_card(edl.title, theme, title_dur, resolution, fps)
    title_card = apply_color_filter(title_card, theme)

    # --- Closing card -----------------------------------------------------

    closing_dur = 2.0
    _print_progress("Creating closing card...")
    closing_card = _create_closing_card(theme, closing_dur, resolution, fps)

    all_clips = [title_card] + shot_clips + [closing_card]

    # --- Transitions ------------------------------------------------------

    _print_progress(f"Applying transitions ({theme.transition_type})...")

    if theme.transition_type == "fade_black":
        # For fade-through-black, apply fades and concatenate sequentially
        processed = _apply_transitions(all_clips, "fade_black", transition_dur)
        final_video = concatenate_videoclips(processed, padding=-transition_dur)
    else:
        # crossfade / slide_left (MVP fallback)
        processed = _apply_transitions(all_clips, theme.transition_type, transition_dur)
        final_video = CompositeVideoClip(processed, size=resolution)

    _print_progress(f"Video duration: {final_video.duration:.1f}s")

    # --- Music ------------------------------------------------------------

    if music_path is not None:
        _print_progress("Adding background music...")
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

    _print_progress(f"Rendering to {output_path}...")
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
