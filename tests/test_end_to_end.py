"""End-to-end tests using the real libraries vendored under `libraries/`.

These tests rely on the session-scoped `bs4_knowledge`, `numpy_knowledge`,
and `combined_knowledge` fixtures from conftest.py so that the (slow)
training step is only paid once per test run.
"""

from __future__ import annotations

import os
import textwrap

import pytest

from analyzer import analyze_script


# ---------------------------------------------------------------------------
# Knowledge-base shape: bs4
# ---------------------------------------------------------------------------


def test_bs4_kb_is_substantive(bs4_knowledge: dict):
    """bs4 has a long history of deprecations; the KB should be sizeable."""
    assert len(bs4_knowledge) > 50


@pytest.mark.parametrize(
    "qualified",
    [
        "bs4.element.Tag.has_key",
        "bs4.element.Tag.isSelfClosing",
        "bs4.element.PageElement.nextGenerator",
        "bs4.element.Tag.replaceWithChildren",
    ],
)
def test_bs4_kb_contains_known_decorator_deprecations(bs4_knowledge, qualified):
    assert qualified in bs4_knowledge
    assert bs4_knowledge[qualified] == "Marked with a @deprecated decorator."


@pytest.mark.parametrize(
    "qualified",
    [
        "bs4.element.Tag.findAll",
        "bs4.element.PageElement.findAllNext",
        "bs4.element.PageElement.findAllPrevious",
        "bs4.element.PageElement.replaceWith",
        "bs4.element.Tag.parserClass",
    ],
)
def test_bs4_kb_contains_class_body_aliases(bs4_knowledge, qualified):
    assert qualified in bs4_knowledge
    reason = bs4_knowledge[qualified]
    assert "Class-body alias" in reason
    assert "_deprecated" in reason


def test_bs4_kb_does_not_flag_undeprecated_apis(bs4_knowledge):
    """A handful of common, well-supported bs4 APIs must NOT be in the KB."""
    safe_apis = [
        "bs4.BeautifulSoup",
        "bs4.element.Tag.find",
        "bs4.element.Tag.find_all",
        "bs4.element.Tag.get",
        "bs4.element.Tag.string",
    ]
    for api in safe_apis:
        assert api not in bs4_knowledge, (
            f"unexpected false positive in bs4 KB: {api}"
        )


# ---------------------------------------------------------------------------
# Knowledge-base shape: numpy
# ---------------------------------------------------------------------------


def test_numpy_kb_is_substantive(numpy_knowledge: dict):
    assert len(numpy_knowledge) > 30


@pytest.mark.parametrize(
    "qualified",
    [
        "numpy.lib._arraysetops_impl.in1d",
        "numpy.lib._utils_impl.safe_eval",
        "numpy.lib._npyio_impl.recfromcsv",
        "numpy.lib._npyio_impl.recfromtxt",
    ],
)
def test_numpy_kb_contains_docstring_deprecations(numpy_knowledge, qualified):
    assert qualified in numpy_knowledge


def test_numpy_kb_has_warn_path_entries(numpy_knowledge):
    """numpy uses `warnings.warn(..., DeprecationWarning)` extensively."""
    warn_entries = {
        k: v for k, v in numpy_knowledge.items()
        if "warnings.warn()" in v
    }
    assert len(warn_entries) >= 1, (
        "expected at least one warnings.warn-based entry from numpy"
    )


# ---------------------------------------------------------------------------
# End-to-end scan: the bundled `test_script.py`
# ---------------------------------------------------------------------------


def test_bundled_test_script_finds_three_deprecations(
    project_root: str, bs4_knowledge: dict
):
    script_path = os.path.join(project_root, "test_script.py")
    findings = analyze_script(script_path, bs4_knowledge)

    assert len(findings) == 3
    by_line = {f["line"]: f for f in findings}
    assert set(by_line.keys()) == {10, 13, 17}
    assert by_line[10]["called"] == "div_tag.has_key"
    assert by_line[10]["deprecated_api"] == "bs4.element.Tag.has_key"
    assert by_line[13]["called"] == "img_tag.isSelfClosing"
    assert by_line[13]["deprecated_api"] == "bs4.element.Tag.isSelfClosing"
    assert by_line[17]["called"] == "div_tag.nextGenerator"
    assert by_line[17]["deprecated_api"].endswith(".nextGenerator")


def test_bundled_test_script_findings_are_well_formed(
    project_root: str, bs4_knowledge: dict
):
    script_path = os.path.join(project_root, "test_script.py")
    for issue in analyze_script(script_path, bs4_knowledge):
        assert set(issue.keys()) >= {
            "line", "called", "resolved", "deprecated_api", "warning",
        }
        assert isinstance(issue["line"], int) and issue["line"] > 0
        assert issue["called"]
        assert issue["warning"]


# ---------------------------------------------------------------------------
# End-to-end: synthetic user scripts against the real KBs
# ---------------------------------------------------------------------------


def _write(tmp_path, src: str) -> str:
    path = os.path.join(tmp_path, "user.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(src))
    return path


def test_real_bs4_kb_does_not_flag_local_close(tmp_path, bs4_knowledge):
    """The headline regression: a local `def close()` must NOT be flagged
    against the real bs4 KB just because some bs4 method shares the name."""
    script = _write(tmp_path, """
        from bs4 import BeautifulSoup

        def close():
            return None

        def main():
            close()
            close()
    """)
    findings = analyze_script(script, bs4_knowledge)
    called = {f["called"] for f in findings}
    assert "close" not in called


def test_real_bs4_kb_flags_findall_via_alias(tmp_path, bs4_knowledge):
    """End-to-end: class-body alias detection plus analyzer matching."""
    script = _write(tmp_path, """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup('<div/>', 'html.parser')
        soup.findAll('div')
    """)
    findings = analyze_script(script, bs4_knowledge)
    leaves = {f["called"].rsplit(".", 1)[-1] for f in findings}
    assert "findAll" in leaves
    findall_finding = next(f for f in findings if f["called"].endswith(".findAll"))
    assert "Class-body alias" in findall_finding["warning"]


def test_real_numpy_kb_flags_in1d(tmp_path, numpy_knowledge):
    script = _write(tmp_path, """
        from numpy import in1d

        in1d([1, 2, 3], [2])
    """)
    findings = analyze_script(script, numpy_knowledge)
    assert len(findings) == 1
    assert findings[0]["called"] == "in1d"
    assert findings[0]["deprecated_api"].endswith(".in1d")


def test_combined_kb_unrelated_local_function_not_flagged(
    tmp_path, combined_knowledge
):
    """No imports of bs4 OR numpy => locally named methods that happen to
    collide with deprecated leaf names elsewhere must NOT match."""
    script = _write(tmp_path, """
        def has_key(d, k):
            return k in d

        def main():
            has_key({}, 'x')
    """)
    findings = analyze_script(script, combined_knowledge)
    assert findings == []


def test_combined_kb_imported_unrelated_lib_does_not_open_door(
    tmp_path, combined_knowledge
):
    """Importing some other library must NOT make bs4 deprecations visible."""
    script = _write(tmp_path, """
        import json

        thing.has_key('x')
    """)
    findings = analyze_script(script, combined_knowledge)
    assert findings == []


def test_real_bs4_kb_async_context(tmp_path, bs4_knowledge):
    """An `async def` user function calling deprecated APIs is still scanned."""
    script = _write(tmp_path, """
        from bs4 import BeautifulSoup

        async def fetch_and_parse(url):
            soup = BeautifulSoup('<div/>', 'html.parser')
            div_tag = soup.find('div')
            return div_tag.has_key('class')
    """)
    findings = analyze_script(script, bs4_knowledge)
    assert any(f["called"] == "div_tag.has_key" for f in findings)


def test_no_findings_for_clean_user_script(tmp_path, bs4_knowledge):
    script = _write(tmp_path, """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup('<div/>', 'html.parser')
        tag = soup.find('div')
        if tag:
            print(tag.get('class'))
            print(tag.get_text())
    """)
    findings = analyze_script(script, bs4_knowledge)
    assert findings == []
