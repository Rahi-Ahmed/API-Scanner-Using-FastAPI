"""Tests for the import-aware analyzer.

These tests target the `_SymbolTable` directly (resolution behaviour) and
`analyze_script()` end-to-end with synthetic scripts + synthetic knowledge
bases, so that name-collision and shadowing rules are exercised in
isolation from the real bs4/numpy training step.
"""

from __future__ import annotations

import ast
import os
import textwrap

import pytest

from analyzer import _SymbolTable, analyze_script


def _resolve(src: str, call_name: str):
    """Build a SymbolTable from `src` and resolve a single dotted call name."""
    tree = ast.parse(textwrap.dedent(src))
    sym = _SymbolTable()
    sym.visit(tree)
    return sym.resolve_call(call_name), sym


def _write_script(tmp_path, src: str) -> str:
    path = os.path.join(tmp_path, "user.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(src))
    return path


# ---------------------------------------------------------------------------
# SymbolTable: imports
# ---------------------------------------------------------------------------


def test_import_module_basic():
    (qualified, root, is_local), sym = _resolve(
        "import bs4\nbs4.something()\n", "bs4.something"
    )
    assert qualified == "bs4.something"
    assert root == "bs4"
    assert is_local is False
    assert sym.imported_roots == {"bs4"}


def test_import_module_with_dotted_path():
    (qualified, root, _), sym = _resolve(
        "import bs4.element\nbs4.element.foo()\n", "bs4.element.foo"
    )
    assert qualified == "bs4.element.foo"
    assert root == "bs4"


def test_import_module_with_alias():
    (qualified, root, _), sym = _resolve(
        "import bs4 as soup_lib\nsoup_lib.parse()\n", "soup_lib.parse"
    )
    assert qualified == "bs4.parse"
    assert root == "bs4"
    assert "bs4" in sym.imported_roots


def test_import_from_module():
    (qualified, root, _), sym = _resolve(
        "from bs4 import BeautifulSoup\nBeautifulSoup()\n", "BeautifulSoup"
    )
    assert qualified == "bs4.BeautifulSoup"
    assert root == "bs4"


def test_import_from_module_with_alias():
    (qualified, root, _), _ = _resolve(
        "from bs4 import BeautifulSoup as BS\nBS()\n", "BS"
    )
    assert qualified == "bs4.BeautifulSoup"
    assert root == "bs4"


def test_import_from_star_records_root():
    _, sym = _resolve("from bs4 import *\n", "anything")
    assert "bs4" in sym.star_imports
    # star imports also count toward `imported_roots` so that the matcher
    # treats unresolved-receiver calls as gated by bs4 anyway.
    assert "bs4" in sym.imported_roots


# ---------------------------------------------------------------------------
# SymbolTable: locals / shadowing
# ---------------------------------------------------------------------------


def test_local_def_is_recorded_as_local():
    (qualified, _, is_local), sym = _resolve(
        "def close():\n    return None\n\nclose()\n", "close"
    )
    assert qualified is None
    assert is_local is True
    assert "close" in sym.locals


def test_async_local_def_is_recorded_as_local():
    (_, _, is_local), sym = _resolve(
        "async def close():\n    return None\n\nclose()\n", "close"
    )
    assert is_local is True
    assert "close" in sym.locals


def test_local_class_is_recorded_as_local():
    (_, _, is_local), sym = _resolve(
        "class MyTag:\n    pass\n\nMyTag()\n", "MyTag"
    )
    assert is_local is True
    assert "MyTag" in sym.locals


def test_local_def_shadows_imported_name():
    """A `def close()` after `from x import close` must shadow the import."""
    (qualified, _, is_local), sym = _resolve(
        """
        from somelib import close

        def close():
            return None

        close()
        """,
        "close",
    )
    assert is_local is True
    assert qualified is None
    assert "close" not in sym.bindings


# ---------------------------------------------------------------------------
# SymbolTable: assignment-based binding
# ---------------------------------------------------------------------------


def test_assignment_resolves_constructor_call():
    (qualified, root, is_local), _ = _resolve(
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup('<html/>', 'html.parser')
        soup.something()
        """,
        "soup.something",
    )
    assert qualified == "bs4.BeautifulSoup.something"
    assert root == "bs4"
    assert is_local is False


def test_assignment_aliasing_propagates_binding():
    (qualified, _, _), _ = _resolve(
        """
        from bs4 import BeautifulSoup
        Maker = BeautifulSoup
        x = Maker()
        x.parse()
        """,
        "x.parse",
    )
    assert qualified == "bs4.BeautifulSoup.parse"


def test_assignment_does_not_resolve_chained_call_return_type():
    """`div_tag = soup.find('div')` is intentionally NOT resolved.

    We must not pretend to know the return type of a chained call. This
    keeps the resolver honest -- the matcher then uses import-gating to
    decide whether to flag `div_tag.has_key`.
    """
    (qualified, _, is_local), sym = _resolve(
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup('<div/>', 'html.parser')
        div_tag = soup.find('div')
        div_tag.has_key('class')
        """,
        "div_tag.has_key",
    )
    assert qualified is None
    assert is_local is False
    assert "div_tag" not in sym.bindings


# ---------------------------------------------------------------------------
# analyze_script: end-to-end with synthetic knowledge bases
# ---------------------------------------------------------------------------


def test_unimported_library_does_not_match(tmp_path):
    """Local `def close()` must NOT be flagged when no relevant lib is imported."""
    script = _write_script(tmp_path, """
        def close():
            return None

        def main():
            close()
    """)
    kb = {"requests.Session.close": "deprecated"}
    findings = analyze_script(script, kb)
    assert findings == []


def test_imported_library_with_local_shadow_does_not_match(tmp_path):
    """Even with `import requests`, a *local* def close() must not be flagged."""
    script = _write_script(tmp_path, """
        import requests

        def close():
            return None

        close()
    """)
    kb = {"requests.Session.close": "deprecated"}
    findings = analyze_script(script, kb)
    called = {f["called"] for f in findings}
    assert "close" not in called


def test_unresolved_receiver_with_imported_root_matches(tmp_path):
    """The canonical bs4 case: receiver is unknown but bs4 is imported."""
    script = _write_script(tmp_path, """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup('<div/>', 'html.parser')
        div_tag = soup.find('div')
        div_tag.has_key('class')
    """)
    kb = {"bs4.element.Tag.has_key": "deprecated"}
    findings = analyze_script(script, kb)
    assert len(findings) == 1
    assert findings[0]["called"] == "div_tag.has_key"
    assert findings[0]["deprecated_api"] == "bs4.element.Tag.has_key"


def test_unresolved_receiver_without_imported_root_skipped(tmp_path):
    """If `bs4` is not imported, even a leaf-name match must not fire."""
    script = _write_script(tmp_path, """
        def main():
            something.has_key('class')
    """)
    kb = {"bs4.element.Tag.has_key": "deprecated"}
    findings = analyze_script(script, kb)
    assert findings == []


def test_resolved_call_matches_only_within_same_root(tmp_path):
    """A call resolved to bs4.* must not match a deprecation in numpy.*."""
    script = _write_script(tmp_path, """
        from bs4 import BeautifulSoup

        x = BeautifulSoup()
        x.in1d()
    """)
    kb = {"numpy.lib._arraysetops_impl.in1d": "deprecated"}
    findings = analyze_script(script, kb)
    assert findings == []


def test_resolved_call_matches_within_same_root(tmp_path):
    script = _write_script(tmp_path, """
        from bs4 import BeautifulSoup

        x = BeautifulSoup()
        x.findAll('div')
    """)
    kb = {"bs4.element.Tag.findAll": "alias-deprecated"}
    findings = analyze_script(script, kb)
    assert len(findings) == 1
    assert findings[0]["resolved"].endswith(".findAll")


def test_async_function_call_is_analyzed(tmp_path):
    script = _write_script(tmp_path, """
        from somelib import old_async

        async def main():
            await old_async()
    """)
    kb = {"somelib.old_async": "async deprecated"}
    findings = analyze_script(script, kb)
    assert len(findings) == 1
    assert findings[0]["called"] == "old_async"


def test_star_import_gates_match(tmp_path):
    """`from bs4 import *` should let unresolved-receiver bs4 calls match."""
    script = _write_script(tmp_path, """
        from bs4 import *

        thing.has_key('x')
    """)
    kb = {"bs4.element.Tag.has_key": "deprecated"}
    findings = analyze_script(script, kb)
    assert len(findings) == 1


def test_top_level_call_to_imported_name(tmp_path):
    """`from numpy import in1d; in1d(...)` should match without any receiver."""
    script = _write_script(tmp_path, """
        from numpy import in1d
        in1d([1, 2], [2, 3])
    """)
    kb = {"numpy.lib._arraysetops_impl.in1d": "deprecated"}
    findings = analyze_script(script, kb)
    assert len(findings) == 1


def test_breaks_on_first_match(tmp_path):
    """Even if multiple deprecated keys share the same leaf, each call site
    is reported once."""
    script = _write_script(tmp_path, """
        from bs4 import BeautifulSoup

        x = BeautifulSoup()
        x.has_key('class')
    """)
    kb = {
        "bs4.element.Tag.has_key": "decorator deprecated",
        "bs4.element.has_key": "decorator deprecated (module)",
    }
    findings = analyze_script(script, kb)
    assert len(findings) == 1
