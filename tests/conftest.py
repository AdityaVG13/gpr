"""Shared pytest fixtures."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def tmp_project(tmp_path: Path):
    """A temp directory acting as a project root."""
    old = os.getcwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old)
