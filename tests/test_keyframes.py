"""Tests for keyframe embedding storage and search."""

from __future__ import annotations

import numpy as np
import pytest

from config import CLIP_EMBEDDING_DIM
from index.store import (
    init_db,
    upsert_media,
    upsert_keyframe_embedding,
    search_keyframes_by_text,
    delete_keyframe_embeddings,
    get_media_by_uuids,
)


def _rand_embedding(seed: int = 0) -> np.ndarray:
    """Return a deterministic L2-normalised random embedding."""
    rng = np.random.RandomState(seed)
    vec = rng.randn(CLIP_EMBEDDING_DIM).astype(np.float32)
    vec /= np.linalg.norm(vec)
    return vec


def _insert_dummy_media(uuid: str, media_type: str = "video") -> None:
    """Insert a minimal media record so foreign-key references work."""
    upsert_media({
        "uuid": uuid,
        "path": f"/tmp/{uuid}.mp4",
        "media_type": media_type,
        "date": "2024-06-15T10:00:00",
        "albums": [],
        "labels": [],
        "persons": [],
        "description": {},
        "embedding": _rand_embedding(hash(uuid) % 1000),
    })


# ---- Test: upsert stores and retrieves correctly ----

def test_upsert_keyframe_embedding_stores_correctly(tmp_db):
    init_db()
    _insert_dummy_media("vid-001")

    emb = _rand_embedding(42)
    upsert_keyframe_embedding("vid-001", 0, 0.0, emb)

    # Retrieve via search with the same embedding as query — should be top hit
    results = search_keyframes_by_text(emb, limit=5)
    assert len(results) == 1
    assert results[0]["media_uuid"] == "vid-001"
    assert results[0]["keyframe_index"] == 0
    assert results[0]["timestamp"] == 0.0
    assert results[0]["similarity"] == pytest.approx(1.0, abs=1e-4)


# ---- Test: upsert can update existing keyframe ----

def test_upsert_keyframe_embedding_updates(tmp_db):
    init_db()
    _insert_dummy_media("vid-002")

    emb_old = _rand_embedding(10)
    upsert_keyframe_embedding("vid-002", 0, 0.0, emb_old)

    emb_new = _rand_embedding(20)
    upsert_keyframe_embedding("vid-002", 0, 1.0, emb_new)

    # Search with new embedding — should find it with high similarity
    results = search_keyframes_by_text(emb_new, limit=5)
    assert len(results) == 1
    assert results[0]["timestamp"] == 1.0
    assert results[0]["similarity"] == pytest.approx(1.0, abs=1e-4)


# ---- Test: search returns best keyframe per video ----

def test_search_returns_best_keyframe_per_video(tmp_db):
    init_db()
    _insert_dummy_media("vid-003")

    # Insert several keyframes with different embeddings
    target_emb = _rand_embedding(99)
    for ki in range(5):
        emb = _rand_embedding(ki)  # random, not similar to target
        upsert_keyframe_embedding("vid-003", ki, ki * 2.0, emb)

    # Overwrite keyframe 3 with the target embedding so it matches best
    upsert_keyframe_embedding("vid-003", 3, 6.0, target_emb)

    results = search_keyframes_by_text(target_emb, limit=10)
    assert len(results) == 1  # only one video
    assert results[0]["media_uuid"] == "vid-003"
    assert results[0]["keyframe_index"] == 3
    assert results[0]["timestamp"] == 6.0


# ---- Test: search with known embeddings returns correct ranking ----

def test_search_returns_correct_ranking(tmp_db):
    init_db()

    # Create two videos with different keyframes
    _insert_dummy_media("vid-A")
    _insert_dummy_media("vid-B")

    # vid-A keyframe is close to query
    query = _rand_embedding(50)
    close_emb = query.copy()  # identical => similarity ~1.0

    # vid-B keyframe is random => low similarity
    far_emb = _rand_embedding(51)

    upsert_keyframe_embedding("vid-A", 0, 0.0, close_emb)
    upsert_keyframe_embedding("vid-B", 0, 0.0, far_emb)

    results = search_keyframes_by_text(query, limit=10)
    assert len(results) == 2
    assert results[0]["media_uuid"] == "vid-A"
    assert results[0]["similarity"] > results[1]["similarity"]


# ---- Test: delete removes all keyframes for a UUID ----

def test_delete_keyframe_embeddings(tmp_db):
    init_db()
    _insert_dummy_media("vid-del")

    for ki in range(4):
        upsert_keyframe_embedding("vid-del", ki, ki * 2.0, _rand_embedding(ki + 100))

    # Confirm they exist
    results = search_keyframes_by_text(_rand_embedding(100), limit=10)
    assert any(r["media_uuid"] == "vid-del" for r in results)

    delete_keyframe_embeddings("vid-del")

    results = search_keyframes_by_text(_rand_embedding(100), limit=10)
    assert not any(r["media_uuid"] == "vid-del" for r in results)


# ---- Test: empty table returns empty results ----

def test_empty_keyframe_table_returns_empty(tmp_db):
    init_db()
    results = search_keyframes_by_text(_rand_embedding(0), limit=10)
    assert results == []


# ---- Test: integration — index a video with multiple keyframes, search finds it ----

def test_integration_video_found_via_keyframe(tmp_db):
    init_db()

    # Insert a video with a generic main embedding
    generic_emb = _rand_embedding(200)
    upsert_media({
        "uuid": "vid-integration",
        "path": "/tmp/vid-integration.mp4",
        "media_type": "video",
        "date": "2024-07-01T12:00:00",
        "albums": [],
        "labels": [],
        "persons": [],
        "description": {},
        "embedding": generic_emb,
    })

    # Insert keyframes — keyframe 2 matches a "sunset" query embedding
    sunset_query = _rand_embedding(300)
    for ki in range(5):
        emb = _rand_embedding(ki + 400)  # unrelated
        upsert_keyframe_embedding("vid-integration", ki, ki * 2.0, emb)

    # Make keyframe 2 match the sunset query exactly
    upsert_keyframe_embedding("vid-integration", 2, 4.0, sunset_query)

    # The main embedding search would give low similarity to sunset_query
    # but keyframe search should find it
    results = search_keyframes_by_text(sunset_query, limit=5)
    assert len(results) >= 1
    assert results[0]["media_uuid"] == "vid-integration"
    assert results[0]["keyframe_index"] == 2
    assert results[0]["similarity"] == pytest.approx(1.0, abs=1e-4)

    # Also verify the media record can be looked up
    records = get_media_by_uuids(["vid-integration"])
    assert len(records) == 1
    assert records[0]["media_type"] == "video"
