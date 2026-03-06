"""End-to-end integration tests exercising the full pipeline.

All external dependencies (Apple Photos, Anthropic API) are mocked.
CLIP embeddings are computed for real on tiny test images to exercise
the actual embedding and vector-search code paths.
"""

from __future__ import annotations

import json
import uuid as uuid_mod
from dataclasses import asdict
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(uid: str, path: str, embedding: np.ndarray | None = None) -> dict:
    """Build a minimal media record dict suitable for ``upsert_media``."""
    return {
        "uuid": uid,
        "path": path,
        "media_type": "photo",
        "date": "2024-06-15T10:30:00",
        "lat": None,
        "lon": None,
        "albums": ["TestAlbum"],
        "labels": ["test"],
        "persons": [],
        "width": 64,
        "height": 64,
        "duration": None,
        "description": {"summary": f"Test image {uid[:8]}"},
        "embedding": embedding,
        "quality_score": 7.0,
    }


def _index_test_images(test_images: dict[str, str]) -> dict[str, str]:
    """Compute real CLIP embeddings for the test images, store them in the
    DB, and return a mapping of ``{colour_name: uuid}``."""
    from index.clip_embeddings import embed_image
    from index.store import init_db, upsert_media

    init_db()

    uid_map: dict[str, str] = {}
    for colour, path in test_images.items():
        uid = str(uuid_mod.uuid4())
        embedding = embed_image(path)
        record = _make_record(uid, path, embedding)
        upsert_media(record)
        uid_map[colour] = uid

    return uid_map


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.slow
def test_index_to_search_pipeline(tmp_db, test_images):
    """Index fake media with real CLIP embeddings, then verify hybrid_search
    returns results."""
    uid_map = _index_test_images(test_images)

    from curate.search import hybrid_search

    results = hybrid_search(query="a red coloured image", limit=10)
    assert len(results) > 0

    returned_uuids = {r["uuid"] for r in results}
    # At least one of our indexed items must appear
    assert returned_uuids & set(uid_map.values())


@pytest.mark.integration
@pytest.mark.slow
def test_index_to_generate_pipeline(tmp_db, test_images):
    """Index images, mock the Anthropic director, create an EDL, and verify
    the EDL references valid UUIDs from the index."""
    uid_map = _index_test_images(test_images)

    from curate.search import hybrid_search

    candidates = hybrid_search(query="colourful image", limit=10)
    assert len(candidates) > 0

    # Build a fake EDL response that Claude would return
    first_candidate = candidates[0]
    fake_edl_json = json.dumps({
        "title": "Integration Test Video",
        "narrative_summary": "A short test video.",
        "music_mood": "upbeat",
        "shots": [
            {
                "uuid": first_candidate["uuid"],
                "path": first_candidate.get("path", ""),
                "media_type": "photo",
                "start_time": 0.0,
                "end_time": 3.0,
                "role": "opener",
                "reason": "test shot",
            }
        ],
    })

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=fake_edl_json)]

    with patch("anthropic.Anthropic") as MockClient:
        mock_instance = MagicMock()
        mock_instance.messages.create.return_value = mock_response
        MockClient.return_value = mock_instance

        from curate.director import create_edit_decision_list

        edl = create_edit_decision_list(
            candidates=candidates,
            prompt="test video",
            target_duration=10.0,
        )

    assert len(edl.shots) > 0
    valid_uuids = {c["uuid"] for c in candidates}
    for shot in edl.shots:
        assert shot.uuid in valid_uuids


@pytest.mark.integration
@pytest.mark.slow
def test_full_pipeline_generates_video(tmp_db, test_images, tmp_path):
    """Complete flow: index, mock director EDL, run build_video, verify
    the output MP4 exists."""
    uid_map = _index_test_images(test_images)

    from curate.search import hybrid_search

    candidates = hybrid_search(query="colourful image", limit=10)
    assert len(candidates) > 0

    # Pick the first candidate for our single-shot EDL
    first = candidates[0]

    from curate.director import EditDecisionList, Shot

    edl = EditDecisionList(
        shots=[
            Shot(
                uuid=first["uuid"],
                path=first["path"],
                media_type="photo",
                start_time=0.0,
                end_time=3.0,
                role="opener",
                reason="test",
            )
        ],
        title="Test Video",
        narrative_summary="A test.",
        estimated_duration=3.0,
        music_mood="calm",
    )

    output_mp4 = str(tmp_path / "test_output.mp4")

    from assemble.builder import build_video

    result_path = build_video(
        edl=edl,
        theme_name="minimal",
        music_path=None,
        output_path=output_mp4,
    )

    assert Path(result_path).exists()
    assert Path(result_path).stat().st_size > 0


@pytest.mark.integration
def test_search_empty_db(tmp_db):
    """Search on an empty database returns empty results gracefully."""
    from index.store import init_db
    from curate.search import hybrid_search

    init_db()

    results = hybrid_search(query="anything at all", limit=10)
    assert results == []


@pytest.mark.integration
def test_generate_no_candidates(tmp_db):
    """Generate with no matching candidates gives a clear message (empty
    results rather than a crash)."""
    from index.store import init_db
    from curate.search import hybrid_search

    init_db()

    candidates = hybrid_search(query="nonexistent thing", limit=10)
    assert candidates == []
    # The real cmd_generate would print a message and return; we verify
    # that the search layer gracefully returns nothing so the CLI can
    # inform the user.
