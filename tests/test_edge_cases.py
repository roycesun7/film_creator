"""Edge case and stress tests for the video-composer project.

Tests cover boundary conditions, malformed inputs, and failure modes across
all layers: store, search, director, assembly, and CLI.
"""

from __future__ import annotations

import importlib
import json
import os
import sqlite3
import struct
import sys
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config
from index import store
from curate.search import hybrid_search, find_similar
from curate.director import (
    Shot,
    EditDecisionList,
    _build_manifest,
    _parse_response,
    _validate,
)
from assemble.themes import (
    MINIMAL,
    WARM_NOSTALGIC,
    _warm_filter,
    apply_ken_burns,
)
from assemble.builder import (
    _create_title_card,
    _prepare_music,
    build_video,
)


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _reload_store():
    """Re-import index.store so it reads the current config.DB_PATH."""
    import index.store as _mod
    importlib.reload(_mod)
    return _mod


def _make_media_record(uuid, **overrides):
    """Return a minimal media dict suitable for upsert_media."""
    rec = {
        "uuid": uuid,
        "path": f"/fake/{uuid}.jpg",
        "media_type": "photo",
        "date": "2024-06-15T10:30:00",
        "lat": 37.77,
        "lon": -122.42,
        "albums": ["Vacation"],
        "labels": ["beach"],
        "persons": ["Alice"],
        "width": 1920,
        "height": 1080,
        "duration": None,
        "description": {"summary": "A sunny beach", "quality_score": 8},
        "embedding": None,
        "quality_score": 8.0,
    }
    rec.update(overrides)
    return rec


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    """Point config.DB_PATH at a temporary SQLite file for every test."""
    db_file = tmp_path / "test_media.db"
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr(store, "DB_PATH", db_file)
    store.init_db()
    return db_file


def _random_embedding(dim=512, rng=None):
    if rng is None:
        rng = np.random.default_rng(42)
    vec = rng.standard_normal(dim).astype(np.float32)
    vec /= np.linalg.norm(vec)
    return vec


def _make_known_embedding(value=1.0, dim=512):
    vec = np.zeros(dim, dtype=np.float32)
    vec[0] = value
    vec /= np.linalg.norm(vec)
    return vec


TEST_RES = (160, 90)
TEST_FPS = 10


# ═══════════════════════════════════════════════════════════════════════════
# STORE EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════


class TestStoreEdgeCases:
    """Edge cases for index/store.py."""

    def test_upsert_media_with_none_embedding(self):
        """upsert_media with None embedding should store NULL, not crash."""
        rec = _make_media_record("none-emb", embedding=None)
        store.upsert_media(rec)
        rows = store.get_media_by_uuids(["none-emb"])
        assert len(rows) == 1
        assert rows[0]["embedding"] is None

    def test_upsert_media_with_empty_lists(self):
        """upsert_media with empty albums/labels/persons."""
        rec = _make_media_record("empty-lists", albums=[], labels=[], persons=[])
        store.upsert_media(rec)
        rows = store.get_media_by_uuids(["empty-lists"])
        assert len(rows) == 1
        assert rows[0]["albums"] == []
        assert rows[0]["labels"] == []
        assert rows[0]["persons"] == []

    def test_upsert_media_with_very_long_summary(self):
        """upsert_media with a 10000-character summary should not crash."""
        long_summary = "A" * 10000
        rec = _make_media_record(
            "long-summary",
            description={"summary": long_summary, "quality_score": 5},
        )
        store.upsert_media(rec)
        rows = store.get_media_by_uuids(["long-summary"])
        assert len(rows) == 1
        assert len(rows[0]["description"]["summary"]) == 10000

    def test_search_by_text_with_only_null_embeddings(self):
        """search_by_text on DB with only NULL embeddings returns empty."""
        store.upsert_media(_make_media_record("null-1", embedding=None))
        store.upsert_media(_make_media_record("null-2", embedding=None))
        query = _make_known_embedding()
        results = store.search_by_text(query, limit=10)
        assert results == []

    def test_search_by_metadata_all_filters_none(self):
        """search_by_metadata with all filters None returns all records."""
        store.upsert_media(_make_media_record("m1"))
        store.upsert_media(_make_media_record("m2"))
        store.upsert_media(_make_media_record("m3"))
        results = store.search_by_metadata(
            albums=None, persons=None, date_range=None, min_quality=None,
        )
        uuids = {r["uuid"] for r in results}
        assert uuids == {"m1", "m2", "m3"}

    def test_concurrent_writes(self):
        """Insert 100 records rapidly via threads, verify all stored."""
        records = [_make_media_record(f"conc-{i}") for i in range(100)]

        def insert(rec):
            store.upsert_media(rec)

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(insert, records))

        all_uuids = {f"conc-{i}" for i in range(100)}
        rows = store.get_media_by_uuids(list(all_uuids))
        stored_uuids = {r["uuid"] for r in rows}
        assert stored_uuids == all_uuids

    def test_get_media_by_uuids_data_integrity(self):
        """get_media_by_uuids preserves all fields."""
        emb = _make_known_embedding()
        rec = _make_media_record(
            "integrity-1",
            path="/special/path.jpg",
            media_type="video",
            date="2023-01-15T08:00:00",
            lat=51.5,
            lon=-0.12,
            albums=["London", "Travel"],
            labels=["city", "landmark"],
            persons=["Charlie", "Dana"],
            width=3840,
            height=2160,
            duration=12.5,
            description={"summary": "Big Ben at dusk", "quality_score": 9},
            embedding=emb,
            quality_score=9.0,
        )
        store.upsert_media(rec)
        rows = store.get_media_by_uuids(["integrity-1"])
        assert len(rows) == 1
        row = rows[0]
        assert row["uuid"] == "integrity-1"
        assert row["path"] == "/special/path.jpg"
        assert row["media_type"] == "video"
        assert row["date"] == "2023-01-15T08:00:00"
        assert row["lat"] == 51.5
        assert row["lon"] == -0.12
        assert row["albums"] == ["London", "Travel"]
        assert row["labels"] == ["city", "landmark"]
        assert row["persons"] == ["Charlie", "Dana"]
        assert row["width"] == 3840
        assert row["height"] == 2160
        assert row["duration"] == 12.5
        assert row["description"]["summary"] == "Big Ben at dusk"
        assert row["quality_score"] == 9.0
        np.testing.assert_allclose(row["embedding"], emb, atol=1e-6)


# ═══════════════════════════════════════════════════════════════════════════
# SEARCH EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════


class TestSearchEdgeCases:
    """Edge cases for curate/search.py."""

    @patch("curate.search.clip_embeddings.embed_text")
    def test_hybrid_search_empty_string_query(self, mock_embed):
        """hybrid_search with empty string query should not crash."""
        mock_embed.return_value = _make_known_embedding()
        emb = _make_known_embedding()
        store.upsert_media(_make_media_record("s1", embedding=emb))
        results = hybrid_search("")
        # Should return results (the embedding still works on "")
        assert isinstance(results, list)

    @patch("curate.search.clip_embeddings.embed_text")
    def test_hybrid_search_very_long_query(self, mock_embed):
        """hybrid_search with a 1000-char query should not crash."""
        mock_embed.return_value = _make_known_embedding()
        emb = _make_known_embedding()
        store.upsert_media(_make_media_record("s2", embedding=emb))
        long_query = "beach " * 167  # ~1002 chars
        results = hybrid_search(long_query)
        assert isinstance(results, list)

    def test_find_similar_single_item_in_db(self):
        """find_similar when only 1 item in DB should return empty."""
        emb = _make_known_embedding()
        store.upsert_media(_make_media_record("only-one", embedding=emb))
        results = find_similar("only-one", limit=5)
        # Cannot find similar items to self - should exclude self
        assert all(r["uuid"] != "only-one" for r in results)
        assert results == []

    @patch("curate.search.clip_embeddings.embed_text")
    def test_hybrid_search_limit_zero(self, mock_embed):
        """hybrid_search with limit=0 returns empty."""
        mock_embed.return_value = _make_known_embedding()
        emb = _make_known_embedding()
        store.upsert_media(_make_media_record("lz", embedding=emb))
        results = hybrid_search("test", limit=0)
        assert results == []

    @patch("curate.search.clip_embeddings.embed_text")
    def test_hybrid_search_result_count_never_exceeds_limit(self, mock_embed):
        """hybrid_search result count never exceeds limit."""
        mock_embed.return_value = _make_known_embedding()
        rng = np.random.default_rng(0)
        for i in range(20):
            emb = _random_embedding(rng=rng)
            store.upsert_media(_make_media_record(f"lim-{i}", embedding=emb))
        for limit in [1, 3, 5, 10]:
            results = hybrid_search("test", limit=limit)
            assert len(results) <= limit


# ═══════════════════════════════════════════════════════════════════════════
# DIRECTOR EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════


class TestDirectorEdgeCases:
    """Edge cases for curate/director.py."""

    def _make_candidates(self):
        return [
            _make_media_record("u1", path="/media/u1.jpg"),
            _make_media_record("u2", path="/media/u2.jpg"),
        ]

    def test_parse_response_empty_json_object(self):
        """_parse_response with empty JSON {} returns empty EDL."""
        candidates = self._make_candidates()
        edl = _parse_response("{}", candidates)
        assert isinstance(edl, EditDecisionList)
        assert edl.shots == []
        assert edl.estimated_duration == 0.0

    def test_parse_response_shots_missing_fields(self):
        """_parse_response with shots that have missing fields."""
        candidates = self._make_candidates()
        data = {
            "title": "Test",
            "shots": [
                {"uuid": "u1"},  # missing path, media_type, start_time, etc.
            ],
        }
        edl = _parse_response(json.dumps(data), candidates)
        assert len(edl.shots) == 1
        shot = edl.shots[0]
        # Should use defaults / fallback from candidates
        assert shot.uuid == "u1"
        assert shot.path == "/media/u1.jpg"  # from path_lookup
        assert shot.media_type == "photo"  # default
        assert shot.start_time == 0.0
        assert shot.end_time == 0.0

    def test_validate_empty_shots(self):
        """_validate with empty shots list."""
        candidates = self._make_candidates()
        edl = EditDecisionList(shots=[])
        validated = _validate(edl, candidates, 30.0)
        assert validated.shots == []
        assert validated.estimated_duration == 0.0

    def test_validate_all_unknown_uuids(self):
        """_validate with all shots having unknown UUIDs returns empty."""
        candidates = self._make_candidates()
        edl = EditDecisionList(
            shots=[
                Shot("unknown-1", "/x.jpg", "photo", 0, 3, "opener", "r"),
                Shot("unknown-2", "/y.jpg", "photo", 3, 6, "b-roll", "r"),
            ],
        )
        validated = _validate(edl, candidates, 30.0)
        assert validated.shots == []

    def test_validate_target_duration_zero(self):
        """_validate with target_duration=0 should not divide by zero."""
        candidates = self._make_candidates()
        edl = EditDecisionList(
            shots=[Shot("u1", "/u1.jpg", "photo", 0, 3, "opener", "r")],
        )
        # Should not raise ZeroDivisionError
        validated = _validate(edl, candidates, 0.0)
        assert len(validated.shots) == 1

    def test_build_manifest_missing_keys(self):
        """_build_manifest with candidates that have missing keys."""
        candidates = [
            {"uuid": "m1"},  # minimal - no description, labels, etc.
            {"uuid": "m2", "media_type": "video"},
        ]
        manifest = _build_manifest(candidates)
        assert len(manifest) == 2
        # Should use defaults for missing keys
        assert manifest[0]["media_type"] == "photo"  # default
        assert manifest[0]["description"] == ""
        assert manifest[0]["persons"] == []
        assert manifest[0]["labels"] == []
        assert manifest[1]["media_type"] == "video"


# ═══════════════════════════════════════════════════════════════════════════
# ASSEMBLY EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════


class TestAssemblyEdgeCases:
    """Edge cases for assemble/themes.py and assemble/builder.py."""

    def test_apply_ken_burns_very_small_image(self, tmp_path):
        """apply_ken_burns with a 10x10 pixel image."""
        path = tmp_path / "tiny.jpg"
        Image.new("RGB", (10, 10), color=(128, 128, 128)).save(str(path))
        clip = apply_ken_burns(str(path), duration=1.0, fps=TEST_FPS, resolution=TEST_RES)
        assert abs(clip.duration - 1.0) < 0.01
        frame = clip.get_frame(0.5)
        assert frame.shape == (TEST_RES[1], TEST_RES[0], 3)

    def test_apply_ken_burns_panoramic_image(self, tmp_path):
        """apply_ken_burns with a very wide panoramic image (5000x500)."""
        path = tmp_path / "pano.jpg"
        Image.new("RGB", (5000, 500), color=(100, 150, 200)).save(str(path))
        clip = apply_ken_burns(str(path), duration=2.0, fps=TEST_FPS, resolution=TEST_RES)
        assert abs(clip.duration - 2.0) < 0.01
        frame = clip.get_frame(1.0)
        assert frame.shape == (TEST_RES[1], TEST_RES[0], 3)
        assert frame.min() >= 0
        assert frame.max() <= 255

    def test_warm_filter_all_black_pixels(self):
        """_warm_filter with all-black pixels should not go negative."""
        frame = np.zeros((5, 5, 3), dtype=np.uint8)
        result = _warm_filter(frame)
        assert result.min() >= 0
        assert result.dtype == np.uint8
        # All zeros multiplied by any factor should remain zero
        np.testing.assert_array_equal(result, 0)

    def test_warm_filter_all_white_pixels(self):
        """_warm_filter with all-white pixels should clamp to 255."""
        frame = np.full((5, 5, 3), 255, dtype=np.uint8)
        result = _warm_filter(frame)
        assert result.max() <= 255
        assert result.dtype == np.uint8
        # Red: 255*1.08=275.4 -> clamped to 255
        assert result[0, 0, 0] == 255
        # Green: 255*1.04=265.2 -> clamped to 255
        assert result[0, 0, 1] == 255
        # Blue: 255*0.92=234.6 -> 234
        assert result[0, 0, 2] == 234

    def test_build_video_single_shot(self, tmp_path):
        """build_video with a single shot (no transitions needed)."""
        img_path = tmp_path / "single.jpg"
        Image.new("RGB", (100, 100), color=(255, 0, 0)).save(str(img_path))

        shots = [
            Shot("s1", str(img_path), "photo", 0.0, 3.0, "opener", "test"),
        ]
        edl = EditDecisionList(
            shots=shots,
            title="Single Shot",
            narrative_summary="One shot.",
            estimated_duration=3.0,
            music_mood="calm",
        )

        output = str(tmp_path / "single_output.mp4")

        orig_res = config.DEFAULT_OUTPUT_RESOLUTION
        orig_fps = config.DEFAULT_OUTPUT_FPS
        orig_photo = config.DEFAULT_PHOTO_DURATION
        orig_trans = config.DEFAULT_TRANSITION_DURATION
        try:
            config.DEFAULT_OUTPUT_RESOLUTION = TEST_RES
            config.DEFAULT_OUTPUT_FPS = TEST_FPS
            config.DEFAULT_PHOTO_DURATION = 1.0
            config.DEFAULT_TRANSITION_DURATION = 0.3
            result = build_video(edl, theme_name="minimal", output_path=output)
        finally:
            config.DEFAULT_OUTPUT_RESOLUTION = orig_res
            config.DEFAULT_OUTPUT_FPS = orig_fps
            config.DEFAULT_PHOTO_DURATION = orig_photo
            config.DEFAULT_TRANSITION_DURATION = orig_trans

        assert os.path.exists(result)
        assert os.path.getsize(result) > 0

    def test_build_video_empty_string_paths(self, tmp_path):
        """build_video with shots that have empty string paths raises RuntimeError."""
        shots = [
            Shot("e1", "", "photo", 0.0, 3.0, "opener", "test"),
            Shot("e2", "", "photo", 3.0, 6.0, "closer", "test"),
        ]
        edl = EditDecisionList(
            shots=shots,
            title="Empty Paths",
            narrative_summary="Should fail.",
            estimated_duration=6.0,
            music_mood="calm",
        )

        orig_res = config.DEFAULT_OUTPUT_RESOLUTION
        orig_fps = config.DEFAULT_OUTPUT_FPS
        try:
            config.DEFAULT_OUTPUT_RESOLUTION = TEST_RES
            config.DEFAULT_OUTPUT_FPS = TEST_FPS
            with pytest.raises(RuntimeError, match="No valid shots"):
                build_video(edl, theme_name="minimal",
                            output_path=str(tmp_path / "empty_paths.mp4"))
        finally:
            config.DEFAULT_OUTPUT_RESOLUTION = orig_res
            config.DEFAULT_OUTPUT_FPS = orig_fps

    def test_create_title_card_empty_title(self):
        """_create_title_card with empty title string."""
        from moviepy import CompositeVideoClip
        card = _create_title_card("", MINIMAL, 2.0, TEST_RES, TEST_FPS)
        assert isinstance(card, CompositeVideoClip)
        assert abs(card.duration - 2.0) < 0.01

    def test_create_title_card_very_long_title(self):
        """_create_title_card with a 500-char title string."""
        from moviepy import CompositeVideoClip
        long_title = "A" * 500
        card = _create_title_card(long_title, MINIMAL, 2.0, TEST_RES, TEST_FPS)
        assert isinstance(card, CompositeVideoClip)
        assert abs(card.duration - 2.0) < 0.01

    def test_prepare_music_longer_than_video(self, tmp_path):
        """_prepare_music with music longer than video should trim, not loop."""
        # Create a 2-second audio file
        audio_path = tmp_path / "long_music.wav"
        sample_rate = 44100
        duration = 2.0
        n_samples = int(sample_rate * duration)
        samples = []
        for i in range(n_samples):
            t = i / sample_rate
            value = int(32767 * 0.5 * np.sin(2 * np.pi * 440.0 * t))
            samples.append(struct.pack("<h", value))
        with wave.open(str(audio_path), "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(b"".join(samples))

        # Request trimming to 1 second (shorter than the 2-second audio)
        video_duration = 1.0
        audio_clip = _prepare_music(str(audio_path), video_duration, volume=0.3)
        assert audio_clip is not None
        # Duration should be trimmed to video_duration
        assert abs(audio_clip.duration - video_duration) < 0.1


# ═══════════════════════════════════════════════════════════════════════════
# CLI EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════


class TestCLIEdgeCases:
    """Edge cases for main.py CLI commands."""

    def test_cmd_stats_with_empty_db(self, _tmp_db, capsys):
        """cmd_stats with a fresh/empty DB file should not crash."""
        from main import cmd_stats
        args = SimpleNamespace(command="stats")
        cmd_stats(args)
        captured = capsys.readouterr()
        assert "Indexed media: 0" in captured.out

    def test_cmd_stats_with_corrupted_db(self, _tmp_db, tmp_path, monkeypatch, capsys):
        """cmd_stats with a corrupted DB file should handle error gracefully."""
        # Write garbage to the DB file
        corrupted_db = tmp_path / "corrupted.db"
        corrupted_db.write_text("this is not a valid sqlite db")
        monkeypatch.setattr(config, "DB_PATH", corrupted_db)
        monkeypatch.setattr(store, "DB_PATH", corrupted_db)

        from main import cmd_stats
        args = SimpleNamespace(command="stats")
        # This should raise an error since the DB is corrupted
        with pytest.raises(Exception):
            cmd_stats(args)

    @patch("curate.search.clip_embeddings.embed_text")
    def test_cmd_search_special_characters(self, mock_embed, _tmp_db, capsys):
        """cmd_search with special characters in query should not crash."""
        mock_embed.return_value = _make_known_embedding()

        from main import cmd_search
        args = SimpleNamespace(
            command="search",
            query="test's \"quote\" & <html> $pecial (chars) [brackets]",
            albums=None,
            persons=None,
            min_quality=None,
            limit=10,
            fast=False,
        )
        # Should not raise
        cmd_search(args)
        captured = capsys.readouterr()
        assert "Searching for" in captured.out
