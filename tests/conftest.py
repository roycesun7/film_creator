"""Shared fixtures for index-layer tests."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

# Ensure the project root is on sys.path so bare `import config` works.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Fixture: temporary database path (patches config.DB_PATH before store loads)
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Create a temporary SQLite DB path and patch config.DB_PATH.

    Returns the Path object for the temporary database file.
    """
    db_path = tmp_path / "test_media.db"
    import config
    import index.store as _store
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(_store, "DB_PATH", db_path)
    return db_path


# ---------------------------------------------------------------------------
# Fixture: small solid-colour test images
# ---------------------------------------------------------------------------

@pytest.fixture()
def test_images(tmp_path):
    """Create small solid-colour JPEG images and return their paths.

    Returns a dict mapping colour name to absolute path string.
    """
    colours = {
        "red": (255, 0, 0),
        "green": (0, 255, 0),
        "blue": (0, 0, 255),
    }
    paths: dict[str, str] = {}
    for name, rgb in colours.items():
        img = Image.new("RGB", (64, 64), color=rgb)
        p = tmp_path / f"{name}.jpg"
        img.save(str(p), "JPEG")
        paths[name] = str(p)
    return paths


# ---------------------------------------------------------------------------
# Fixture: sample MediaItem
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_media_item():
    """Return a sample MediaItem instance for tests."""
    from index.apple_photos import MediaItem

    return MediaItem(
        uuid="AAAA-BBBB-CCCC-DDDD",
        path="/tmp/photo.jpg",
        media_type="photo",
        date=datetime(2024, 6, 15, 10, 30, 0),
        location=(37.7749, -122.4194),
        albums=["Vacation", "Family"],
        labels=["beach", "sunset"],
        persons=["Alice", "Bob"],
        width=4032,
        height=3024,
        duration=None,
        keyframe_paths=[],
    )
