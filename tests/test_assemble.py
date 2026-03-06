"""Tests for the assembly layer: themes.py and builder.py."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

# Ensure project root is on sys.path so `config` and `assemble` are importable.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from assemble.themes import (
    BOLD_MODERN,
    MINIMAL,
    WARM_NOSTALGIC,
    Theme,
    _hex_to_rgb,
    _warm_filter,
    apply_color_filter,
    apply_ken_burns,
    get_theme,
)
from assemble.builder import (
    _apply_transitions,
    _create_title_card,
    _prepare_photo_clip,
    _prepare_video_clip,
    build_video,
)
from curate.director import EditDecisionList, Shot


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def tmp_dir(tmp_path):
    """Return a temporary directory path."""
    return tmp_path


@pytest.fixture
def red_image_path(tmp_path):
    """Create a small 100x100 red JPEG and return its path."""
    path = tmp_path / "red.jpg"
    img = Image.new("RGB", (100, 100), color=(255, 0, 0))
    img.save(str(path))
    return str(path)


@pytest.fixture
def green_image_path(tmp_path):
    """Create a small 100x100 green JPEG and return its path."""
    path = tmp_path / "green.jpg"
    img = Image.new("RGB", (100, 100), color=(0, 255, 0))
    img.save(str(path))
    return str(path)


@pytest.fixture
def blue_image_path(tmp_path):
    """Create a small 100x100 blue JPEG and return its path."""
    path = tmp_path / "blue.jpg"
    img = Image.new("RGB", (100, 100), color=(0, 0, 255))
    img.save(str(path))
    return str(path)


@pytest.fixture
def short_audio_path(tmp_path):
    """Create a short sine wave WAV file (0.5 seconds) and return its path."""
    import wave
    import struct

    path = tmp_path / "tone.wav"
    sample_rate = 44100
    duration = 0.5
    frequency = 440.0
    n_samples = int(sample_rate * duration)

    samples = []
    for i in range(n_samples):
        t = i / sample_rate
        value = int(32767 * 0.5 * np.sin(2 * np.pi * frequency * t))
        samples.append(struct.pack("<h", value))

    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"".join(samples))

    return str(path)


def _make_shot(path: str, media_type: str = "photo", role: str = "highlight") -> Shot:
    """Helper to create a Shot dataclass for testing."""
    return Shot(
        uuid="test-uuid",
        path=path,
        media_type=media_type,
        start_time=0.0,
        end_time=3.0,
        role=role,
        reason="test",
    )


# Use small resolution for fast tests
TEST_RES = (160, 90)
TEST_FPS = 10


# ===========================================================================
# themes.py tests
# ===========================================================================

class TestThemeDataclass:
    """Test Theme dataclass instantiation."""

    def test_theme_instantiation_all_fields(self):
        theme = Theme(
            name="test",
            font="Arial",
            font_size=36,
            font_color="#AABBCC",
            bg_color="#112233",
            transition_type="crossfade",
            title_position="center",
            color_filter=None,
            ken_burns_enabled=False,
        )
        assert theme.name == "test"
        assert theme.font == "Arial"
        assert theme.font_size == 36
        assert theme.font_color == "#AABBCC"
        assert theme.bg_color == "#112233"
        assert theme.transition_type == "crossfade"
        assert theme.title_position == "center"
        assert theme.color_filter is None
        assert theme.ken_burns_enabled is False

    def test_theme_default_color_filter_is_none(self):
        theme = Theme(
            name="x",
            font="x",
            font_size=10,
            font_color="#000000",
            bg_color="#000000",
            transition_type="crossfade",
            title_position="center",
        )
        assert theme.color_filter is None
        assert theme.ken_burns_enabled is True  # default


class TestGetTheme:
    """Test get_theme lookup."""

    def test_returns_minimal(self):
        assert get_theme("minimal") is MINIMAL

    def test_returns_warm_nostalgic(self):
        assert get_theme("warm_nostalgic") is WARM_NOSTALGIC

    def test_returns_bold_modern(self):
        assert get_theme("bold_modern") is BOLD_MODERN

    def test_case_insensitive(self):
        assert get_theme("MINIMAL") is MINIMAL
        assert get_theme("Warm_Nostalgic") is WARM_NOSTALGIC
        assert get_theme("BOLD_MODERN") is BOLD_MODERN

    def test_unknown_name_returns_minimal(self):
        assert get_theme("nonexistent_theme") is MINIMAL
        assert get_theme("") is MINIMAL
        assert get_theme("foobar") is MINIMAL


class TestHexToRgb:
    """Test _hex_to_rgb conversion."""

    def test_white(self):
        assert _hex_to_rgb("#FFFFFF") == (255, 255, 255)

    def test_black(self):
        assert _hex_to_rgb("#000000") == (0, 0, 0)

    def test_red(self):
        assert _hex_to_rgb("#FF0000") == (255, 0, 0)

    def test_arbitrary_color(self):
        assert _hex_to_rgb("#1A2B3C") == (26, 43, 60)

    def test_without_hash(self):
        # The function lstrips '#', so a string without it should also work
        assert _hex_to_rgb("AABB00") == (170, 187, 0)

    def test_lowercase_hex(self):
        assert _hex_to_rgb("#aabbcc") == (170, 187, 204)


class TestWarmFilter:
    """Test _warm_filter pixel modification."""

    def test_boosts_red_and_green_reduces_blue(self):
        # Create a frame with known values
        frame = np.full((2, 2, 3), 100, dtype=np.uint8)
        result = _warm_filter(frame)

        # Red channel: 100 * 1.08 = 108
        assert result[0, 0, 0] == 108
        # Green channel: 100 * 1.04 = 104
        assert result[0, 0, 1] == 104
        # Blue channel: 100 * 0.92 = 92
        assert result[0, 0, 2] == 92

    def test_red_clipped_at_255(self):
        # If red is already near max, should clip at 255
        frame = np.full((1, 1, 3), 250, dtype=np.uint8)
        result = _warm_filter(frame)
        assert result[0, 0, 0] == 255  # 250 * 1.08 = 270, clipped to 255

    def test_green_clipped_at_255(self):
        frame = np.full((1, 1, 3), 250, dtype=np.uint8)
        result = _warm_filter(frame)
        assert result[0, 0, 1] == 255  # 250 * 1.04 = 260, clipped to 255

    def test_output_dtype_is_uint8(self):
        frame = np.full((3, 3, 3), 128, dtype=np.uint8)
        result = _warm_filter(frame)
        assert result.dtype == np.uint8

    def test_shape_preserved(self):
        frame = np.zeros((10, 15, 3), dtype=np.uint8)
        result = _warm_filter(frame)
        assert result.shape == (10, 15, 3)


class TestApplyKenBurns:
    """Test apply_ken_burns produces correct clips."""

    def test_returns_clip_with_correct_duration(self, red_image_path):
        clip = apply_ken_burns(red_image_path, duration=2.0, fps=TEST_FPS, resolution=TEST_RES)
        assert abs(clip.duration - 2.0) < 0.01

    def test_returns_clip_with_correct_resolution(self, red_image_path):
        clip = apply_ken_burns(red_image_path, duration=1.0, fps=TEST_FPS, resolution=TEST_RES)
        frame = clip.get_frame(0)
        assert frame.shape[1] == TEST_RES[0]  # width
        assert frame.shape[0] == TEST_RES[1]  # height

    def test_frame_values_are_valid(self, red_image_path):
        clip = apply_ken_burns(red_image_path, duration=1.0, fps=TEST_FPS, resolution=TEST_RES)
        frame = clip.get_frame(0.5)
        assert frame.min() >= 0
        assert frame.max() <= 255


class TestApplyColorFilter:
    """Test apply_color_filter."""

    def test_applies_filter_when_defined(self, red_image_path):
        from moviepy import ImageClip

        clip = ImageClip(red_image_path).with_duration(1.0)
        theme = WARM_NOSTALGIC  # has a color filter
        result = apply_color_filter(clip, theme)
        # Result should be different from input because filter was applied
        assert result is not clip

    def test_passthrough_when_no_filter(self, red_image_path):
        from moviepy import ImageClip

        clip = ImageClip(red_image_path).with_duration(1.0)
        theme = MINIMAL  # color_filter is None
        result = apply_color_filter(clip, theme)
        assert result is clip


class TestPresetThemes:
    """Verify that preset themes have the expected field values."""

    def test_minimal_fields(self):
        assert MINIMAL.name == "minimal"
        assert MINIMAL.font == "Helvetica"
        assert MINIMAL.font_size == 48
        assert MINIMAL.font_color == "#FFFFFF"
        assert MINIMAL.bg_color == "#000000"
        assert MINIMAL.transition_type == "crossfade"
        assert MINIMAL.title_position == "center"
        assert MINIMAL.color_filter is None
        assert MINIMAL.ken_burns_enabled is True

    def test_warm_nostalgic_fields(self):
        assert WARM_NOSTALGIC.name == "warm_nostalgic"
        assert WARM_NOSTALGIC.font == "Georgia"
        assert WARM_NOSTALGIC.font_size == 44
        assert WARM_NOSTALGIC.font_color == "#FFF8E7"
        assert WARM_NOSTALGIC.bg_color == "#1A0A00"
        assert WARM_NOSTALGIC.transition_type == "fade_black"
        assert WARM_NOSTALGIC.title_position == "center"
        assert WARM_NOSTALGIC.color_filter is not None
        assert WARM_NOSTALGIC.ken_burns_enabled is True

    def test_bold_modern_fields(self):
        assert BOLD_MODERN.name == "bold_modern"
        assert BOLD_MODERN.font == "Helvetica-Bold"
        assert BOLD_MODERN.font_size == 72
        assert BOLD_MODERN.font_color == "#FFFFFF"
        assert BOLD_MODERN.bg_color == "#0D0D0D"
        assert BOLD_MODERN.transition_type == "slide_left"
        assert BOLD_MODERN.title_position == "bottom_left"
        assert BOLD_MODERN.color_filter is None
        assert BOLD_MODERN.ken_burns_enabled is False


# ===========================================================================
# builder.py tests
# ===========================================================================

class TestPreparePhotoClip:
    """Test _prepare_photo_clip."""

    def test_returns_clip_with_correct_duration(self, red_image_path):
        shot = _make_shot(red_image_path, media_type="photo")
        clip = _prepare_photo_clip(shot, MINIMAL, TEST_RES, TEST_FPS)
        assert clip is not None
        # DEFAULT_PHOTO_DURATION is 3.0
        assert abs(clip.duration - 3.0) < 0.01

    def test_returns_none_for_nonexistent_file(self):
        shot = _make_shot("/nonexistent/path/image.jpg", media_type="photo")
        clip = _prepare_photo_clip(shot, MINIMAL, TEST_RES, TEST_FPS)
        assert clip is None

    def test_with_ken_burns_disabled(self, red_image_path):
        shot = _make_shot(red_image_path, media_type="photo")
        clip = _prepare_photo_clip(shot, BOLD_MODERN, TEST_RES, TEST_FPS)
        assert clip is not None
        assert abs(clip.duration - 3.0) < 0.01


class TestPrepareVideoClip:
    """Test _prepare_video_clip."""

    def test_returns_none_for_nonexistent_file(self):
        shot = _make_shot("/nonexistent/video.mp4", media_type="video")
        clip = _prepare_video_clip(shot, TEST_RES, TEST_FPS)
        assert clip is None


class TestCreateTitleCard:
    """Test _create_title_card."""

    def test_returns_composite_with_correct_duration(self):
        from moviepy import CompositeVideoClip

        card = _create_title_card("Test Title", MINIMAL, 3.0, TEST_RES, TEST_FPS)
        assert isinstance(card, CompositeVideoClip)
        assert abs(card.duration - 3.0) < 0.01

    def test_short_duration(self):
        card = _create_title_card("Short", MINIMAL, 0.5, TEST_RES, TEST_FPS)
        assert abs(card.duration - 0.5) < 0.01


class TestApplyTransitions:
    """Test _apply_transitions."""

    def _make_clips(self, n=3, dur=2.0):
        """Create n simple color clips for testing."""
        from moviepy import ColorClip

        clips = []
        for i in range(n):
            c = ColorClip(size=TEST_RES, color=(i * 80, 50, 50)).with_duration(dur).with_fps(TEST_FPS)
            clips.append(c)
        return clips

    def test_crossfade_overlapping_start_times(self):
        clips = self._make_clips(3, dur=2.0)
        result = _apply_transitions(clips, "crossfade", 0.5)
        assert len(result) == 3
        # First clip starts at 0
        assert result[0].start == 0.0
        # Second clip should start at (first.duration - transition_dur) = 1.5
        assert abs(result[1].start - 1.5) < 0.01
        # Third clip should start at 1.5 + (2.0 - 0.5) = 3.0
        assert abs(result[2].start - 3.0) < 0.01

    def test_fade_black_applies_effects(self):
        clips = self._make_clips(2, dur=2.0)
        result = _apply_transitions(clips, "fade_black", 0.5)
        assert len(result) == 2
        # CrossFadeIn/CrossFadeOut in moviepy 2.x work through the clip mask.
        # Verify that each clip has a mask with fade-in at start and fade-out at end.
        for clip in result:
            assert clip.mask is not None, "Clip should have a mask after fade effects"
            mask_start = clip.mask.get_frame(0.0).mean()
            mask_mid = clip.mask.get_frame(clip.duration / 2).mean()
            mask_end = clip.mask.get_frame(clip.duration - 0.01).mean()
            # At t=0 mask should be ~0 (faded in from black)
            assert mask_start < 0.1
            # At midpoint mask should be ~1 (fully visible)
            assert mask_mid > 0.9
            # Near end mask should be small (fading out to black)
            assert mask_end < 0.1

    def test_empty_list(self):
        result = _apply_transitions([], "crossfade", 0.5)
        assert result == []

    def test_single_clip(self):
        clips = self._make_clips(1, dur=2.0)
        result = _apply_transitions(clips, "crossfade", 0.5)
        assert len(result) == 1
        assert result[0].start == 0.0

    def test_slide_left_falls_back_to_crossfade(self):
        clips = self._make_clips(2, dur=2.0)
        result = _apply_transitions(clips, "slide_left", 0.5)
        assert len(result) == 2
        # Should behave like crossfade
        assert result[0].start == 0.0
        assert abs(result[1].start - 1.5) < 0.01


class TestBuildVideoEndToEnd:
    """End-to-end tests for build_video."""

    def test_build_video_creates_output_file(self, red_image_path, green_image_path, blue_image_path, tmp_path):
        """Build a video from test images and verify the output exists."""
        shots = [
            Shot(uuid="1", path=red_image_path, media_type="photo",
                 start_time=0.0, end_time=3.0, role="opener", reason="test"),
            Shot(uuid="2", path=green_image_path, media_type="photo",
                 start_time=0.0, end_time=3.0, role="highlight", reason="test"),
            Shot(uuid="3", path=blue_image_path, media_type="photo",
                 start_time=0.0, end_time=3.0, role="closer", reason="test"),
        ]
        edl = EditDecisionList(
            shots=shots,
            title="Test Video",
            narrative_summary="A test video.",
            estimated_duration=9.0,
            music_mood="calm",
        )

        output_path = str(tmp_path / "test_output.mp4")

        # Monkey-patch config to use small resolution and low fps for speed
        import config as cfg
        orig_res = cfg.DEFAULT_OUTPUT_RESOLUTION
        orig_fps = cfg.DEFAULT_OUTPUT_FPS
        orig_photo_dur = cfg.DEFAULT_PHOTO_DURATION
        orig_trans_dur = cfg.DEFAULT_TRANSITION_DURATION
        try:
            cfg.DEFAULT_OUTPUT_RESOLUTION = TEST_RES
            cfg.DEFAULT_OUTPUT_FPS = TEST_FPS
            cfg.DEFAULT_PHOTO_DURATION = 1.0  # shorter for fast tests
            cfg.DEFAULT_TRANSITION_DURATION = 0.3

            result = build_video(edl, theme_name="minimal", output_path=output_path)
        finally:
            cfg.DEFAULT_OUTPUT_RESOLUTION = orig_res
            cfg.DEFAULT_OUTPUT_FPS = orig_fps
            cfg.DEFAULT_PHOTO_DURATION = orig_photo_dur
            cfg.DEFAULT_TRANSITION_DURATION = orig_trans_dur

        assert os.path.exists(result)
        assert os.path.getsize(result) > 0

    def test_build_video_raises_when_all_shots_fail(self, tmp_path):
        """When all shot paths are invalid, build_video should raise RuntimeError."""
        shots = [
            Shot(uuid="bad1", path="/nonexistent/a.jpg", media_type="photo",
                 start_time=0.0, end_time=3.0, role="opener", reason="test"),
            Shot(uuid="bad2", path="/nonexistent/b.jpg", media_type="photo",
                 start_time=0.0, end_time=3.0, role="closer", reason="test"),
        ]
        edl = EditDecisionList(
            shots=shots,
            title="Fail Video",
            narrative_summary="Should fail.",
            estimated_duration=6.0,
            music_mood="calm",
        )

        import config as cfg
        orig_res = cfg.DEFAULT_OUTPUT_RESOLUTION
        orig_fps = cfg.DEFAULT_OUTPUT_FPS
        try:
            cfg.DEFAULT_OUTPUT_RESOLUTION = TEST_RES
            cfg.DEFAULT_OUTPUT_FPS = TEST_FPS

            with pytest.raises(RuntimeError, match="No valid shots"):
                build_video(edl, theme_name="minimal", output_path=str(tmp_path / "fail.mp4"))
        finally:
            cfg.DEFAULT_OUTPUT_RESOLUTION = orig_res
            cfg.DEFAULT_OUTPUT_FPS = orig_fps

    def test_build_video_with_music(self, red_image_path, short_audio_path, tmp_path):
        """Build a video with background music and verify output exists."""
        shots = [
            Shot(uuid="1", path=red_image_path, media_type="photo",
                 start_time=0.0, end_time=3.0, role="opener", reason="test"),
        ]
        edl = EditDecisionList(
            shots=shots,
            title="Music Test",
            narrative_summary="Test with music.",
            estimated_duration=3.0,
            music_mood="calm",
        )

        output_path = str(tmp_path / "music_test.mp4")

        import config as cfg
        orig_res = cfg.DEFAULT_OUTPUT_RESOLUTION
        orig_fps = cfg.DEFAULT_OUTPUT_FPS
        orig_photo_dur = cfg.DEFAULT_PHOTO_DURATION
        orig_trans_dur = cfg.DEFAULT_TRANSITION_DURATION
        try:
            cfg.DEFAULT_OUTPUT_RESOLUTION = TEST_RES
            cfg.DEFAULT_OUTPUT_FPS = TEST_FPS
            cfg.DEFAULT_PHOTO_DURATION = 1.0
            cfg.DEFAULT_TRANSITION_DURATION = 0.3

            result = build_video(
                edl,
                theme_name="minimal",
                music_path=short_audio_path,
                output_path=output_path,
            )
        finally:
            cfg.DEFAULT_OUTPUT_RESOLUTION = orig_res
            cfg.DEFAULT_OUTPUT_FPS = orig_fps
            cfg.DEFAULT_PHOTO_DURATION = orig_photo_dur
            cfg.DEFAULT_TRANSITION_DURATION = orig_trans_dur

        assert os.path.exists(result)
        assert os.path.getsize(result) > 0
