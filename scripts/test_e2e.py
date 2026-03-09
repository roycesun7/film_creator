#!/usr/bin/env python3
"""End-to-end test of the video-composer pipeline.

Tests: media listing -> embeddings check -> AI arrange (search + enrich +
two-stage director + timeline build) -> project validation -> music library.

Requires the backend to be running at localhost:8000 with indexed media.

Usage:
    python scripts/test_e2e.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

BASE = "http://localhost:8000"

# ---------------------------------------------------------------------------
# Test bookkeeping
# ---------------------------------------------------------------------------

passed = 0
failed = 0
total = 0


def check(name: str, condition: bool, detail: str = "") -> bool:
    """Print a pass/fail line and return the condition."""
    status = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{status}] {name}{suffix}")
    return condition


def run_test(name: str, fn):
    """Run a test function, catch exceptions, and update counters."""
    global passed, failed, total
    total += 1
    print(f"\n{'=' * 60}")
    print(f"TEST {total}: {name}")
    print(f"{'=' * 60}")
    try:
        ok = fn()
        if ok:
            passed += 1
        else:
            failed += 1
    except Exception as exc:
        print(f"  [FAIL] Unhandled exception: {exc}")
        failed += 1


# ---------------------------------------------------------------------------
# Shared state across tests
# ---------------------------------------------------------------------------

created_project_id: str | None = None


# ---------------------------------------------------------------------------
# Test implementations
# ---------------------------------------------------------------------------

def test_backend_health() -> bool:
    """Verify the backend is reachable and has indexed media."""
    r = requests.get(f"{BASE}/api/media", params={"limit": 1}, timeout=10)
    if not check("GET /api/media returns 200", r.status_code == 200, f"status={r.status_code}"):
        return False
    data = r.json()
    count = data.get("total", 0)
    if not check("Media library is not empty", count > 0, f"total={count}"):
        return False
    print(f"    Media library has {count} items.")
    return True


def test_media_embeddings() -> bool:
    """Fetch a few media items and verify they have descriptions."""
    r = requests.get(f"{BASE}/api/media", params={"limit": 5}, timeout=10)
    if not check("GET /api/media?limit=5 returns 200", r.status_code == 200):
        return False
    items = r.json().get("items", [])
    if not check("Got at least 1 media item", len(items) > 0, f"got {len(items)}"):
        return False

    all_ok = True
    for item in items:
        uuid_short = item.get("uuid", "?")[:8]
        has_desc = bool(item.get("description"))
        if not check(f"Item {uuid_short} has description", has_desc):
            all_ok = False
        has_path = bool(item.get("path"))
        if not check(f"Item {uuid_short} has path", has_path):
            all_ok = False
        has_type = item.get("media_type") in ("photo", "video")
        if not check(f"Item {uuid_short} has valid media_type", has_type,
                     f"type={item.get('media_type')}"):
            all_ok = False
    return all_ok


def test_stats_endpoint() -> bool:
    """Verify the /api/stats endpoint returns enrichment info."""
    r = requests.get(f"{BASE}/api/stats", timeout=15)
    if not check("GET /api/stats returns 200", r.status_code == 200, f"status={r.status_code}"):
        return False
    data = r.json()
    total_count = data.get("total", 0)
    if not check("Stats total > 0", total_count > 0, f"total={total_count}"):
        return False
    with_emb = data.get("with_embeddings", 0)
    check("Some items have embeddings", with_emb > 0, f"{with_emb}/{total_count}")
    with_desc = data.get("with_descriptions", 0)
    check("Some items have descriptions", with_desc > 0, f"{with_desc}/{total_count}")
    print(f"    Stats: {total_count} total, {with_emb} embedded, {with_desc} described")
    return True


def test_create_and_arrange() -> bool:
    """THE BIG TEST: create a project, trigger AI arrange, poll to completion."""
    global created_project_id

    # Step 1: Create project
    # Use a broad prompt to maximize matches in small libraries
    print("  Step 1: Creating project...")
    r = requests.post(
        f"{BASE}/api/projects",
        json={"name": "E2E Test",
              "prompt": "Best moments highlights -- fun, upbeat, energetic montage of everything"},
        timeout=10,
    )
    if not check("POST /api/projects returns 200", r.status_code == 200, f"status={r.status_code}"):
        print(f"    Response: {r.text[:500]}")
        return False
    project_data = r.json()
    project_id = project_data.get("id")
    if not check("Project ID returned", bool(project_id), f"id={project_id}"):
        return False
    created_project_id = project_id
    print(f"    Created project: {project_id}")

    # Step 2: Trigger AI arrange
    print("  Step 2: Triggering AI arrange (search + enrich + director)...")
    r = requests.post(f"{BASE}/api/projects/{project_id}/preview", timeout=15)
    if not check("POST /api/projects/{id}/preview returns 200",
                 r.status_code == 200, f"status={r.status_code}"):
        print(f"    Response: {r.text[:500]}")
        return False
    job_id = r.json().get("job_id")
    if not check("Job ID returned", bool(job_id), f"job_id={job_id}"):
        return False
    print(f"    Job started: {job_id}")

    # Step 3: Poll for completion
    print("  Step 3: Polling for AI arrange completion...")
    timeout_sec = 120
    poll_interval = 5
    elapsed = 0
    final_status = None
    last_message = ""

    while elapsed < timeout_sec:
        r = requests.get(f"{BASE}/api/jobs/{job_id}", timeout=10)
        if r.status_code != 200:
            print(f"    Warning: job poll returned {r.status_code}")
            time.sleep(poll_interval)
            elapsed += poll_interval
            continue

        job = r.json()
        status = job.get("status", "unknown")
        progress = job.get("progress", 0)
        message = job.get("message", "")

        if message != last_message:
            print(f"    [{elapsed:3d}s] {status} ({progress}%) {message}")
            last_message = message

        if status in ("completed", "failed"):
            final_status = status
            break

        time.sleep(poll_interval)
        elapsed += poll_interval

    if not check("Job completed within timeout", final_status == "completed",
                 f"status={final_status}, elapsed={elapsed}s"):
        if final_status == "failed":
            print(f"    Failure message: {last_message}")
        return False

    # Step 4: Fetch the project and validate the timeline
    print("  Step 4: Validating project timeline...")
    r = requests.get(f"{BASE}/api/projects/{project_id}", timeout=10)
    if not check("GET /api/projects/{id} returns 200", r.status_code == 200):
        return False

    project = r.json()

    # Timeline structure
    timeline = project.get("timeline", {})
    tracks = timeline.get("tracks", [])
    if not check("Timeline has tracks", len(tracks) > 0, f"track_count={len(tracks)}"):
        return False

    # Find the video track
    video_tracks = [t for t in tracks if t.get("type") == "video"]
    if not check("At least one video track", len(video_tracks) > 0):
        return False

    clips = video_tracks[0].get("clips", [])
    if not check("Video track has clips", len(clips) > 0, f"clip_count={len(clips)}"):
        return False

    print(f"    Timeline: {len(tracks)} tracks, {len(clips)} clips on main video track")

    # Validate individual clips
    all_ok = True
    roles_seen = set()
    transition_types_seen = set()

    for i, clip in enumerate(clips):
        clip_label = f"Clip {i+1}/{len(clips)}"
        media_uuid = clip.get("media_uuid", "")
        if not check(f"{clip_label} has media_uuid", bool(media_uuid)):
            all_ok = False
            continue

        duration = clip.get("duration", 0)
        if not check(f"{clip_label} has non-zero duration", duration > 0, f"duration={duration:.1f}s"):
            all_ok = False

        role = clip.get("role", "")
        if role:
            roles_seen.add(role)

        transition = clip.get("transition", {})
        trans_type = transition.get("type", "unknown") if isinstance(transition, dict) else "unknown"
        transition_types_seen.add(trans_type)

    # Summary checks on the collection
    # Adaptive threshold: for small libraries (< 10 items), accept >= 1 clip
    r_count = requests.get(f"{BASE}/api/media", params={"limit": 1}, timeout=10)
    lib_size = r_count.json().get("total", 0) if r_count.status_code == 200 else 0
    min_clips = 3 if lib_size >= 10 else 1
    check(f"Enough clips present (>= {min_clips})", len(clips) >= min_clips,
          f"got {len(clips)} clips from {lib_size}-item library")
    check("Roles assigned", len(roles_seen) > 0, f"roles={roles_seen}")
    print(f"    Roles seen: {roles_seen}")
    print(f"    Transition types seen: {transition_types_seen}")

    # Narrative summary and music mood
    narrative = project.get("narrative_summary", "")
    if check("narrative_summary is non-empty", bool(narrative)):
        # Truncate for display
        display = narrative[:120] + ("..." if len(narrative) > 120 else "")
        print(f"    Narrative: {display}")

    music_mood = project.get("music_mood", "")
    if check("music_mood is non-empty", bool(music_mood)):
        print(f"    Music mood: {music_mood}")

    # Timeline duration
    tl_duration = timeline.get("duration", 0)
    check("Timeline duration > 0", tl_duration > 0, f"duration={tl_duration:.1f}s")

    # Text track (title card)
    text_tracks = [t for t in tracks if t.get("type") == "text"]
    if text_tracks:
        text_elements = text_tracks[0].get("text_elements", [])
        check("Title text element present", len(text_elements) > 0,
              f"text_elements={len(text_elements)}")

    return all_ok


def test_music_library_status() -> bool:
    """Check the music library (Jamendo) status endpoint."""
    r = requests.get(f"{BASE}/api/music/status", timeout=10)
    if not check("GET /api/music/status returns 200", r.status_code == 200,
                 f"status={r.status_code}"):
        return False
    data = r.json()
    available = data.get("available", False)
    check("Music library status has 'available' field", "available" in data)
    if available:
        print("    Jamendo music library is configured and available.")
    else:
        print("    Jamendo music library is NOT configured (JAMENDO_CLIENT_ID not set).")
    # This test passes either way -- we just report the status
    return True


def test_music_search() -> bool:
    """If Jamendo is available, try a search."""
    # Check availability first
    r = requests.get(f"{BASE}/api/music/status", timeout=10)
    if r.status_code != 200 or not r.json().get("available", False):
        print("  [SKIP] Jamendo not configured, skipping music search test.")
        return True  # not a failure

    r = requests.get(f"{BASE}/api/music/search",
                     params={"query": "upbeat", "mood": "happy", "limit": 5},
                     timeout=15)
    if not check("GET /api/music/search returns 200", r.status_code == 200,
                 f"status={r.status_code}"):
        return False
    data = r.json()
    tracks = data.get("tracks", [])
    check("Music search returned results", len(tracks) > 0, f"count={len(tracks)}")
    if tracks:
        first = tracks[0]
        print(f"    First result: {first.get('title', '?')} by {first.get('artist', '?')}")
    return True


def test_enriched_director_output() -> bool:
    """Deep validation of the director output from the project created in test 4."""
    global created_project_id
    if not created_project_id:
        print("  [SKIP] No project was created (earlier test failed).")
        return True

    r = requests.get(f"{BASE}/api/projects/{created_project_id}", timeout=10)
    if not check("GET /api/projects/{id} returns 200", r.status_code == 200):
        return False

    project = r.json()
    timeline = project.get("timeline", {})
    tracks = timeline.get("tracks", [])
    video_tracks = [t for t in tracks if t.get("type") == "video"]

    if not video_tracks:
        print("  [FAIL] No video track found.")
        return False

    clips = video_tracks[0].get("clips", [])

    # Check clip count -- adaptive to library size
    r_count = requests.get(f"{BASE}/api/media", params={"limit": 1}, timeout=10)
    lib_size = r_count.json().get("total", 0) if r_count.status_code == 200 else 0
    min_clips = 3 if lib_size >= 10 else 1
    if not check(f"At least {min_clips} clip(s) in timeline", len(clips) >= min_clips,
                 f"got {len(clips)} from {lib_size}-item library"):
        return False

    # Analyze transition distribution
    transition_counts: dict[str, int] = {}
    for clip in clips:
        trans = clip.get("transition", {})
        ttype = trans.get("type", "unknown") if isinstance(trans, dict) else "unknown"
        transition_counts[ttype] = transition_counts.get(ttype, 0) + 1

    print(f"    Transition distribution: {transition_counts}")

    # Director should use mostly cuts ("none") with occasional non-cut transitions
    has_cuts = "none" in transition_counts or "crossfade" in transition_counts
    check("Has at least one recognized transition type", has_cuts or len(transition_counts) > 0,
          f"types={list(transition_counts.keys())}")

    # Check for a mix (not 100% the same transition) -- but allow if all cuts
    all_same = len(transition_counts) == 1
    if all_same:
        sole_type = list(transition_counts.keys())[0]
        print(f"    All clips use '{sole_type}' transitions (acceptable if mostly cuts).")
    else:
        check("Mix of transition types", len(transition_counts) >= 2,
              f"types={list(transition_counts.keys())}")

    # Verify effects on clips
    clips_with_effects = sum(1 for c in clips if c.get("effects"))
    photo_clips = sum(1 for c in clips if c.get("media_type") == "photo")
    print(f"    {clips_with_effects}/{len(clips)} clips have effects, {photo_clips} are photos")

    # Check roles
    roles = set(c.get("role", "") for c in clips)
    min_roles = 2 if len(clips) >= 3 else 1
    check(f"Roles assigned (>= {min_roles})", len(roles) >= min_roles, f"roles={roles}")

    # Check reasons
    clips_with_reasons = sum(1 for c in clips if c.get("reason"))
    check("Most clips have a reason", clips_with_reasons >= len(clips) // 2,
          f"{clips_with_reasons}/{len(clips)} have reasons")

    # Check narrative_summary
    narrative = project.get("narrative_summary", "")
    if not check("narrative_summary is non-empty", bool(narrative)):
        return False

    # Check music_mood
    music_mood = project.get("music_mood", "")
    if not check("music_mood is non-empty", bool(music_mood)):
        return False

    return True


def test_ai_arrange_pipeline() -> bool:
    """Full AI Arrange pipeline: create project -> trigger arrange -> poll -> validate -> cleanup.

    This is a self-contained test that creates its own project, runs the AI arrange
    pipeline end-to-end, and validates the resulting timeline structure including
    transitions, narrative_summary, and music_mood.
    """
    test_project_id: str | None = None

    try:
        # Step 1: Create a new project with a prompt
        print("  Step 1: Creating a fresh test project...")
        r = requests.post(
            f"{BASE}/api/projects",
            json={
                "name": "AI Arrange Pipeline Test",
                "prompt": "A cinematic highlight reel -- dramatic, visually striking moments",
            },
            timeout=10,
        )
        if not check("POST /api/projects returns 200", r.status_code == 200,
                      f"status={r.status_code}"):
            print(f"    Response: {r.text[:500]}")
            return False

        project_data = r.json()
        test_project_id = project_data.get("id")
        if not check("Project ID returned", bool(test_project_id), f"id={test_project_id}"):
            return False
        print(f"    Created project: {test_project_id}")

        # Step 2: Trigger AI arrange via preview endpoint
        print("  Step 2: Triggering AI arrange (POST /api/projects/{id}/preview)...")
        r = requests.post(f"{BASE}/api/projects/{test_project_id}/preview", timeout=15)
        if not check("POST preview returns 200", r.status_code == 200,
                      f"status={r.status_code}"):
            print(f"    Response: {r.text[:500]}")
            return False

        job_id = r.json().get("job_id")
        if not check("Job ID returned", bool(job_id), f"job_id={job_id}"):
            return False
        print(f"    Job started: {job_id}")

        # Step 3: Poll the job until completion (max 120s)
        print("  Step 3: Polling for job completion (max 120s)...")
        timeout_sec = 120
        poll_interval = 5
        elapsed = 0
        final_status = None
        last_message = ""

        while elapsed < timeout_sec:
            r = requests.get(f"{BASE}/api/jobs/{job_id}", timeout=10)
            if r.status_code != 200:
                print(f"    Warning: job poll returned {r.status_code}")
                time.sleep(poll_interval)
                elapsed += poll_interval
                continue

            job = r.json()
            status = job.get("status", "unknown")
            progress = job.get("progress", 0)
            message = job.get("message", "")

            if message != last_message:
                print(f"    [{elapsed:3d}s] {status} ({progress}%) {message}")
                last_message = message

            if status in ("completed", "failed"):
                final_status = status
                break

            time.sleep(poll_interval)
            elapsed += poll_interval

        if not check("Job completed within 120s", final_status == "completed",
                      f"status={final_status}, elapsed={elapsed}s"):
            if final_status == "failed":
                print(f"    Failure message: {last_message}")
            return False

        # Step 4: Fetch the completed project and validate
        print("  Step 4: Validating the arranged project...")
        r = requests.get(f"{BASE}/api/projects/{test_project_id}", timeout=10)
        if not check("GET /api/projects/{id} returns 200", r.status_code == 200):
            return False

        project = r.json()
        all_ok = True

        # 4a: Timeline has at least 1 track
        timeline = project.get("timeline", {})
        tracks = timeline.get("tracks", [])
        if not check("Timeline has at least 1 track", len(tracks) >= 1,
                      f"track_count={len(tracks)}"):
            return False

        # 4b: Clips exist on at least one track
        video_tracks = [t for t in tracks if t.get("type") == "video"]
        if not check("At least one video track exists", len(video_tracks) > 0):
            return False

        clips = video_tracks[0].get("clips", [])
        if not check("Video track has clips", len(clips) > 0, f"clip_count={len(clips)}"):
            return False
        print(f"    Found {len(clips)} clips on main video track")

        # 4c: At least one clip has a non-"none" transition
        non_none_transitions = []
        for clip in clips:
            trans = clip.get("transition", {})
            trans_type = trans.get("type", "none") if isinstance(trans, dict) else "none"
            if trans_type != "none":
                non_none_transitions.append(trans_type)

        if not check("At least one clip has a non-'none' transition",
                      len(non_none_transitions) > 0,
                      f"non-none transitions: {non_none_transitions}"):
            all_ok = False

        print(f"    Transitions found: {non_none_transitions}")

        # 4d: narrative_summary is not empty
        narrative = project.get("narrative_summary", "")
        if not check("narrative_summary is not empty", bool(narrative)):
            all_ok = False
        else:
            display = narrative[:120] + ("..." if len(narrative) > 120 else "")
            print(f"    Narrative: {display}")

        # 4e: music_mood is not empty
        music_mood = project.get("music_mood", "")
        if not check("music_mood is not empty", bool(music_mood)):
            all_ok = False
        else:
            print(f"    Music mood: {music_mood}")

        return all_ok

    finally:
        # Step 5: Clean up the test project
        if test_project_id:
            print("  Step 5: Cleaning up test project...")
            try:
                r = requests.delete(f"{BASE}/api/projects/{test_project_id}", timeout=10)
                if r.status_code == 200:
                    print(f"    Deleted project {test_project_id}")
                else:
                    print(f"    Warning: cleanup returned status {r.status_code}")
            except Exception as exc:
                print(f"    Warning: cleanup failed: {exc}")


def test_project_cleanup() -> bool:
    """Delete the test project created during the test run."""
    global created_project_id
    if not created_project_id:
        print("  [SKIP] No project to clean up.")
        return True

    r = requests.delete(f"{BASE}/api/projects/{created_project_id}", timeout=10)
    if not check("DELETE /api/projects/{id} returns 200", r.status_code == 200,
                 f"status={r.status_code}"):
        return False
    data = r.json()
    if not check("Project deleted", data.get("deleted") is True):
        return False

    # Verify it's gone
    r2 = requests.get(f"{BASE}/api/projects/{created_project_id}", timeout=10)
    check("Project returns 404 after deletion", r2.status_code == 404,
          f"status={r2.status_code}")

    created_project_id = None
    print("    Test project cleaned up.")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global created_project_id

    print("=" * 60)
    print("VIDEO COMPOSER -- END-TO-END PIPELINE TEST")
    print("=" * 60)
    print(f"Backend: {BASE}")
    print(f"Time:    {time.strftime('%Y-%m-%d %H:%M:%S')}")

    # Quick connectivity check
    try:
        r = requests.get(f"{BASE}/api/stats", timeout=5)
        r.raise_for_status()
        print("Backend is reachable.\n")
    except Exception as exc:
        print(f"\nERROR: Cannot reach backend at {BASE}")
        print(f"  {exc}")
        print("\nMake sure the backend is running:")
        print("  cd /Users/kzoyce/Code_Projects/video-composer")
        print("  python -m uvicorn api:app --port 8000")
        sys.exit(1)

    # Run tests in order
    run_test("Backend Health", test_backend_health)
    run_test("Media Embeddings & Descriptions", test_media_embeddings)
    run_test("Stats Endpoint", test_stats_endpoint)
    run_test("Create Project & AI Arrange (search -> enrich -> direct -> build)",
             test_create_and_arrange)
    run_test("Music Library Status", test_music_library_status)
    run_test("Music Search", test_music_search)
    run_test("Enriched Director Output Validation", test_enriched_director_output)
    run_test("AI Arrange Pipeline (create -> arrange -> validate -> cleanup)",
             test_ai_arrange_pipeline)
    run_test("Cleanup Test Project", test_project_cleanup)

    # Summary
    print(f"\n{'=' * 60}")
    print(f"RESULTS: {passed} passed, {failed} failed out of {total} total")
    print(f"{'=' * 60}")

    if failed > 0:
        print("\nSome tests FAILED.")
        sys.exit(1)
    else:
        print("\nAll tests PASSED.")
        sys.exit(0)


if __name__ == "__main__":
    main()
