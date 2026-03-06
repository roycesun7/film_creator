"""Tests for library management (delete) and fast text search (search_by_description)."""

from __future__ import annotations

import argparse
import importlib
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


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


# ═══════════════════════════════════════════════════════════════════════════
# delete_media tests
# ═══════════════════════════════════════════════════════════════════════════

class TestDeleteMedia:
    """delete_media removes a single record and returns correct status."""

    def test_delete_existing_record(self, tmp_db):
        store = _reload_store()
        store.init_db()

        store.upsert_media(_make_media_record("del-1"))
        store.upsert_media(_make_media_record("del-2"))

        result = store.delete_media("del-1")
        assert result is True

        # Verify it's actually gone
        remaining = store.get_media_by_uuids(["del-1"])
        assert len(remaining) == 0

        # Other record still exists
        remaining = store.get_media_by_uuids(["del-2"])
        assert len(remaining) == 1

    def test_delete_unknown_uuid_returns_false(self, tmp_db):
        store = _reload_store()
        store.init_db()

        store.upsert_media(_make_media_record("exists-1"))
        result = store.delete_media("nonexistent-uuid")
        assert result is False


# ═══════════════════════════════════════════════════════════════════════════
# delete_all_media tests
# ═══════════════════════════════════════════════════════════════════════════

class TestDeleteAllMedia:
    """delete_all_media removes all records and returns correct count."""

    def test_delete_all_returns_count(self, tmp_db):
        store = _reload_store()
        store.init_db()

        store.upsert_media(_make_media_record("all-1"))
        store.upsert_media(_make_media_record("all-2"))
        store.upsert_media(_make_media_record("all-3"))

        count = store.delete_all_media()
        assert count == 3

        # DB should be empty
        remaining = store.count_media()
        assert remaining == 0

    def test_delete_all_empty_db(self, tmp_db):
        store = _reload_store()
        store.init_db()

        count = store.delete_all_media()
        assert count == 0


# ═══════════════════════════════════════════════════════════════════════════
# count_media tests
# ═══════════════════════════════════════════════════════════════════════════

class TestCountMedia:
    """count_media returns accurate count."""

    def test_count_empty(self, tmp_db):
        store = _reload_store()
        store.init_db()
        assert store.count_media() == 0

    def test_count_after_inserts(self, tmp_db):
        store = _reload_store()
        store.init_db()

        store.upsert_media(_make_media_record("cnt-1"))
        store.upsert_media(_make_media_record("cnt-2"))
        assert store.count_media() == 2

    def test_count_after_delete(self, tmp_db):
        store = _reload_store()
        store.init_db()

        store.upsert_media(_make_media_record("cnt-1"))
        store.upsert_media(_make_media_record("cnt-2"))
        store.delete_media("cnt-1")
        assert store.count_media() == 1


# ═══════════════════════════════════════════════════════════════════════════
# search_by_description tests
# ═══════════════════════════════════════════════════════════════════════════

class TestSearchByDescription:
    """search_by_description performs full-text search over descriptions, labels, persons."""

    def _seed(self, store):
        store.init_db()
        store.upsert_media(_make_media_record(
            "desc-1",
            description={"summary": "A beautiful sunset at the beach"},
            labels=["sunset", "beach", "ocean"],
            persons=["Alice"],
        ))
        store.upsert_media(_make_media_record(
            "desc-2",
            description={"summary": "Mountain hiking trail with wildflowers"},
            labels=["mountain", "hiking", "flowers"],
            persons=["Bob"],
        ))
        store.upsert_media(_make_media_record(
            "desc-3",
            description={"summary": "Birthday party celebration"},
            labels=["party", "cake", "balloons"],
            persons=["Alice", "Bob"],
        ))

    def test_finds_by_summary_text(self, tmp_db):
        store = _reload_store()
        self._seed(store)

        results = store.search_by_description("sunset")
        uuids = [r["uuid"] for r in results]
        assert "desc-1" in uuids

    def test_finds_by_label_text(self, tmp_db):
        store = _reload_store()
        self._seed(store)

        results = store.search_by_description("hiking")
        uuids = [r["uuid"] for r in results]
        assert "desc-2" in uuids

    def test_finds_by_person_name(self, tmp_db):
        store = _reload_store()
        self._seed(store)

        results = store.search_by_description("Bob")
        uuids = [r["uuid"] for r in results]
        assert "desc-2" in uuids
        assert "desc-3" in uuids

    def test_ranks_by_word_match_count(self, tmp_db):
        store = _reload_store()
        self._seed(store)

        # "sunset beach" should rank desc-1 highest (matches both words in
        # description + labels)
        results = store.search_by_description("sunset beach")
        assert len(results) > 0
        assert results[0]["uuid"] == "desc-1"
        # desc-1 should have higher relevance than others
        if len(results) > 1:
            assert results[0]["relevance_score"] >= results[1]["relevance_score"]

    def test_no_matches_returns_empty(self, tmp_db):
        store = _reload_store()
        self._seed(store)

        results = store.search_by_description("xyznonexistent")
        assert results == []

    def test_case_insensitive(self, tmp_db):
        store = _reload_store()
        self._seed(store)

        results_lower = store.search_by_description("sunset")
        results_upper = store.search_by_description("SUNSET")
        results_mixed = store.search_by_description("SuNsEt")

        uuids_lower = {r["uuid"] for r in results_lower}
        uuids_upper = {r["uuid"] for r in results_upper}
        uuids_mixed = {r["uuid"] for r in results_mixed}

        assert uuids_lower == uuids_upper == uuids_mixed


# ═══════════════════════════════════════════════════════════════════════════
# CLI delete tests
# ═══════════════════════════════════════════════════════════════════════════

class TestCLIDelete:
    """CLI-level delete command tests."""

    def test_delete_partial_uuid_match(self, tmp_db):
        store = _reload_store()
        store.init_db()

        full_uuid = "ABCDEF12-3456-7890-ABCD-EF1234567890"
        store.upsert_media(_make_media_record(full_uuid))

        # Call cmd_delete with a partial UUID
        from main import cmd_delete
        args = argparse.Namespace(
            command="delete",
            uuid="ABCDEF12",
            all=False,
            album=None,
            yes=True,
        )
        cmd_delete(args)

        # Should be deleted
        remaining = store.get_media_by_uuids([full_uuid])
        assert len(remaining) == 0

    def test_delete_all_requires_yes(self, tmp_db, capsys):
        store = _reload_store()
        store.init_db()

        store.upsert_media(_make_media_record("keep-1"))
        store.upsert_media(_make_media_record("keep-2"))

        from main import cmd_delete

        # Without --yes and with EOFError on input (no interactive terminal)
        args = argparse.Namespace(
            command="delete",
            uuid=None,
            all=True,
            album=None,
            yes=False,
        )

        # Simulate non-interactive (EOFError on input)
        with patch("builtins.input", side_effect=EOFError):
            cmd_delete(args)

        # Items should still exist (not deleted)
        assert store.count_media() == 2

        captured = capsys.readouterr()
        assert "Aborted" in captured.out

    def test_delete_all_with_yes_flag(self, tmp_db, capsys):
        store = _reload_store()
        store.init_db()

        store.upsert_media(_make_media_record("gone-1"))
        store.upsert_media(_make_media_record("gone-2"))

        from main import cmd_delete
        args = argparse.Namespace(
            command="delete",
            uuid=None,
            all=True,
            album=None,
            yes=True,
        )
        cmd_delete(args)

        assert store.count_media() == 0
        captured = capsys.readouterr()
        assert "Deleted 2" in captured.out
