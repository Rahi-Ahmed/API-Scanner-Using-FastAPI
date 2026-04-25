import ast
import re

_DOC_DEPRECATION_PATTERNS = (
    re.compile(r"\.\.\s*deprecated\s*::", re.IGNORECASE),
    re.compile(r":deprecated:", re.IGNORECASE),
    re.compile(r"\bdeprecated\s+since\b", re.IGNORECASE),
    re.compile(r"\bdeprecated\s+in\s+version\b", re.IGNORECASE),
    re.compile(r"\bis\s+deprecated\b", re.IGNORECASE),
    re.compile(r"\bare\s+deprecated\b", re.IGNORECASE),
    re.compile(r"\bhas\s+been\s+deprecated\b", re.IGNORECASE),
    re.compile(r"\bwill\s+be\s+deprecated\b", re.IGNORECASE),
    re.compile(r"(?:^|\n)\s*deprecated\b[\s.,:;\-]", re.IGNORECASE),
)

# Decorator names like `deprecated`, `_deprecated`, `mypkg.deprecated`,
# `deprecated_alias`. Preceded only by start-of-string, `.`, or `_` so that
# `undeprecated` / `notdeprecated` are not matched.
_DECORATOR_DEPRECATION_RE = re.compile(r"(?:^|[._])deprecated", re.IGNORECASE)

_WARNING_TYPES = frozenset({
    "DeprecationWarning",
    "FutureWarning",
    "PendingDeprecationWarning",
})


def _resolve_dotted(node):
    if isinstance(node, ast.Attribute):
        base = _resolve_dotted(node.value)
        return f"{base}.{node.attr}" if base else ""
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _doc_indicates_deprecation(doc):
    if not doc:
        return False
    return any(pattern.search(doc) for pattern in _DOC_DEPRECATION_PATTERNS)


def _decorators_indicate_deprecation(decorators):
    return any(_DECORATOR_DEPRECATION_RE.search(d) for d in decorators)


def _is_warnings_warn_call(call):
    name = _resolve_dotted(call.func)
    if not name:
        return False
    return name == "warn" or name == "warnings.warn" or name.endswith(".warnings.warn")


def _arg_references_warning_type(arg):
    """Return the warning class name referenced by `arg`, or None.

    Handles bare names (`DeprecationWarning`), dotted attributes
    (`warnings.DeprecationWarning`), and instantiations passed as the
    message itself (`DeprecationWarning("...")`).
    """
    if isinstance(arg, ast.Name):
        return arg.id if arg.id in _WARNING_TYPES else None
    if isinstance(arg, ast.Attribute):
        leaf = _resolve_dotted(arg).rsplit(".", 1)[-1]
        return leaf if leaf in _WARNING_TYPES else None
    if isinstance(arg, ast.Call):
        return _arg_references_warning_type(arg.func)
    return None


def _function_emits_deprecation_warning(node):
    for child in ast.walk(node):
        if not isinstance(child, ast.Call) or not _is_warnings_warn_call(child):
            continue
        candidates = list(child.args) + [kw.value for kw in child.keywords]
        for arg in candidates:
            warning_type = _arg_references_warning_type(arg)
            if warning_type:
                return warning_type
    return None


def extract_deprecations(class_map, func_map, func_decorators):
    knowledge_base = {}

    for name, node in class_map.items():
        if _doc_indicates_deprecation(ast.get_docstring(node)):
            knowledge_base[name] = "Class docstring indicates deprecation."

    for name, node in func_map.items():
        if _decorators_indicate_deprecation(func_decorators.get(name, [])):
            knowledge_base[name] = "Marked with a @deprecated decorator."
            continue

        if _doc_indicates_deprecation(ast.get_docstring(node)):
            knowledge_base[name] = "Function docstring indicates deprecation."
            continue

        warning_type = _function_emits_deprecation_warning(node)
        if warning_type:
            knowledge_base[name] = f"Emits {warning_type} via warnings.warn()."

    return knowledge_base
