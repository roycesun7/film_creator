#!/usr/bin/env python3
"""Runtime validation of the video assembly pipeline.

Creates real images, builds real EDLs, renders real videos, and verifies outputs.
"""

from __future__ import annotations

import os
import struct
import sys
import tempfile
import traceback
import wave

import numpy as np
from PIL import Image, ImageDraw

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config

# Override config for fast rendering BEFORE importing assemble modules
config.DEFAULT_OUTPUT_RESOLUTION = (320, 180)
config.DEFAULT_OUTPUT_FPS = 10
config.DEFAULT_PHOTO_DURATION = 2.0
config.DEFAULT_TRANSITION_DURATION = 0.3

from moviepy import VideoFileClip, ImageClip

from assemble.themes import (
    MINIMAL,
    WARM_NOSTALGIC,
    BOLD_MODERN,
    Theme,
    apply_ken_burns,
    fit_to_resolution,
    apply_color_filter,
    get_theme,
)
from assemble.builder import (
    _create_title_card,
    _create_closing_card,
    build_video,
)
from curate.director import EditDecisionList, Shot

RESOLUTION = (320, 180)
FPS = 10


def print_section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def print_ok(msg: str) -> None:
    print(f"  [OK] {msg}")


# ===================================================================
# Step 1: Set up temp directory
# ===================================================================

tmpdir = tempfile.mkdtemp(prefix="vc_validate_")
print(f"Using temp directory: {tmpdir}")


# ===================================================================
# Step 2: Create diverse test images
# ===================================================================

print_section("Step 2: Creating diverse test images")

test_images = {}


def save_image(name: str, img: Image.Image) -> str:
    path = os.path.join(tmpdir, f"{name}.jpg")
    img.save(path, "JPEG")
    test_images[name] = path
    print_ok(f"Created {name}: {img.size}")
    return path


# 1920x1080 landscape (red gradient)
img = Image.new("RGB", (1920, 1080))
draw = ImageDraw.Draw(img)
for x in range(1920):
    r = int(255 * x / 1920)
    draw.line([(x, 0), (x, 1079)], fill=(r, 0, 0))
save_image("landscape_red", img)

# 1080x1920 portrait (blue gradient)
img = Image.new("RGB", (1080, 1920))
draw = ImageDraw.Draw(img)
for y in range(1920):
    b = int(255 * y / 1920)
    draw.line([(0, y), (1079, y)], fill=(0, 0, b))
save_image("portrait_blue", img)

# 500x500 square (green solid)
img = Image.new("RGB", (500, 500), color=(0, 200, 0))
save_image("square_green", img)

# 4000x2000 very large (yellow)
img = Image.new("RGB", (4000, 2000), color=(255, 255, 0))
save_image("large_yellow", img)

# 100x100 very small (purple)
img = Image.new("RGB", (100, 100), color=(128, 0, 128))
save_image("small_purple", img)

# 3000x1000 panoramic (orange gradient)
img = Image.new("RGB", (3000, 1000))
draw = ImageDraw.Draw(img)
for x in range(3000):
    r = 255
    g = int(165 * x / 3000)
    draw.line([(x, 0), (x, 999)], fill=(r, g, 0))
save_image("panoramic_orange", img)

print_ok(f"Created {len(test_images)} test images")


# ===================================================================
# Step 3: Test Ken Burns
# ===================================================================

print_section("Step 3: Testing Ken Burns effect")

for name, path in test_images.items():
    print(f"  Testing Ken Burns on {name}...")
    duration = 2.0
    clip = apply_ken_burns(path, duration, FPS, RESOLUTION)

    # Correct duration
    assert abs(clip.duration - duration) < 0.01, \
        f"Ken Burns duration mismatch for {name}: {clip.duration} vs {duration}"
    print_ok(f"{name}: duration correct ({clip.duration}s)")

    # Frame at t=0 has correct resolution
    frame0 = clip.get_frame(0)
    assert frame0.shape == (180, 320, 3), \
        f"Frame at t=0 wrong shape for {name}: {frame0.shape}"
    print_ok(f"{name}: frame at t=0 correct shape {frame0.shape}")

    # Frame at t=duration/2 has correct resolution
    frame_mid = clip.get_frame(duration / 2)
    assert frame_mid.shape == (180, 320, 3), \
        f"Frame at t=mid wrong shape for {name}: {frame_mid.shape}"
    print_ok(f"{name}: frame at t=mid correct shape")

    # Frames are valid (no NaN, values in 0-255)
    assert not np.isnan(frame0).any(), f"NaN in frame0 for {name}"
    assert not np.isnan(frame_mid).any(), f"NaN in frame_mid for {name}"
    assert frame0.min() >= 0 and frame0.max() <= 255, \
        f"Frame0 values out of range for {name}"
    assert frame_mid.min() >= 0 and frame_mid.max() <= 255, \
        f"Frame_mid values out of range for {name}"
    print_ok(f"{name}: frame values valid")

    # Clip can be closed without error
    clip.close()
    print_ok(f"{name}: clip closed successfully")

print_ok("All Ken Burns tests passed")


# ===================================================================
# Step 4: Test fit_to_resolution
# ===================================================================

print_section("Step 4: Testing fit_to_resolution")

for name, path in test_images.items():
    print(f"  Testing fit_to_resolution on {name}...")
    result = fit_to_resolution(path, RESOLUTION, "#000000")

    # Result should be a numpy array with target resolution
    assert isinstance(result, np.ndarray), \
        f"fit_to_resolution for {name} returned {type(result)}, expected ndarray"
    assert result.shape == (180, 320, 3), \
        f"fit_to_resolution for {name} wrong shape: {result.shape}"
    print_ok(f"{name}: output dimensions match target ({result.shape})")

# Verify portrait images get pillarboxed (black bars on sides)
portrait_result = fit_to_resolution(test_images["portrait_blue"], RESOLUTION, "#000000")
# For a portrait (1080x1920) fitted into 320x180, the image should be scaled
# to fit height: scale = 180/1920 = 0.09375, new_w = 1080*0.09375 = 101.25 => 101
# So there should be black bars on the sides
# Check left edge column is black
left_col = portrait_result[:, 0, :]
assert np.all(left_col == 0), "Portrait image should have black bars on left (pillarbox)"
# Check right edge column is black
right_col = portrait_result[:, -1, :]
assert np.all(right_col == 0), "Portrait image should have black bars on right (pillarbox)"
print_ok("Portrait images correctly pillarboxed")

# Verify landscape images fill correctly (no significant black bars on top/bottom for 16:9 source)
landscape_result = fit_to_resolution(test_images["landscape_red"], RESOLUTION, "#000000")
# 1920x1080 into 320x180 -- exactly 16:9, should fill perfectly
center_row = landscape_result[90, :, :]  # middle row
assert np.any(center_row > 0), "Landscape image should fill the frame"
print_ok("Landscape images fill correctly")

print_ok("All fit_to_resolution tests passed")


# ===================================================================
# Step 5: Test each theme
# ===================================================================

print_section("Step 5: Testing themes")

themes_to_test = {
    "minimal": MINIMAL,
    "warm_nostalgic": WARM_NOSTALGIC,
    "bold_modern": BOLD_MODERN,
}

for theme_name, theme in themes_to_test.items():
    print(f"  Testing theme: {theme_name}...")

    # Create title card
    title_card = _create_title_card("Test Title", theme, 2.0, RESOLUTION, FPS)
    frame = title_card.get_frame(0.5)
    assert frame.shape == (180, 320, 3), \
        f"Title card frame wrong shape for {theme_name}: {frame.shape}"
    assert not np.isnan(frame).any(), f"NaN in title card frame for {theme_name}"
    print_ok(f"{theme_name}: title card renders correctly")
    title_card.close()

    # Apply color filter to a test clip
    test_clip = ImageClip(test_images["landscape_red"]).with_duration(1.0).with_fps(FPS)
    filtered = apply_color_filter(test_clip, theme)
    filtered_frame = filtered.get_frame(0.5)
    assert filtered_frame.shape[0] > 0 and filtered_frame.shape[1] > 0, \
        f"Filtered frame has zero dimension for {theme_name}"
    assert not np.isnan(filtered_frame.astype(float)).any(), \
        f"NaN in filtered frame for {theme_name}"
    print_ok(f"{theme_name}: color filter applied successfully")
    test_clip.close()

print_ok("All theme tests passed")


# ===================================================================
# Step 6: Test full build_video with all 3 themes
# ===================================================================

print_section("Step 6: Testing full build_video with all 3 themes")

image_paths = list(test_images.values())

for theme_name in ["minimal", "warm_nostalgic", "bold_modern"]:
    print(f"  Building video with theme: {theme_name}...")

    shots = [
        Shot(uuid=f"s{i}", path=image_paths[i], media_type="photo",
             start_time=0.0, end_time=2.0, role="highlight", reason="test")
        for i in range(min(4, len(image_paths)))
    ]
    edl = EditDecisionList(
        shots=shots,
        title=f"Test {theme_name}",
        narrative_summary="Validation test video.",
        estimated_duration=8.0,
        music_mood="calm",
    )

    output_path = os.path.join(tmpdir, f"output_{theme_name}.mp4")
    result_path = build_video(edl, theme_name=theme_name, output_path=output_path)

    # Verify output exists
    assert os.path.exists(result_path), f"Output file does not exist: {result_path}"
    print_ok(f"{theme_name}: output file exists")

    # Verify file size > 0
    fsize = os.path.getsize(result_path)
    assert fsize > 0, f"Output file is empty: {result_path}"
    print_ok(f"{theme_name}: file size = {fsize} bytes")

    # Verify the file can be opened and has approximately expected duration
    verify_clip = VideoFileClip(result_path)
    # Expected: title(3s) + 4 shots(2s each) + closing(2s) - overlaps
    # For crossfade with 4+2 = 6 clips: 5 transitions * 0.3s = 1.5s overlap
    # Total ~ 3 + 4*2 + 2 - 1.5 = 11.5s (but varies by theme/transition type)
    # Just check it's reasonable (> 5s, < 30s)
    print(f"  {theme_name}: video duration = {verify_clip.duration:.1f}s")
    assert verify_clip.duration > 3.0, \
        f"Video too short for {theme_name}: {verify_clip.duration}s"
    assert verify_clip.duration < 30.0, \
        f"Video too long for {theme_name}: {verify_clip.duration}s"
    print_ok(f"{theme_name}: duration is reasonable ({verify_clip.duration:.1f}s)")
    verify_clip.close()

print_ok("All build_video theme tests passed")


# ===================================================================
# Step 7: Test build_video with music
# ===================================================================

print_section("Step 7: Testing build_video with music")

# Generate a simple sine wave WAV file (1 second, 440Hz)
audio_path = os.path.join(tmpdir, "test_tone.wav")
sample_rate = 44100
audio_duration = 1.0
frequency = 440.0
n_samples = int(sample_rate * audio_duration)

samples = []
for i in range(n_samples):
    t = i / sample_rate
    value = int(32767 * 0.5 * np.sin(2 * np.pi * frequency * t))
    samples.append(struct.pack("<h", value))

with wave.open(audio_path, "w") as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(sample_rate)
    wf.writeframes(b"".join(samples))

print_ok(f"Created test audio: {audio_path}")

shots = [
    Shot(uuid="m1", path=test_images["landscape_red"], media_type="photo",
         start_time=0.0, end_time=2.0, role="opener", reason="test"),
    Shot(uuid="m2", path=test_images["square_green"], media_type="photo",
         start_time=0.0, end_time=2.0, role="closer", reason="test"),
]
edl = EditDecisionList(
    shots=shots,
    title="Music Test",
    narrative_summary="Test with background music.",
    estimated_duration=4.0,
    music_mood="calm",
)

output_music = os.path.join(tmpdir, "output_with_music.mp4")
result_path = build_video(edl, theme_name="minimal", music_path=audio_path, output_path=output_music)

assert os.path.exists(result_path), "Music video output does not exist"
verify_clip = VideoFileClip(result_path)
assert verify_clip.audio is not None, "Video with music should have audio track"
print_ok(f"Music video has audio track, duration={verify_clip.duration:.1f}s")
verify_clip.close()

print_ok("Music test passed")


# ===================================================================
# Step 8: Test error cases
# ===================================================================

print_section("Step 8: Testing error cases")

# 8a: build_video with all invalid paths should raise RuntimeError
print("  Testing all-invalid paths...")
bad_shots = [
    Shot(uuid="bad1", path="/nonexistent/a.jpg", media_type="photo",
         start_time=0.0, end_time=2.0, role="opener", reason="test"),
    Shot(uuid="bad2", path="/nonexistent/b.jpg", media_type="photo",
         start_time=0.0, end_time=2.0, role="closer", reason="test"),
]
bad_edl = EditDecisionList(
    shots=bad_shots,
    title="Bad Video",
    narrative_summary="Should fail.",
    estimated_duration=4.0,
    music_mood="calm",
)
try:
    build_video(bad_edl, theme_name="minimal", output_path=os.path.join(tmpdir, "should_fail.mp4"))
    assert False, "Should have raised RuntimeError for all-invalid paths"
except RuntimeError as e:
    assert "No valid shots" in str(e), f"Wrong error message: {e}"
    print_ok(f"All-invalid paths correctly raises RuntimeError: {e}")

# 8b: build_video with mix of valid and invalid paths should succeed
print("  Testing mix of valid and invalid paths...")
mixed_shots = [
    Shot(uuid="good1", path=test_images["landscape_red"], media_type="photo",
         start_time=0.0, end_time=2.0, role="opener", reason="test"),
    Shot(uuid="bad3", path="/nonexistent/c.jpg", media_type="photo",
         start_time=0.0, end_time=2.0, role="highlight", reason="test"),
    Shot(uuid="good2", path=test_images["square_green"], media_type="photo",
         start_time=0.0, end_time=2.0, role="closer", reason="test"),
]
mixed_edl = EditDecisionList(
    shots=mixed_shots,
    title="Mixed Video",
    narrative_summary="Some valid, some invalid.",
    estimated_duration=6.0,
    music_mood="calm",
)
output_mixed = os.path.join(tmpdir, "output_mixed.mp4")
result_path = build_video(mixed_edl, theme_name="minimal", output_path=output_mixed)
assert os.path.exists(result_path), "Mixed-path video output does not exist"
assert os.path.getsize(result_path) > 0, "Mixed-path video is empty"
print_ok("Mix of valid/invalid paths succeeds (skips bad ones)")

# 8c: build_video with a single photo should work (no transitions needed)
print("  Testing single-photo video...")
single_shots = [
    Shot(uuid="solo1", path=test_images["small_purple"], media_type="photo",
         start_time=0.0, end_time=2.0, role="opener", reason="test"),
]
single_edl = EditDecisionList(
    shots=single_shots,
    title="Single Shot",
    narrative_summary="One photo only.",
    estimated_duration=2.0,
    music_mood="calm",
)
output_single = os.path.join(tmpdir, "output_single.mp4")
result_path = build_video(single_edl, theme_name="minimal", output_path=output_single)
assert os.path.exists(result_path), "Single-photo video output does not exist"
assert os.path.getsize(result_path) > 0, "Single-photo video is empty"
print_ok("Single-photo video works correctly")

print_ok("All error case tests passed")


# ===================================================================
# Step 9: Test closing card duration
# ===================================================================

print_section("Step 9: Testing closing card and overall duration")

shots_for_timing = [
    Shot(uuid="t1", path=test_images["landscape_red"], media_type="photo",
         start_time=0.0, end_time=2.0, role="opener", reason="test"),
    Shot(uuid="t2", path=test_images["portrait_blue"], media_type="photo",
         start_time=0.0, end_time=2.0, role="highlight", reason="test"),
]
timing_edl = EditDecisionList(
    shots=shots_for_timing,
    title="Timing Test",
    narrative_summary="Test video timing.",
    estimated_duration=4.0,
    music_mood="calm",
)

output_timing = os.path.join(tmpdir, "output_timing.mp4")
result_path = build_video(timing_edl, theme_name="minimal", output_path=output_timing)

verify_clip = VideoFileClip(result_path)
# Expected: title(3s) + 2 shots(2s each) + closing(2s) = 9s
# With crossfade transitions: 3 transitions * 0.3s = 0.9s overlap
# Expected ~ 9 - 0.9 = 8.1s
# Allow 2 seconds tolerance
expected_approx = 3.0 + 2 * 2.0 + 2.0 - 3 * 0.3  # 8.1
actual = verify_clip.duration
print(f"  Expected ~{expected_approx:.1f}s, got {actual:.1f}s")
assert abs(actual - expected_approx) < 2.0, \
    f"Duration mismatch: expected ~{expected_approx:.1f}s, got {actual:.1f}s"
print_ok(f"Duration within tolerance (expected ~{expected_approx:.1f}s, got {actual:.1f}s)")
verify_clip.close()

# Verify closing card exists by creating one standalone
closing_card = _create_closing_card(MINIMAL, 2.0, RESOLUTION, FPS)
assert abs(closing_card.duration - 2.0) < 0.01, \
    f"Closing card duration mismatch: {closing_card.duration}"
frame = closing_card.get_frame(1.0)
assert frame.shape == (180, 320, 3), f"Closing card wrong shape: {frame.shape}"
print_ok("Closing card renders correctly with correct duration")
closing_card.close()


# ===================================================================
# Done
# ===================================================================

print(f"\n{'='*60}")
print("  ALL ASSEMBLY VALIDATIONS PASSED")
print(f"{'='*60}")
print(f"\nTemp directory with outputs: {tmpdir}")
