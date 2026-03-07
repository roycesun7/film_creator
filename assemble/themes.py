"""Visual themes and image effects for video assembly."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
from moviepy import ColorClip, CompositeVideoClip, ImageClip, VideoClip
from PIL import Image


@dataclass
class Theme:
    """Visual theme controlling the look and feel of an assembled video."""

    name: str
    font: str
    font_size: int
    font_color: str  # hex, e.g. "#FFFFFF"
    bg_color: str  # hex, e.g. "#000000"
    transition_type: str  # "crossfade", "fade_black", "slide_left"
    title_position: str  # "center", "bottom_left"
    color_filter: Optional[Callable] = field(default=None, repr=False)
    ken_burns_enabled: bool = True
    resolution_override: Optional[tuple[int, int]] = None


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert a hex color string to an (R, G, B) tuple."""
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


# ---------------------------------------------------------------------------
# Aspect-ratio-safe resize helpers
# ---------------------------------------------------------------------------

def fit_to_resolution(image_path_or_clip, resolution: tuple[int, int], bg_color: str = "#000000"):
    """Resize content to fit within *resolution* while maintaining aspect ratio.

    For images (str path): opens with PIL, computes the scale to fit within
    *resolution*, pastes onto a background-coloured canvas of the target size,
    and returns a numpy array (H, W, 3).

    For moviepy clips: resizes while maintaining aspect ratio, then composites
    over a :class:`ColorClip` background of the target resolution. Returns a
    new :class:`CompositeVideoClip`.

    Args:
        image_path_or_clip: Either a file-system path (str) to an image or a
            moviepy video/image clip.
        resolution: ``(width, height)`` target resolution.
        bg_color: Hex colour string for the background (letterbox/pillarbox).

    Returns:
        numpy array for image paths, or CompositeVideoClip for clip inputs.
    """
    target_w, target_h = resolution
    bg_rgb = _hex_to_rgb(bg_color)

    if isinstance(image_path_or_clip, str):
        # --- Image path --------------------------------------------------
        img = Image.open(image_path_or_clip).convert("RGB")
        src_w, src_h = img.size

        scale = min(target_w / src_w, target_h / src_h)
        new_w = int(src_w * scale)
        new_h = int(src_h * scale)

        img = img.resize((new_w, new_h), Image.LANCZOS)

        canvas = Image.new("RGB", (target_w, target_h), color=bg_rgb)
        paste_x = (target_w - new_w) // 2
        paste_y = (target_h - new_h) // 2
        canvas.paste(img, (paste_x, paste_y))
        return np.array(canvas)

    # --- moviepy clip ----------------------------------------------------
    clip = image_path_or_clip
    src_w, src_h = clip.size

    scale = min(target_w / src_w, target_h / src_h)
    new_size = (int(src_w * scale), int(src_h * scale))

    resized_clip = clip.resized(new_size)

    bg = (
        ColorClip(size=resolution, color=bg_rgb)
        .with_duration(clip.duration)
        .with_fps(getattr(clip, "fps", 24))
    )
    composite = CompositeVideoClip(
        [bg, resized_clip.with_position("center")],
        size=resolution,
    ).with_duration(clip.duration)
    return composite


# ---------------------------------------------------------------------------
# Color filter functions
# ---------------------------------------------------------------------------

def _warm_filter(frame: np.ndarray) -> np.ndarray:
    """Apply a warm tone: boost reds/greens slightly, reduce blues."""
    result = frame.astype(np.float32)
    result[:, :, 0] = np.minimum(result[:, :, 0] * 1.08, 255)  # red
    result[:, :, 1] = np.minimum(result[:, :, 1] * 1.04, 255)  # green
    result[:, :, 2] = result[:, :, 2] * 0.92                    # blue
    return result.astype(np.uint8)


def _warm_color_filter(clip):
    """Apply warm nostalgic color grading to a moviepy clip."""
    return clip.image_transform(_warm_filter)


def _cinematic_filter(frame: np.ndarray) -> np.ndarray:
    """Slight desaturation + warm tint for a cinematic look."""
    result = frame.astype(np.float32)
    # Desaturate by 15%: blend each channel toward the luminance
    gray = 0.2989 * result[:, :, 0] + 0.5870 * result[:, :, 1] + 0.1140 * result[:, :, 2]
    factor = 0.85  # keep 85% of colour (15% desaturation)
    result[:, :, 0] = result[:, :, 0] * factor + gray * (1 - factor)
    result[:, :, 1] = result[:, :, 1] * factor + gray * (1 - factor)
    result[:, :, 2] = result[:, :, 2] * factor + gray * (1 - factor)
    # Warm tint: slight red/green boost, blue reduction
    result[:, :, 0] = np.minimum(result[:, :, 0] * 1.06, 255)  # red
    result[:, :, 1] = np.minimum(result[:, :, 1] * 1.02, 255)  # green
    result[:, :, 2] = result[:, :, 2] * 0.94                    # blue
    return result.astype(np.uint8)


def _cinematic_color_filter(clip):
    """Apply cinematic desaturation + warm tint to a moviepy clip."""
    return clip.image_transform(_cinematic_filter)


# ---------------------------------------------------------------------------
# Preset themes
# ---------------------------------------------------------------------------

MINIMAL = Theme(
    name="minimal",
    font="Helvetica",
    font_size=48,
    font_color="#FFFFFF",
    bg_color="#000000",
    transition_type="crossfade",
    title_position="center",
    color_filter=None,
    ken_burns_enabled=True,
)

WARM_NOSTALGIC = Theme(
    name="warm_nostalgic",
    font="Georgia",
    font_size=44,
    font_color="#FFF8E7",
    bg_color="#1A0A00",
    transition_type="fade_black",
    title_position="center",
    color_filter=_warm_color_filter,
    ken_burns_enabled=True,
)

BOLD_MODERN = Theme(
    name="bold_modern",
    font="Helvetica-Bold",
    font_size=72,
    font_color="#FFFFFF",
    bg_color="#0D0D0D",
    transition_type="slide_left",
    title_position="bottom_left",
    color_filter=None,
    ken_burns_enabled=False,
)

CINEMATIC = Theme(
    name="cinematic",
    font="Georgia",
    font_size=56,
    font_color="#E8E0D0",
    bg_color="#0A0A0A",
    transition_type="crossfade",
    title_position="center",
    color_filter=_cinematic_color_filter,
    ken_burns_enabled=True,
)

DOCUMENTARY = Theme(
    name="documentary",
    font="Helvetica",
    font_size=40,
    font_color="#FFFFFF",
    bg_color="#1A1A2E",
    transition_type="fade_black",
    title_position="center",
    color_filter=None,
    ken_burns_enabled=True,
)

SOCIAL_VERTICAL = Theme(
    name="social_vertical",
    font="Helvetica-Bold",
    font_size=64,
    font_color="#FFFFFF",
    bg_color="#000000",
    transition_type="crossfade",
    title_position="center",
    color_filter=None,
    ken_burns_enabled=True,
    resolution_override=(1080, 1920),
)

_THEMES: dict[str, Theme] = {
    "minimal": MINIMAL,
    "warm_nostalgic": WARM_NOSTALGIC,
    "bold_modern": BOLD_MODERN,
    "cinematic": CINEMATIC,
    "documentary": DOCUMENTARY,
    "social_vertical": SOCIAL_VERTICAL,
}


def get_theme(name: str) -> Theme:
    """Return a theme by name. Falls back to MINIMAL if not found."""
    return _THEMES.get(name.lower(), MINIMAL)


# ---------------------------------------------------------------------------
# Ken Burns effect
# ---------------------------------------------------------------------------

def apply_ken_burns(
    image_path: str,
    duration: float,
    fps: int,
    resolution: tuple[int, int],
) -> VideoClip:
    """Create a video clip from a still image with a Ken Burns zoom + pan.

    Randomly chooses a motion style:
    - Zoom in (center focus)
    - Zoom out (center focus)
    - Zoom in with pan (drift from one region to another)

    The zoom range is gentle (1.0x to 1.15x) to keep the effect subtle.

    Args:
        image_path: Path to the source image file.
        duration: Duration of the resulting clip in seconds.
        fps: Frames per second for the output clip.
        resolution: (width, height) target resolution.

    Returns:
        A moviepy VideoClip with the Ken Burns effect applied.
    """
    target_w, target_h = resolution

    img = Image.open(image_path).convert("RGB")
    # Work at a higher resolution to allow cropping during zoom + pan
    scale_factor = 1.4
    work_w = int(target_w * scale_factor)
    work_h = int(target_h * scale_factor)
    img = img.resize((work_w, work_h), Image.LANCZOS)
    img_array = np.array(img)

    # Choose motion style
    style = random.choice(["zoom_in", "zoom_out", "pan_zoom"])
    zoom_start = 1.0
    zoom_end = 1.15

    # Pan parameters — slight drift from start to end offset
    max_pan = int(work_w * 0.08)  # max pan distance as fraction of image
    if style == "pan_zoom":
        pan_start_x = random.randint(-max_pan, max_pan)
        pan_start_y = random.randint(-max_pan // 2, max_pan // 2)
        pan_end_x = random.randint(-max_pan, max_pan)
        pan_end_y = random.randint(-max_pan // 2, max_pan // 2)
    else:
        pan_start_x = pan_start_y = pan_end_x = pan_end_y = 0

    def make_frame(t: float) -> np.ndarray:
        progress = t / duration if duration > 0 else 0.0
        # Ease-in-out for smoother motion
        progress = 0.5 - 0.5 * np.cos(np.pi * progress)

        if style == "zoom_out":
            zoom = zoom_end - (zoom_end - zoom_start) * progress
        else:  # zoom_in or pan_zoom
            zoom = zoom_start + (zoom_end - zoom_start) * progress

        # Compute the crop box for this zoom level
        crop_w = int(target_w / zoom)
        crop_h = int(target_h / zoom)

        # Pan interpolation
        pan_x = int(pan_start_x + (pan_end_x - pan_start_x) * progress)
        pan_y = int(pan_start_y + (pan_end_y - pan_start_y) * progress)

        # Center crop on the working image with pan offset
        cx = work_w // 2 + pan_x
        cy = work_h // 2 + pan_y
        x1 = max(cx - crop_w // 2, 0)
        y1 = max(cy - crop_h // 2, 0)
        x2 = min(x1 + crop_w, work_w)
        y2 = min(y1 + crop_h, work_h)

        # Ensure we don't crop outside bounds
        if x2 - x1 < crop_w:
            x1 = max(0, x2 - crop_w)
        if y2 - y1 < crop_h:
            y1 = max(0, y2 - crop_h)

        cropped = img_array[y1:y2, x1:x2]

        # Resize cropped region to target resolution
        pil_crop = Image.fromarray(cropped)
        pil_crop = pil_crop.resize((target_w, target_h), Image.LANCZOS)
        return np.array(pil_crop)

    clip = VideoClip(make_frame, duration=duration).with_fps(fps)
    return clip


# ---------------------------------------------------------------------------
# Color filter application
# ---------------------------------------------------------------------------

def apply_color_filter(clip, theme: Theme):
    """Apply the theme's color filter to a clip, if one is defined.

    Args:
        clip: A moviepy video clip.
        theme: The Theme whose color_filter should be applied.

    Returns:
        The clip with the color filter applied, or the original clip
        if no filter is defined.
    """
    if theme.color_filter is not None:
        return theme.color_filter(clip)
    return clip
