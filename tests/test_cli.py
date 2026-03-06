"""Tests for the CLI interface defined in main.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAIN_PY = str(PROJECT_ROOT / "main.py")


def _run(args: list[str], env_extra: dict | None = None) -> subprocess.CompletedProcess:
    """Run main.py with the given arguments and return the CompletedProcess."""
    import os

    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, MAIN_PY] + args,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(PROJECT_ROOT),
    )


def test_help_output():
    """``python main.py --help`` returns 0 and shows usage."""
    result = _run(["--help"])
    assert result.returncode == 0
    assert "usage" in result.stdout.lower() or "video-composer" in result.stdout.lower()


def test_index_help():
    """``python main.py index --help`` returns 0."""
    result = _run(["index", "--help"])
    assert result.returncode == 0
    assert "index" in result.stdout.lower()


def test_search_help():
    """``python main.py search --help`` returns 0."""
    result = _run(["search", "--help"])
    assert result.returncode == 0
    assert "search" in result.stdout.lower() or "query" in result.stdout.lower()


def test_generate_help():
    """``python main.py generate --help`` returns 0."""
    result = _run(["generate", "--help"])
    assert result.returncode == 0
    assert "generate" in result.stdout.lower() or "prompt" in result.stdout.lower()


def test_stats_on_empty_db(tmp_db):
    """``python main.py stats`` works with no indexed media.

    Uses the tmp_db fixture which patches config.DB_PATH and
    index.store.DB_PATH to a temporary database file.
    """
    from index.store import init_db
    init_db()

    # Import and call cmd_stats directly with a minimal namespace.
    # cmd_stats does ``from config import DB_PATH`` which creates a local
    # binding — we must ensure config.DB_PATH is already patched (tmp_db
    # does this) before the import resolves.
    import argparse
    from main import cmd_stats

    args = argparse.Namespace(command="stats")
    # Should not raise
    cmd_stats(args)


def test_no_command():
    """``python main.py`` with no args returns non-zero exit code."""
    result = _run([])
    assert result.returncode != 0
