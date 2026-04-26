"""Tests for `train_on_library`: error handling and basic invariants.

Real-library knowledge-base content is exercised in test_end_to_end.py
via session fixtures. This file focuses on synthetic libraries and
adversarial inputs (bad syntax, undecodable bytes, missing __init__).
"""

from __future__ import annotations

import logging
import os
import textwrap

import pytest

from trainer import train_on_library


def _write(tmp_path, name: str, content: str) -> str:
    full = os.path.join(tmp_path, name)
    os.makedirs(os.path.dirname(full), exist_ok=True) if os.path.dirname(full) else None
    with open(full, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(content))
    return full


def test_train_on_empty_directory_returns_empty_dict(tmp_path):
    out = train_on_library(str(tmp_path), "fake")
    assert out == {}


def test_train_skips_non_python_files(tmp_path):
    _write(tmp_path, "README.md", "Just docs, not deprecated.\n")
    _write(tmp_path, "data.txt", "deprecated content but wrong extension")
    out = train_on_library(str(tmp_path), "fake")
    assert out == {}


def test_train_picks_up_decorator_and_warn_paths(tmp_path):
    _write(tmp_path, "mod.py", """
        from warnings import warn

        @_deprecated('use new_thing')
        def old():
            return 1

        def warns_caller():
            warn('gone soon', DeprecationWarning)
    """)
    out = train_on_library(str(tmp_path), "fake")
    assert "fake.mod.old" in out
    assert "fake.mod.warns_caller" in out
    assert out["fake.mod.old"] == "Marked with a @deprecated decorator."
    assert "DeprecationWarning" in out["fake.mod.warns_caller"]


def test_train_picks_up_class_body_alias(tmp_path):
    _write(tmp_path, "mod.py", """
        class Tag:
            findAll = _deprecated_function_alias('findAll', 'find_all', '4.0.0')
    """)
    out = train_on_library(str(tmp_path), "fake")
    assert "fake.mod.Tag.findAll" in out
    assert "_deprecated_function_alias" in out["fake.mod.Tag.findAll"]


def test_train_logs_warning_on_syntax_error(tmp_path, caplog):
    _write(tmp_path, "good.py", """
        @_deprecated('use new')
        def f(): pass
    """)
    _write(tmp_path, "bad.py", "def broken(:\n  pass\n")  # invalid syntax

    with caplog.at_level(logging.WARNING, logger="trainer"):
        out = train_on_library(str(tmp_path), "fake")

    assert "fake.good.f" in out
    assert "fake.bad" not in " ".join(out.keys())
    syntax_warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "invalid Python syntax" in r.getMessage()
    ]
    assert len(syntax_warnings) == 1
    assert "bad.py" in syntax_warnings[0].getMessage()


def test_train_logs_warning_on_unicode_decode_error(tmp_path, caplog):
    bad_path = os.path.join(tmp_path, "binary.py")
    with open(bad_path, "wb") as f:
        f.write(b"\xff\xfe\xfd\x00 not really utf-8")

    with caplog.at_level(logging.WARNING, logger="trainer"):
        out = train_on_library(str(tmp_path), "fake")

    assert out == {}
    decode_warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "Could not read" in r.getMessage()
    ]
    assert len(decode_warnings) == 1


def test_train_qualifies_names_by_relative_path(tmp_path):
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/sub.py", """
        def helper():
            \"\"\"This helper is deprecated.\"\"\"
            return 1
    """)
    out = train_on_library(str(tmp_path), "fake")
    assert "fake.pkg.sub.helper" in out


def test_train_does_not_flag_negative_docstrings(tmp_path):
    _write(tmp_path, "mod.py", """
        def f():
            \"\"\"This function is not deprecated.\"\"\"
            return 1

        def g():
            \"\"\"undeprecated.\"\"\"
            return 2
    """)
    out = train_on_library(str(tmp_path), "fake")
    assert "fake.mod.f" not in out
    assert "fake.mod.g" not in out


def test_train_returns_only_strings_as_values(tmp_path):
    """Knowledge base values must be human-readable strings."""
    _write(tmp_path, "mod.py", """
        @deprecated
        def f(): pass
    """)
    out = train_on_library(str(tmp_path), "fake")
    assert all(isinstance(v, str) for v in out.values())
    assert all(v for v in out.values()), "no entry may have an empty reason"
