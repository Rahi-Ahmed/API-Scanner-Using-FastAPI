"""Tests for `FuncVisitor` and `ClassVisitor`.

Exercises:
- sync and async function collection,
- decorator extraction for `Name`, `Attribute`, `Call(Name)`, `Call(Attribute)`,
- nested-class qualified naming,
- class-body alias detection (`x = _deprecated_function_alias(...)`),
  including the `AnnAssign` form (`x: T = ...`).
"""

from __future__ import annotations

import ast
import textwrap

import pytest

from visitors import ClassVisitor, FuncVisitor


def _parse(src: str) -> ast.Module:
    return ast.parse(textwrap.dedent(src))


# ---------------------------------------------------------------------------
# FuncVisitor
# ---------------------------------------------------------------------------


def test_func_visitor_collects_top_level_functions():
    fv = FuncVisitor("m")
    fv.visit(_parse("""
        def a(): pass
        def b(): pass
    """))
    assert set(fv.func_map.keys()) == {"m.a", "m.b"}


def test_func_visitor_collects_async_functions():
    fv = FuncVisitor("m")
    fv.visit(_parse("""
        async def helper():
            return 1
    """))
    assert "m.helper" in fv.func_map
    assert isinstance(fv.func_map["m.helper"], ast.AsyncFunctionDef)


@pytest.mark.parametrize(
    "src,expected",
    [
        # Bare name decorator
        ("@staticmethod\ndef f(): pass\n", ["staticmethod"]),
        # Attribute decorator
        ("@functools.lru_cache\ndef f(): pass\n", ["functools.lru_cache"]),
        # Call(Name) decorator
        ("@_deprecated('use g')\ndef f(): pass\n", ["_deprecated"]),
        # Call(Attribute) decorator -- the case fixed in this iteration
        ("@pkg.deprecated('use g')\ndef f(): pass\n", ["pkg.deprecated"]),
        # Multiple decorators preserve order
        (
            "@staticmethod\n@_deprecated('x')\ndef f(): pass\n",
            ["staticmethod", "_deprecated"],
        ),
    ],
)
def test_func_visitor_extracts_all_decorator_forms(src, expected):
    fv = FuncVisitor("m")
    fv.visit(_parse(src))
    assert fv.func_decorators["m.f"] == expected


def test_func_visitor_async_with_attribute_call_decorator():
    """The previously-missed case: `@pkg.deprecated(...)` on an async def."""
    fv = FuncVisitor("m")
    fv.visit(_parse("""
        @typing_extensions.deprecated('use new_async')
        async def old_async():
            return 1
    """))
    assert fv.func_decorators["m.old_async"] == [
        "typing_extensions.deprecated"
    ]


# ---------------------------------------------------------------------------
# ClassVisitor: classes, methods, qualified names
# ---------------------------------------------------------------------------


def test_class_visitor_collects_classes_and_methods():
    cv = ClassVisitor("m")
    cv.visit(_parse("""
        class Foo:
            def a(self): pass
            async def b(self): pass

        class Bar:
            pass
    """))
    assert set(cv.class_map.keys()) == {"m.Foo", "m.Bar"}
    assert set(cv.func_map.keys()) == {"m.Foo.a", "m.Foo.b"}


def test_class_visitor_handles_nested_classes():
    cv = ClassVisitor("m")
    cv.visit(_parse("""
        class Outer:
            class Inner:
                def doit(self): pass
    """))
    assert "m.Outer" in cv.class_map
    # Nested-class scoping uses the outermost ClassVisitor, so Inner is
    # qualified relative to the module rather than `Outer.Inner`. That's
    # intentional given the current visitor design — pin it so future
    # refactors are noticed.
    assert "m.Inner" in cv.class_map


# ---------------------------------------------------------------------------
# ClassVisitor: alias_map for class-body deprecation aliases
# ---------------------------------------------------------------------------


def test_class_body_alias_simple_assign_is_recorded():
    cv = ClassVisitor("m")
    cv.visit(_parse("""
        class Tag:
            findAll = _deprecated_function_alias("findAll", "find_all", "4.0.0")
    """))
    assert "m.Tag.findAll" in cv.alias_map
    assert "_deprecated_function_alias" in cv.alias_map["m.Tag.findAll"]


def test_class_body_alias_dotted_callee_is_recorded():
    cv = ClassVisitor("m")
    cv.visit(_parse("""
        class Tag:
            old = pkg.helpers._deprecated_alias("old", "new", "4.0.0")
    """))
    assert "m.Tag.old" in cv.alias_map


def test_class_body_alias_ann_assign_form():
    cv = ClassVisitor("m")
    cv.visit(_parse("""
        class Tag:
            findAll: object = _deprecated_function_alias("findAll", "find_all", "4.0.0")
    """))
    assert "m.Tag.findAll" in cv.alias_map


def test_class_body_alias_ignores_non_deprecation_calls():
    cv = ClassVisitor("m")
    cv.visit(_parse("""
        class Tag:
            things = list()
            cache = lru_cache(maxsize=128)
            other = pkg.factory("x")
    """))
    assert cv.alias_map == {}


def test_class_body_alias_ignores_non_call_rhs():
    cv = ClassVisitor("m")
    cv.visit(_parse("""
        class Tag:
            CONSTANT = 42
            label = "deprecated"   # the literal string must not trigger
            other = some_name      # bare reference
    """))
    assert cv.alias_map == {}


def test_class_body_alias_does_not_match_negative_names():
    cv = ClassVisitor("m")
    cv.visit(_parse("""
        class Tag:
            x = undeprecated_helper("a")
            y = notdeprecated("b")
    """))
    assert cv.alias_map == {}
