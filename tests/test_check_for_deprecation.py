"""Detection-rule tests for `check_for_deprecation`.

Covers docstring-marker detection, decorator-name detection, the
`is_deprecation_wrapper_name` helper, and the `warnings.warn` body
inspection in all the forms the analyzer is expected to handle.
"""

from __future__ import annotations

import ast
import textwrap

import pytest

from check_for_deprecation import (
    extract_deprecations,
    is_deprecation_wrapper_name,
    _decorators_indicate_deprecation,
    _doc_indicates_deprecation,
    _function_emits_deprecation_warning,
    _is_warnings_warn_call,
)
from visitors import ClassVisitor, FuncVisitor


def _build_maps(src: str, base: str = "m"):
    """Parse `src` and return (class_map, combined_func_map, combined_decs)."""
    tree = ast.parse(textwrap.dedent(src))
    cv = ClassVisitor(base)
    cv.visit(tree)
    fv = FuncVisitor(base)
    fv.visit(tree)
    return (
        cv.class_map,
        {**cv.func_map, **fv.func_map},
        {**cv.func_decorators, **fv.func_decorators},
    )


# ---------------------------------------------------------------------------
# Docstring detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "doc",
    [
        "This function is deprecated. Use new_thing instead.",
        ".. deprecated:: 1.0\n    Use new_thing instead.",
        ":deprecated: removed in 2.0",
        "Deprecated since version 4.7.0",
        "Deprecated in version 4.7.0 -- use foo",
        "These helpers are deprecated and will be removed.",
        "This API has been deprecated since v1.",
        "Deprecated. Use the modern API.",
        "Deprecated: see notes",
    ],
)
def test_docstring_positive_markers(doc: str):
    assert _doc_indicates_deprecation(doc) is True


@pytest.mark.parametrize(
    "doc",
    [
        "",
        None,
        "This is not deprecated. Please keep using it.",
        "An undeprecated helper function.",
        "Returns a value. See deprecation policy in docs/policy.md.",
        "This function is fine; nothing about it is gone.",
    ],
)
def test_docstring_negative_does_not_match(doc):
    assert _doc_indicates_deprecation(doc) is False


# ---------------------------------------------------------------------------
# Decorator-name detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "deprecated",
        "Deprecated",
        "_deprecated",
        "_deprecated_function_alias",
        "_deprecated_alias",
        "_deprecate",
        "_deprecation_warn",
        "pkg.deprecated",
        "pkg.sub.deprecated_alias",
    ],
)
def test_is_deprecation_wrapper_name_positive(name: str):
    assert is_deprecation_wrapper_name(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "",
        "undeprecated",
        "notdeprecated",
        "predeprecated",
        "depr",
        "my_decorator",
        "lru_cache",
        "staticmethod",
    ],
)
def test_is_deprecation_wrapper_name_negative(name: str):
    assert is_deprecation_wrapper_name(name) is False


def test_decorators_indicate_deprecation_aggregates():
    assert _decorators_indicate_deprecation(["staticmethod", "_deprecated"]) is True
    assert _decorators_indicate_deprecation(["staticmethod", "lru_cache"]) is False
    assert _decorators_indicate_deprecation([]) is False


# ---------------------------------------------------------------------------
# warnings.warn detection
# ---------------------------------------------------------------------------


def _first_call(src: str) -> ast.Call:
    """Return the first `Call` node in `src`."""
    tree = ast.parse(textwrap.dedent(src))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            return node
    raise AssertionError("no Call node found in src")


@pytest.mark.parametrize(
    "src",
    [
        "warn('x', DeprecationWarning)",
        "warnings.warn('x', DeprecationWarning)",
    ],
)
def test_is_warnings_warn_call_positive(src: str):
    assert _is_warnings_warn_call(_first_call(src)) is True


@pytest.mark.parametrize(
    "src",
    [
        "print('x')",
        # An arbitrary `.warn` (e.g. a logger) must NOT be treated as
        # `warnings.warn`. Only the bare `warn` and qualified `warnings.warn`
        # forms are accepted.
        "logger.warn('x', DeprecationWarning)",
        "something.notwarn('x', DeprecationWarning)",
    ],
)
def test_is_warnings_warn_call_negative(src: str):
    assert _is_warnings_warn_call(_first_call(src)) is False


@pytest.mark.parametrize(
    "src,expected",
    [
        # Bare warn(), positional class
        ("def f():\n    warn('x', DeprecationWarning)\n", "DeprecationWarning"),
        # Qualified warnings.warn, positional class
        ("def f():\n    warnings.warn('x', FutureWarning)\n", "FutureWarning"),
        # PendingDeprecationWarning
        (
            "def f():\n    warnings.warn('x', PendingDeprecationWarning)\n",
            "PendingDeprecationWarning",
        ),
        # category=... kwarg form
        (
            "def f():\n    warnings.warn('x', category=DeprecationWarning)\n",
            "DeprecationWarning",
        ),
        # Instantiation passed as the message itself
        (
            "def f():\n    warnings.warn(DeprecationWarning('x'))\n",
            "DeprecationWarning",
        ),
        # Dotted attribute reference (warnings.DeprecationWarning)
        (
            "def f():\n    warnings.warn('x', warnings.DeprecationWarning)\n",
            "DeprecationWarning",
        ),
    ],
)
def test_function_emits_deprecation_warning_positive(src: str, expected: str):
    tree = ast.parse(textwrap.dedent(src))
    func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
    assert _function_emits_deprecation_warning(func) == expected


@pytest.mark.parametrize(
    "src",
    [
        # No warning class at all
        "def f():\n    warnings.warn('x')\n",
        # Non-deprecation warning class
        "def f():\n    warnings.warn('x', UserWarning)\n",
        # Wrong call name
        "def f():\n    print('x', DeprecationWarning)\n",
        # Empty body
        "def f():\n    pass\n",
    ],
)
def test_function_emits_deprecation_warning_negative(src: str):
    tree = ast.parse(textwrap.dedent(src))
    func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
    assert _function_emits_deprecation_warning(func) is None


# ---------------------------------------------------------------------------
# extract_deprecations() — full integration of detection rules
# ---------------------------------------------------------------------------


def test_extract_deprecations_class_docstring():
    src = """
    class Old:
        \"\"\"This class is deprecated. Use New instead.\"\"\"
        pass

    class Fine:
        \"\"\"Helpful docstring; not deprecated at all.\"\"\"
        pass
    """
    class_map, func_map, func_decs = _build_maps(src)
    out = extract_deprecations(class_map, func_map, func_decs)
    assert out.get("m.Old") == "Class docstring indicates deprecation."
    assert "m.Fine" not in out


def test_extract_deprecations_function_decorator_takes_precedence():
    src = """
    @_deprecated('use g')
    def f():
        \"\"\"Plain docstring.\"\"\"
        pass
    """
    out = extract_deprecations(*_build_maps(src))
    assert out.get("m.f") == "Marked with a @deprecated decorator."


def test_extract_deprecations_function_docstring_path():
    src = """
    def f():
        \"\"\"This helper is deprecated. Use g instead.\"\"\"
        return 1
    """
    out = extract_deprecations(*_build_maps(src))
    assert out.get("m.f") == "Function docstring indicates deprecation."


def test_extract_deprecations_warn_message_reports_class():
    src = """
    import warnings

    def f():
        warnings.warn('gone', FutureWarning)
    """
    out = extract_deprecations(*_build_maps(src))
    assert out.get("m.f") == "Emits FutureWarning via warnings.warn()."


def test_extract_deprecations_async_function_decorator():
    src = """
    @deprecated('use new_async')
    async def old_async():
        return 1
    """
    out = extract_deprecations(*_build_maps(src))
    assert out.get("m.old_async") == "Marked with a @deprecated decorator."


def test_extract_deprecations_skips_non_deprecation_warning():
    src = """
    import warnings

    def f():
        warnings.warn('non-fatal', UserWarning)
    """
    out = extract_deprecations(*_build_maps(src))
    assert "m.f" not in out


def test_extract_deprecations_does_not_flag_negative_docstring():
    src = """
    def f():
        \"\"\"This function is not deprecated. Use it freely.\"\"\"
        return 1

    def g():
        \"\"\"undeprecated helper.\"\"\"
        return 2
    """
    out = extract_deprecations(*_build_maps(src))
    assert "m.f" not in out
    assert "m.g" not in out
