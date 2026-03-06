"""Tests for the curation layer: curate/search.py and curate/director.py."""

from __future__ import annotations

import json
import logging
import uuid as _uuid
from dataclasses import asdict
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

import config
from index import store
from curate.search import hybrid_search, find_similar, _fuse_results
from curate.director import (
    Shot,
    EditDecisionList,
    create_edit_decision_list,
    _build_manifest,
    _parse_response,
    _validate,
)


# =========================================================================== #
# Helpers
# =========================================================================== #

def _random_embedding(dim: int = 512, rng: np.random.Generator | None = None) -> np.ndarray:
    if rng is None:
        rng = np.random.default_rng()
    vec = rng.standard_normal(dim).astype(np.float32)
    vec /= np.linalg.norm(vec)
    return vec


def _make_item(
    *,
    uuid: str | None = None,
    media_type: str = "photo",
    date: str = "2025-06-15T12:00:00",
    albums: list[str] | None = None,
    persons: list[str] | None = None,
    labels: list[str] | None = None,
    quality_score: float = 0.8,
    duration: float | None = None,
    embedding: np.ndarray | None = None,
    path: str | None = None,
) -> dict:
    uid = uuid or str(_uuid.uuid4())
    return {
        "uuid": uid,
        "path": path or f"/media/{uid}.jpg",
        "media_type": media_type,
        "date": date,
        "lat": None,
        "lon": None,
        "albums": albums or [],
        "labels": labels or [],
        "persons": persons or [],
        "width": 1920,
        "height": 1080,
        "duration": duration,
        "description": {"summary": "A test image"},
        "embedding": embedding,
        "quality_score": quality_score,
    }


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    """Point config.DB_PATH at a temporary SQLite file for every test."""
    db_file = tmp_path / "test_media.db"
    monkeypatch.setattr(config, "DB_PATH", db_file)
    # store imports DB_PATH at module level, so we must patch it there too.
    monkeypatch.setattr(store, "DB_PATH", db_file)
    store.init_db()


def _seed_db(items: list[dict]) -> None:
    for item in items:
        store.upsert_media(item)


def _make_known_embedding(value: float = 1.0, dim: int = 512) -> np.ndarray:
    """Return a normalized embedding with a known direction."""
    vec = np.zeros(dim, dtype=np.float32)
    vec[0] = value
    vec /= np.linalg.norm(vec)
    return vec


# =========================================================================== #
# search.py tests
# =========================================================================== #


class TestHybridSearchEmbeddingOnly:
    """hybrid_search with only embedding results (no metadata filters)."""

    @patch("curate.search.clip_embeddings.embed_text")
    def test_returns_ranked_results_with_relevance_score(self, mock_embed):
        rng = np.random.default_rng(99)
        query_vec = _make_known_embedding(1.0)
        mock_embed.return_value = query_vec

        # Item whose embedding is close to query_vec
        close_emb = query_vec.copy()
        close_emb[1] = 0.05
        close_emb /= np.linalg.norm(close_emb)

        far_emb = _random_embedding(rng=rng)

        items = [
            _make_item(uuid="close-1", embedding=close_emb, quality_score=0.9),
            _make_item(uuid="far-1", embedding=far_emb, quality_score=0.9),
        ]
        _seed_db(items)

        results = hybrid_search("test query")

        assert len(results) >= 1
        for r in results:
            assert "relevance_score" in r
        # close-1 should rank first
        assert results[0]["uuid"] == "close-1"


class TestHybridSearchWithMetadataFilters:
    """hybrid_search with metadata filters produces fused results."""

    @patch("curate.search.clip_embeddings.embed_text")
    def test_album_filter_returns_fused(self, mock_embed):
        query_vec = _make_known_embedding()
        mock_embed.return_value = query_vec

        items = [
            _make_item(uuid="v1", albums=["vacation"], embedding=_make_known_embedding(),
                       quality_score=0.9),
            _make_item(uuid="w1", albums=["work"], embedding=_random_embedding(),
                       quality_score=0.9),
        ]
        _seed_db(items)

        results = hybrid_search("beach", albums=["vacation"])
        uuids = [r["uuid"] for r in results]
        assert "v1" in uuids

    @patch("curate.search.clip_embeddings.embed_text")
    def test_persons_filter(self, mock_embed):
        mock_embed.return_value = _make_known_embedding()

        items = [
            _make_item(uuid="alice-1", persons=["Alice"], embedding=_make_known_embedding()),
            _make_item(uuid="bob-1", persons=["Bob"], embedding=_random_embedding()),
        ]
        _seed_db(items)

        results = hybrid_search("portrait", persons=["Alice"])
        uuids = [r["uuid"] for r in results]
        assert "alice-1" in uuids

    @patch("curate.search.clip_embeddings.embed_text")
    def test_date_range_filter(self, mock_embed):
        mock_embed.return_value = _make_known_embedding()

        items = [
            _make_item(uuid="june", date="2025-06-15T12:00:00",
                       embedding=_make_known_embedding()),
            _make_item(uuid="jan", date="2025-01-01T12:00:00",
                       embedding=_random_embedding()),
        ]
        _seed_db(items)

        results = hybrid_search(
            "summer",
            date_range=("2025-06-01", "2025-06-30"),
        )
        uuids = [r["uuid"] for r in results]
        assert "june" in uuids


class TestRRFBoost:
    """Items in both embedding and metadata results get boosted scores."""

    @patch("curate.search.clip_embeddings.embed_text")
    def test_item_in_both_gets_higher_score(self, mock_embed):
        query_vec = _make_known_embedding()
        mock_embed.return_value = query_vec

        # Both items have similar embeddings but only one matches the album filter
        emb = query_vec.copy()
        items = [
            _make_item(uuid="both-1", albums=["vacation"], embedding=emb,
                       quality_score=0.9, date="2025-06-15T12:00:00"),
            _make_item(uuid="emb-only", albums=["work"], embedding=emb,
                       quality_score=0.9, date="2025-06-15T12:00:00"),
        ]
        _seed_db(items)

        results = hybrid_search("beach", albums=["vacation"])
        score_map = {r["uuid"]: r["relevance_score"] for r in results}
        # both-1 appears in embedding AND metadata results => boosted
        assert score_map["both-1"] > score_map["emb-only"]


class TestMinQualityFilter:
    """min_quality filter works."""

    @patch("curate.search.clip_embeddings.embed_text")
    def test_filters_low_quality(self, mock_embed):
        mock_embed.return_value = _make_known_embedding()

        items = [
            _make_item(uuid="hq", quality_score=0.9, embedding=_make_known_embedding()),
            _make_item(uuid="lq", quality_score=0.3, embedding=_random_embedding()),
        ]
        _seed_db(items)

        results = hybrid_search("anything", min_quality=0.7)
        uuids = [r["uuid"] for r in results]
        assert "hq" in uuids
        assert "lq" not in uuids


class TestFindSimilar:
    """find_similar returns visually similar items, excluding the query item."""

    def test_returns_similar_excluding_self(self):
        base = _make_known_embedding()
        close = base.copy()
        close[1] = 0.01
        close /= np.linalg.norm(close)

        items = [
            _make_item(uuid="query-item", embedding=base),
            _make_item(uuid="close-item", embedding=close),
            _make_item(uuid="rand-item", embedding=_random_embedding()),
        ]
        _seed_db(items)

        results = find_similar("query-item", limit=5)
        uuids = [r["uuid"] for r in results]
        assert "query-item" not in uuids
        assert "close-item" in uuids
        # close-item should be the most similar
        assert results[0]["uuid"] == "close-item"

    def test_unknown_uuid_returns_empty(self):
        items = [_make_item(uuid="x1", embedding=_make_known_embedding())]
        _seed_db(items)
        results = find_similar("nonexistent-uuid")
        assert results == []


class TestEmptyDatabase:
    """Empty database returns empty results."""

    @patch("curate.search.clip_embeddings.embed_text")
    def test_hybrid_search_empty(self, mock_embed):
        mock_embed.return_value = _make_known_embedding()
        results = hybrid_search("anything")
        assert results == []

    def test_find_similar_empty(self):
        results = find_similar("any-uuid")
        assert results == []


# =========================================================================== #
# director.py tests
# =========================================================================== #


class TestDataclasses:
    """Shot and EditDecisionList dataclasses instantiate correctly."""

    def test_shot_creation(self):
        shot = Shot(
            uuid="abc",
            path="/media/abc.jpg",
            media_type="photo",
            start_time=0.0,
            end_time=3.0,
            role="opener",
            reason="nice opener",
        )
        assert shot.uuid == "abc"
        assert shot.end_time == 3.0
        assert shot.role == "opener"

    def test_edl_defaults(self):
        edl = EditDecisionList()
        assert edl.shots == []
        assert edl.title == ""
        assert edl.estimated_duration == 0.0

    def test_edl_with_shots(self):
        shot = Shot("a", "/a.jpg", "photo", 0, 3, "opener", "reason")
        edl = EditDecisionList(shots=[shot], title="My Video")
        assert len(edl.shots) == 1
        assert edl.title == "My Video"


class TestBuildManifest:
    """_build_manifest produces compact entries with required fields."""

    def test_required_fields_present(self):
        candidates = [
            _make_item(uuid="m1"),
            _make_item(uuid="m2", media_type="video", duration=5.0),
        ]
        manifest = _build_manifest(candidates)
        assert len(manifest) == 2
        required_keys = {"uuid", "media_type", "description", "date", "persons",
                         "labels", "quality_score", "duration", "path"}
        for entry in manifest:
            assert required_keys <= set(entry.keys())

    def test_values_propagated(self):
        item = _make_item(uuid="x1", media_type="video", duration=4.2,
                          persons=["Alice"], labels=["beach"])
        manifest = _build_manifest([item])
        assert manifest[0]["uuid"] == "x1"
        assert manifest[0]["media_type"] == "video"
        assert manifest[0]["duration"] == 4.2
        assert manifest[0]["persons"] == ["Alice"]


class TestParseResponse:
    """_parse_response handles valid JSON and markdown-fenced JSON."""

    def _make_candidates(self):
        return [
            _make_item(uuid="u1", path="/media/u1.jpg"),
            _make_item(uuid="u2", path="/media/u2.jpg"),
        ]

    def _valid_json(self) -> str:
        return json.dumps({
            "title": "Test Video",
            "narrative_summary": "A test",
            "music_mood": "calm",
            "shots": [
                {
                    "uuid": "u1",
                    "path": "/media/u1.jpg",
                    "media_type": "photo",
                    "start_time": 0.0,
                    "end_time": 3.0,
                    "role": "opener",
                    "reason": "good opener",
                },
                {
                    "uuid": "u2",
                    "path": "/media/u2.jpg",
                    "media_type": "photo",
                    "start_time": 3.0,
                    "end_time": 6.0,
                    "role": "closer",
                    "reason": "nice ending",
                },
            ],
        })

    def test_valid_json(self):
        candidates = self._make_candidates()
        edl = _parse_response(self._valid_json(), candidates)
        assert isinstance(edl, EditDecisionList)
        assert edl.title == "Test Video"
        assert len(edl.shots) == 2
        assert edl.shots[0].uuid == "u1"
        assert edl.estimated_duration == pytest.approx(6.0)

    def test_markdown_fenced_json(self):
        candidates = self._make_candidates()
        fenced = f"```json\n{self._valid_json()}\n```"
        edl = _parse_response(fenced, candidates)
        assert edl.title == "Test Video"
        assert len(edl.shots) == 2

    def test_path_lookup_fallback(self):
        """If shot JSON omits path, it falls back to the candidates lookup."""
        candidates = self._make_candidates()
        data = {
            "title": "T",
            "narrative_summary": "",
            "music_mood": "",
            "shots": [{"uuid": "u1", "start_time": 0, "end_time": 2, "role": "b-roll", "reason": "r"}],
        }
        edl = _parse_response(json.dumps(data), candidates)
        assert edl.shots[0].path == "/media/u1.jpg"


class TestValidate:
    """_validate cleans up the EDL."""

    def _make_candidates(self):
        return [
            _make_item(uuid="u1"),
            _make_item(uuid="u2"),
            _make_item(uuid="u3"),
        ]

    def test_removes_unknown_uuids(self):
        candidates = self._make_candidates()
        edl = EditDecisionList(
            shots=[
                Shot("u1", "/u1.jpg", "photo", 0, 3, "opener", "r"),
                Shot("unknown-uuid", "/x.jpg", "photo", 3, 6, "b-roll", "r"),
            ],
        )
        validated = _validate(edl, candidates, 30.0)
        uuids = [s.uuid for s in validated.shots]
        assert "u1" in uuids
        assert "unknown-uuid" not in uuids

    def test_removes_duplicate_uuids_keeps_first(self):
        candidates = self._make_candidates()
        edl = EditDecisionList(
            shots=[
                Shot("u1", "/u1.jpg", "photo", 0, 3, "opener", "first"),
                Shot("u1", "/u1.jpg", "photo", 3, 6, "b-roll", "second"),
                Shot("u2", "/u2.jpg", "photo", 6, 9, "closer", "r"),
            ],
        )
        validated = _validate(edl, candidates, 30.0)
        u1_shots = [s for s in validated.shots if s.uuid == "u1"]
        assert len(u1_shots) == 1
        assert u1_shots[0].reason == "first"

    def test_ensures_nonnegative_ordered_times(self):
        candidates = self._make_candidates()
        edl = EditDecisionList(
            shots=[
                Shot("u1", "/u1.jpg", "photo", -5.0, -1.0, "opener", "r"),
                Shot("u2", "/u2.jpg", "photo", 3.0, 2.0, "b-roll", "r"),
            ],
        )
        validated = _validate(edl, candidates, 30.0)
        for shot in validated.shots:
            assert shot.start_time >= 0.0
            assert shot.end_time > shot.start_time

    def test_warns_duration_divergence(self, caplog):
        candidates = self._make_candidates()
        # 3 seconds total vs 60 second target => way under 50%
        edl = EditDecisionList(
            shots=[
                Shot("u1", "/u1.jpg", "photo", 0, 3, "opener", "r"),
            ],
        )
        with caplog.at_level(logging.WARNING, logger="curate.director"):
            _validate(edl, candidates, 60.0)
        assert any("diverges" in rec.message for rec in caplog.records)

    def test_no_warning_when_close_to_target(self, caplog):
        candidates = self._make_candidates()
        # 9 seconds vs 10 target => ratio 0.9, within range
        edl = EditDecisionList(
            shots=[
                Shot("u1", "/u1.jpg", "photo", 0, 3, "opener", "r"),
                Shot("u2", "/u2.jpg", "photo", 3, 6, "b-roll", "r"),
                Shot("u3", "/u3.jpg", "photo", 6, 9, "closer", "r"),
            ],
        )
        with caplog.at_level(logging.WARNING, logger="curate.director"):
            _validate(edl, candidates, 10.0)
        assert not any("diverges" in rec.message for rec in caplog.records)


class TestCreateEditDecisionListCallsAPI:
    """create_edit_decision_list calls Claude API with correct manifest format."""

    @patch("curate.director.anthropic.Anthropic")
    def test_calls_api_with_manifest(self, MockAnthropic):
        candidates = [
            _make_item(uuid="c1", media_type="photo"),
            _make_item(uuid="c2", media_type="video", duration=4.0),
        ]

        response_data = {
            "title": "Test",
            "narrative_summary": "A short test video",
            "music_mood": "calm",
            "shots": [
                {
                    "uuid": "c1",
                    "path": "/media/c1.jpg",
                    "media_type": "photo",
                    "start_time": 0.0,
                    "end_time": 3.0,
                    "role": "opener",
                    "reason": "good start",
                },
            ],
        }

        mock_client = MagicMock()
        MockAnthropic.return_value = mock_client

        mock_response = MagicMock()
        mock_content_block = MagicMock()
        mock_content_block.text = json.dumps(response_data)
        mock_response.content = [mock_content_block]
        mock_client.messages.create.return_value = mock_response

        edl = create_edit_decision_list(candidates, "make a nice video", 30.0)

        # Verify API was called
        mock_client.messages.create.assert_called_once()
        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs.kwargs["model"] == config.DIRECTOR_MODEL
        assert call_kwargs.kwargs["max_tokens"] == 4096

        # Verify the user message contains the manifest
        user_msg = call_kwargs.kwargs["messages"][0]["content"]
        assert "c1" in user_msg
        assert "c2" in user_msg
        assert "30" in user_msg


class TestEndToEndMock:
    """End-to-end: mock anthropic client, verify full create_edit_decision_list flow."""

    @patch("curate.director.anthropic.Anthropic")
    def test_full_flow(self, MockAnthropic):
        candidates = [
            _make_item(uuid="e1", media_type="photo", path="/media/e1.jpg"),
            _make_item(uuid="e2", media_type="video", duration=6.0, path="/media/e2.mp4"),
            _make_item(uuid="e3", media_type="photo", path="/media/e3.jpg"),
        ]

        response_data = {
            "title": "Summer Highlights",
            "narrative_summary": "A montage of summer fun.",
            "music_mood": "upbeat",
            "shots": [
                {
                    "uuid": "e1",
                    "path": "/media/e1.jpg",
                    "media_type": "photo",
                    "start_time": 0.0,
                    "end_time": 4.0,
                    "role": "opener",
                    "reason": "bright opening shot",
                },
                {
                    "uuid": "e2",
                    "path": "/media/e2.mp4",
                    "media_type": "video",
                    "start_time": 4.0,
                    "end_time": 9.0,
                    "role": "highlight",
                    "reason": "action sequence",
                },
                {
                    "uuid": "e3",
                    "path": "/media/e3.jpg",
                    "media_type": "photo",
                    "start_time": 9.0,
                    "end_time": 13.0,
                    "role": "closer",
                    "reason": "warm ending",
                },
                {
                    "uuid": "e1",
                    "path": "/media/e1.jpg",
                    "media_type": "photo",
                    "start_time": 13.0,
                    "end_time": 16.0,
                    "role": "b-roll",
                    "reason": "duplicate that should be removed",
                },
            ],
        }

        mock_client = MagicMock()
        MockAnthropic.return_value = mock_client
        mock_response = MagicMock()
        mock_content_block = MagicMock()
        mock_content_block.text = json.dumps(response_data)
        mock_response.content = [mock_content_block]
        mock_client.messages.create.return_value = mock_response

        edl = create_edit_decision_list(candidates, "summer video", target_duration=15.0)

        # Should be a valid EditDecisionList
        assert isinstance(edl, EditDecisionList)
        assert edl.title == "Summer Highlights"
        assert edl.narrative_summary == "A montage of summer fun."
        assert edl.music_mood == "upbeat"

        # Duplicate e1 should have been removed by _validate
        uuids = [s.uuid for s in edl.shots]
        assert len(uuids) == len(set(uuids)), "No duplicate UUIDs"

        # All remaining UUIDs must be from candidates
        valid_uuids = {c["uuid"] for c in candidates}
        for uid in uuids:
            assert uid in valid_uuids

        # All times must be non-negative and ordered
        for shot in edl.shots:
            assert shot.start_time >= 0.0
            assert shot.end_time > shot.start_time

        # estimated_duration should be recalculated
        assert edl.estimated_duration > 0
        expected_dur = sum(s.end_time - s.start_time for s in edl.shots)
        assert edl.estimated_duration == pytest.approx(expected_dur)
