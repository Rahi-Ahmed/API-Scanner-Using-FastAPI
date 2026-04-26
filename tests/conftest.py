"""Shared pytest fixtures.

Training over the vendored bs4 + numpy sources is the slow part of the test
suite (a few seconds), so build each library's knowledge base exactly once
per session and let every test reuse it via these fixtures.
"""

from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIBRARIES_DIR = os.path.join(ROOT, "libraries")

# Make the project importable when pytest is invoked from a subdirectory or
# without an installed package layout.
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from trainer import train_on_library  # noqa: E402


@pytest.fixture(scope="session")
def project_root() -> str:
    return ROOT


@pytest.fixture(scope="session")
def libraries_dir() -> str:
    return LIBRARIES_DIR


@pytest.fixture(scope="session")
def bs4_knowledge() -> dict:
    """Knowledge base built from libraries/bs4 (qualified under `bs4`)."""
    return train_on_library(os.path.join(LIBRARIES_DIR, "bs4"), "bs4")


@pytest.fixture(scope="session")
def numpy_knowledge() -> dict:
    """Knowledge base built from libraries/numpy (qualified under `numpy`)."""
    return train_on_library(os.path.join(LIBRARIES_DIR, "numpy"), "numpy")


@pytest.fixture(scope="session")
def combined_knowledge(bs4_knowledge: dict, numpy_knowledge: dict) -> dict:
    """Union of both library knowledge bases — used for end-to-end runs."""
    merged = {}
    merged.update(bs4_knowledge)
    merged.update(numpy_knowledge)
    return merged
