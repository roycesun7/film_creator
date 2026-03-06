"""Tests for the indexing layer: store, clip_embeddings, vision_describe, apple_photos."""

from __future__ import annotations

import importlib
import json
import sqlite3
import sys
from datetime import datetime
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


# ═══════════════════════════════════════════════════════════════════════════
# Helper: reload store module so it picks up the patched config.DB_PATH
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


# ═══════════════════════════════════════════════════════════════════════════
# STORE.PY TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestInitDb:
    """init_db creates the media table and expected indexes."""

    def test_creates_table_and_indexes(self, tmp_db):
        store = _reload_store()
        store.init_db()

        conn = sqlite3.connect(str(tmp_db))
        # Table exists
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='media'"
        ).fetchall()
        assert len(tables) == 1

        # Indexes exist
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        idx_names = {row[0] for row in indexes}
        assert "idx_media_date" in idx_names
        assert "idx_media_quality" in idx_names
        conn.close()


class TestUpsertMedia:
    """upsert_media inserts and updates records correctly."""

    def test_insert_and_read_back(self, tmp_db):
        store = _reload_store()
        store.init_db()

        rec = _make_media_record("uuid-1")
        store.upsert_media(rec)

        rows = store.get_media_by_uuids(["uuid-1"])
        assert len(rows) == 1
        assert rows[0]["uuid"] == "uuid-1"
        assert rows[0]["path"] == "/fake/uuid-1.jpg"
        assert rows[0]["media_type"] == "photo"

    def test_upsert_updates_on_conflict(self, tmp_db):
        store = _reload_store()
        store.init_db()

        rec1 = _make_media_record("uuid-1", quality_score=5.0)
        store.upsert_media(rec1)

        rec2 = _make_media_record(
            "uuid-1",
            path="/updated/path.jpg",
            quality_score=9.5,
            albums=["Updated"],
        )
        store.upsert_media(rec2)

        rows = store.get_media_by_uuids(["uuid-1"])
        assert len(rows) == 1
        assert rows[0]["path"] == "/updated/path.jpg"
        assert rows[0]["quality_score"] == 9.5
        assert rows[0]["albums"] == ["Updated"]


class TestSearchByText:
    """search_by_text ranks results by cosine similarity."""

    def test_cosine_similarity_ordering(self, tmp_db):
        store = _reload_store()
        store.init_db()

        # Create three fake normalised embeddings with known dot-products
        dim = 512
        # query vector: unit vector along first axis
        query = np.zeros(dim, dtype=np.float32)
        query[0] = 1.0

        # emb_a: perfectly aligned (similarity=1)
        emb_a = np.zeros(dim, dtype=np.float32)
        emb_a[0] = 1.0

        # emb_b: partially aligned (similarity~0.707)
        emb_b = np.zeros(dim, dtype=np.float32)
        emb_b[0] = 1.0
        emb_b[1] = 1.0
        emb_b /= np.linalg.norm(emb_b)

        # emb_c: orthogonal (similarity=0)
        emb_c = np.zeros(dim, dtype=np.float32)
        emb_c[2] = 1.0

        store.upsert_media(_make_media_record("a", embedding=emb_a))
        store.upsert_media(_make_media_record("b", embedding=emb_b))
        store.upsert_media(_make_media_record("c", embedding=emb_c))

        results = store.search_by_text(query, limit=10)
        assert len(results) == 3

        uuids_ordered = [r["uuid"] for r in results]
        assert uuids_ordered == ["a", "b", "c"]

        # Check similarity scores are monotonically decreasing
        sims = [r["similarity"] for r in results]
        assert sims[0] > sims[1] > sims[2]
        assert abs(sims[0] - 1.0) < 1e-5
        assert abs(sims[2] - 0.0) < 1e-5


class TestSearchByMetadata:
    """search_by_metadata filters by date_range, albums, persons, min_quality."""

    def _seed(self, store):
        store.init_db()
        store.upsert_media(_make_media_record(
            "m1", date="2024-01-01T00:00:00", albums=["Trip"], persons=["Alice"],
            quality_score=9.0,
        ))
        store.upsert_media(_make_media_record(
            "m2", date="2024-06-15T00:00:00", albums=["Wedding"], persons=["Bob"],
            quality_score=6.0,
        ))
        store.upsert_media(_make_media_record(
            "m3", date="2024-12-31T00:00:00", albums=["Trip"], persons=["Bob"],
            quality_score=3.0,
        ))

    def test_filter_by_date_range(self, tmp_db):
        store = _reload_store()
        self._seed(store)

        results = store.search_by_metadata(
            date_range=("2024-05-01T00:00:00", "2024-08-01T00:00:00"),
        )
        uuids = {r["uuid"] for r in results}
        assert uuids == {"m2"}

    def test_filter_by_albums(self, tmp_db):
        store = _reload_store()
        self._seed(store)

        results = store.search_by_metadata(albums=["Trip"])
        uuids = {r["uuid"] for r in results}
        assert uuids == {"m1", "m3"}

    def test_filter_by_persons(self, tmp_db):
        store = _reload_store()
        self._seed(store)

        results = store.search_by_metadata(persons=["Alice"])
        uuids = {r["uuid"] for r in results}
        assert uuids == {"m1"}

    def test_filter_by_min_quality(self, tmp_db):
        store = _reload_store()
        self._seed(store)

        results = store.search_by_metadata(min_quality=7.0)
        uuids = {r["uuid"] for r in results}
        assert uuids == {"m1"}

    def test_combined_filters(self, tmp_db):
        store = _reload_store()
        self._seed(store)

        results = store.search_by_metadata(
            albums=["Trip"],
            min_quality=5.0,
        )
        uuids = {r["uuid"] for r in results}
        assert uuids == {"m1"}


class TestGetAllEmbeddings:
    """get_all_embeddings returns correct shape and only records with embeddings."""

    def test_returns_correct_shape(self, tmp_db):
        store = _reload_store()
        store.init_db()

        dim = 512
        emb1 = np.random.randn(dim).astype(np.float32)
        emb1 /= np.linalg.norm(emb1)
        emb2 = np.random.randn(dim).astype(np.float32)
        emb2 /= np.linalg.norm(emb2)

        store.upsert_media(_make_media_record("e1", embedding=emb1))
        store.upsert_media(_make_media_record("e2", embedding=emb2))
        # Record without embedding
        store.upsert_media(_make_media_record("e3", embedding=None))

        uuids, matrix = store.get_all_embeddings()
        assert len(uuids) == 2
        assert matrix.shape == (2, dim)
        assert set(uuids) == {"e1", "e2"}

    def test_empty_db_returns_empty(self, tmp_db):
        store = _reload_store()
        store.init_db()

        uuids, matrix = store.get_all_embeddings()
        assert len(uuids) == 0
        assert matrix.shape == (0, 512)


class TestGetMediaByUuids:
    """get_media_by_uuids returns correct records and handles edge cases."""

    def test_returns_correct_records(self, tmp_db):
        store = _reload_store()
        store.init_db()

        store.upsert_media(_make_media_record("r1"))
        store.upsert_media(_make_media_record("r2"))
        store.upsert_media(_make_media_record("r3"))

        results = store.get_media_by_uuids(["r1", "r3"])
        uuids = {r["uuid"] for r in results}
        assert uuids == {"r1", "r3"}

    def test_handles_empty_list(self, tmp_db):
        store = _reload_store()
        store.init_db()

        results = store.get_media_by_uuids([])
        assert results == []

    def test_handles_unknown_uuids(self, tmp_db):
        store = _reload_store()
        store.init_db()

        results = store.get_media_by_uuids(["nonexistent-uuid"])
        assert results == []


class TestJsonSerialization:
    """JSON roundtrip for albums, labels, persons, description."""

    def test_roundtrip(self, tmp_db):
        store = _reload_store()
        store.init_db()

        albums = ["Vacation", "Family Photos"]
        labels = ["beach", "sunset", "ocean"]
        persons = ["Alice", "Bob"]
        description = {
            "summary": "A beautiful sunset at the beach",
            "subjects": ["sunset", "ocean"],
            "quality_score": 9,
        }

        rec = _make_media_record(
            "json-1",
            albums=albums,
            labels=labels,
            persons=persons,
            description=description,
        )
        store.upsert_media(rec)

        rows = store.get_media_by_uuids(["json-1"])
        assert len(rows) == 1
        row = rows[0]
        assert row["albums"] == albums
        assert row["labels"] == labels
        assert row["persons"] == persons
        assert row["description"] == description


# ═══════════════════════════════════════════════════════════════════════════
# CLIP_EMBEDDINGS.PY TESTS
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.slow
class TestEmbedImage:
    """embed_image returns a normalised (512,) vector for a real image."""

    def test_single_image_shape_and_norm(self, test_images):
        from index.clip_embeddings import embed_image

        emb = embed_image(test_images["red"])
        assert emb.shape == (512,)
        assert abs(np.linalg.norm(emb) - 1.0) < 1e-4

    def test_different_images_produce_different_embeddings(self, test_images):
        from index.clip_embeddings import embed_image

        emb_red = embed_image(test_images["red"])
        emb_blue = embed_image(test_images["blue"])
        # Should not be identical
        assert not np.allclose(emb_red, emb_blue, atol=1e-3)


@pytest.mark.slow
class TestEmbedImages:
    """embed_images batch returns correct shapes."""

    def test_batch_shape(self, test_images):
        from index.clip_embeddings import embed_images

        paths = [test_images["red"], test_images["green"], test_images["blue"]]
        result = embed_images(paths)
        assert result.shape == (3, 512)

        # Each row should be L2-normalised
        norms = np.linalg.norm(result, axis=1)
        np.testing.assert_allclose(norms, 1.0, atol=1e-4)

    def test_empty_list(self):
        from index.clip_embeddings import embed_images

        result = embed_images([])
        assert result.shape == (0, 512)


@pytest.mark.slow
class TestEmbedText:
    """embed_text returns a normalised (512,) vector."""

    def test_text_embedding(self):
        from index.clip_embeddings import embed_text

        emb = embed_text("a sunny beach with palm trees")
        assert emb.shape == (512,)
        assert abs(np.linalg.norm(emb) - 1.0) < 1e-4

    def test_different_texts_produce_different_embeddings(self):
        from index.clip_embeddings import embed_text

        emb_a = embed_text("a cat sitting on a mat")
        emb_b = embed_text("a skyscraper in a modern city")
        assert not np.allclose(emb_a, emb_b, atol=1e-3)


# ═══════════════════════════════════════════════════════════════════════════
# VISION_DESCRIBE.PY TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestDescribeImage:
    """describe_image sends an image to Claude and parses the JSON response."""

    def _mock_response(self, text):
        """Build a fake Anthropic Message with a single TextBlock."""
        block = SimpleNamespace(text=text)
        return SimpleNamespace(content=[block])

    def test_valid_json_response(self, tmp_path):
        img_path = tmp_path / "test.jpg"
        Image.new("RGB", (10, 10), color="red").save(str(img_path))

        valid_json = json.dumps({
            "summary": "A red square",
            "subjects": ["red square"],
            "setting": "studio",
            "mood": "neutral",
            "colors": ["red"],
            "activity": "nothing",
            "quality_score": 7,
        })

        with patch("index.vision_describe._get_client") as mock_get:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = self._mock_response(valid_json)
            mock_get.return_value = mock_client

            from index.vision_describe import describe_image
            result = describe_image(str(img_path))

        assert result["summary"] == "A red square"
        assert result["quality_score"] == 7
        assert "subjects" in result
        assert "mood" in result

    def test_markdown_fenced_json(self, tmp_path):
        img_path = tmp_path / "test.jpg"
        Image.new("RGB", (10, 10), color="blue").save(str(img_path))

        fenced = '```json\n{"summary":"fenced","subjects":[],"setting":"x","mood":"y","colors":[],"activity":"z","quality_score":5}\n```'

        with patch("index.vision_describe._get_client") as mock_get:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = self._mock_response(fenced)
            mock_get.return_value = mock_client

            from index.vision_describe import describe_image
            result = describe_image(str(img_path))

        assert result["summary"] == "fenced"

    def test_malformed_json_returns_defaults(self, tmp_path):
        img_path = tmp_path / "test.jpg"
        Image.new("RGB", (10, 10), color="green").save(str(img_path))

        with patch("index.vision_describe._get_client") as mock_get:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = self._mock_response(
                "This is not JSON at all!"
            )
            mock_get.return_value = mock_client

            from index.vision_describe import describe_image
            result = describe_image(str(img_path))

        # When JSON parsing fails, summary is the raw text, quality_score defaults to 5
        assert result["quality_score"] == 5
        assert result["setting"] == "unknown"
        assert result["subjects"] == []


class TestDescribeImagesBatch:
    """describe_images_batch processes all images and handles failures."""

    def test_processes_all_images(self, tmp_path):
        paths = []
        for i in range(3):
            p = tmp_path / f"img{i}.jpg"
            Image.new("RGB", (10, 10)).save(str(p))
            paths.append(str(p))

        valid_json = json.dumps({
            "summary": "test",
            "subjects": [],
            "setting": "s",
            "mood": "m",
            "colors": [],
            "activity": "a",
            "quality_score": 6,
        })

        with patch("index.vision_describe._get_client") as mock_get:
            mock_client = MagicMock()
            block = SimpleNamespace(text=valid_json)
            mock_client.messages.create.return_value = SimpleNamespace(content=[block])
            mock_get.return_value = mock_client

            from index.vision_describe import describe_images_batch
            results = describe_images_batch(paths, batch_size=2)

        assert len(results) == 3
        assert all(r["summary"] == "test" for r in results)

    def test_handles_failures_gracefully(self, tmp_path):
        paths = []
        for i in range(2):
            p = tmp_path / f"img{i}.jpg"
            Image.new("RGB", (10, 10)).save(str(p))
            paths.append(str(p))

        with patch("index.vision_describe.describe_image") as mock_desc:
            mock_desc.side_effect = [
                {"summary": "ok", "subjects": [], "setting": "s", "mood": "m",
                 "colors": [], "activity": "a", "quality_score": 7},
                Exception("API error"),
            ]

            from index.vision_describe import describe_images_batch
            results = describe_images_batch(paths, batch_size=10)

        assert len(results) == 2
        assert results[0]["summary"] == "ok"
        # Second result should be the fallback
        assert results[1]["summary"] == "Description failed"
        assert results[1]["quality_score"] == 5


# ═══════════════════════════════════════════════════════════════════════════
# APPLE_PHOTOS.PY TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestMediaItemDataclass:
    """MediaItem dataclass creation and defaults."""

    def test_creation(self, sample_media_item):
        mi = sample_media_item
        assert mi.uuid == "AAAA-BBBB-CCCC-DDDD"
        assert mi.media_type == "photo"
        assert mi.location == (37.7749, -122.4194)
        assert "Vacation" in mi.albums
        assert mi.duration is None
        assert mi.keyframe_paths == []

    def test_defaults(self):
        from index.apple_photos import MediaItem

        mi = MediaItem(
            uuid="test",
            path=None,
            media_type="photo",
            date=None,
            location=None,
        )
        assert mi.albums == []
        assert mi.labels == []
        assert mi.persons == []
        assert mi.width == 0
        assert mi.height == 0
        assert mi.keyframe_paths == []


class TestGetMediaItems:
    """get_media_items queries PhotosDB and returns MediaItem list."""

    def _make_mock_photo(self, uuid, date=None, is_movie=False, album="TestAlbum"):
        photo = MagicMock()
        photo.uuid = uuid
        photo.ismovie = is_movie
        photo.date = date
        photo.latitude = 40.0
        photo.longitude = -74.0
        photo.albums = [album]
        photo.labels = []
        photo.persons = ["TestPerson"]
        photo.width = 1920
        photo.height = 1080
        photo.duration = 10.0 if is_movie else None
        photo.path = f"/fake/{uuid}.jpg"
        return photo

    @patch("index.apple_photos.osxphotos")
    def test_returns_media_items(self, mock_osxphotos):
        mock_db = MagicMock()
        mock_osxphotos.PhotosDB.return_value = mock_db

        photos = [
            self._make_mock_photo("u1", date=datetime(2024, 1, 1)),
            self._make_mock_photo("u2", date=datetime(2024, 6, 1)),
        ]
        mock_db.photos.return_value = photos

        from index.apple_photos import get_media_items
        items = get_media_items()

        assert len(items) == 2
        assert items[0].uuid == "u1"
        assert items[1].uuid == "u2"

    @patch("index.apple_photos.osxphotos")
    def test_date_range_filtering(self, mock_osxphotos):
        mock_db = MagicMock()
        mock_osxphotos.PhotosDB.return_value = mock_db

        photos = [
            self._make_mock_photo("u1", date=datetime(2024, 1, 1)),
            self._make_mock_photo("u2", date=datetime(2024, 6, 15)),
            self._make_mock_photo("u3", date=datetime(2024, 12, 1)),
        ]
        mock_db.photos.return_value = photos

        from index.apple_photos import get_media_items
        items = get_media_items(
            date_range=(datetime(2024, 5, 1), datetime(2024, 7, 1)),
        )

        assert len(items) == 1
        assert items[0].uuid == "u2"

    @patch("index.apple_photos.osxphotos")
    def test_limit_parameter(self, mock_osxphotos):
        mock_db = MagicMock()
        mock_osxphotos.PhotosDB.return_value = mock_db

        photos = [
            self._make_mock_photo(f"u{i}", date=datetime(2024, 1, i + 1))
            for i in range(10)
        ]
        mock_db.photos.return_value = photos

        from index.apple_photos import get_media_items
        items = get_media_items(limit=3)

        assert len(items) == 3


class TestExtractKeyframes:
    """_extract_keyframes with a mocked video clip."""

    def test_extract_keyframes_mock(self, tmp_path, monkeypatch):
        """Mock moviepy.VideoFileClip and verify keyframes are extracted."""
        import index.apple_photos as ap

        # Override the keyframe export dir to use tmp_path
        monkeypatch.setattr(ap, "KEYFRAME_EXPORT_DIR", tmp_path / "keyframes")

        # Create a mock VideoFileClip
        mock_clip = MagicMock()
        mock_clip.duration = 5.0  # 5-second video

        # get_frame returns a small RGB numpy array
        mock_clip.get_frame.return_value = np.zeros((64, 64, 3), dtype=np.uint8)

        # VideoFileClip is imported lazily inside _extract_keyframes via
        # `from moviepy import VideoFileClip`, so we patch it on the moviepy module.
        import moviepy
        with patch.object(moviepy, "VideoFileClip", return_value=mock_clip):
            paths = ap._extract_keyframes("/fake/video.mp4", "test-uuid")

        # With 5-second duration and 2-second interval, we expect frames at t=0,2,4
        assert len(paths) == 3
        for p in paths:
            assert Path(p).exists()
        mock_clip.close.assert_called_once()

    def test_extract_keyframes_moviepy_not_installed(self, monkeypatch):
        """When moviepy import fails, return empty list."""
        import index.apple_photos as ap

        monkeypatch.setattr(ap, "KEYFRAME_EXPORT_DIR", Path("/tmp/kf_test"))

        # Simulate ImportError for moviepy
        original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        def mock_import(name, *args, **kwargs):
            if name == "moviepy":
                raise ImportError("no moviepy")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            paths = ap._extract_keyframes("/fake/video.mp4", "test-uuid")

        assert paths == []
