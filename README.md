# API Deprecation Scanner

A static analysis tool that AST-parses third-party libraries to build a knowledge base of deprecated APIs, then scans a user script for any calls to those APIs.

## How to run

### Requirements

- Python 3.9+
- (Optional) `beautifulsoup4` if you want `test_script.py` to also run as real Python — the scanner itself only needs the standard library.

### Setup

```bash
git clone <this-repo>
cd API-Scanner-Using-FastAPI

python3 -m venv .venv
source .venv/bin/activate
```

### Run the scanner

```bash
python3 main.py
```

Expected output (abridged). Progress logs go to **stderr**; findings go to **stdout**, so you can pipe results cleanly (e.g. `python3 main.py 2>/dev/null`):

```
--- STEP 1: FEEDING LIBRARIES ---
[Scanning Library: bs4]
  -> Parsing element.py
  -> Parsing __init__.py
  ...
 -> Found 77 deprecations in bs4
[Total Knowledge Base Built: 77 known deprecations]
--- STEP 2: ANALYZING SCRIPT ---
Analyzing .../test_script.py

DEPRECATIONS FOUND:
Line 10: Call to 'div_tag.has_key' -> Marked with a @deprecated decorator. [matches bs4.element.Tag.has_key]
Line 13: Call to 'img_tag.isSelfClosing' -> Marked with a @deprecated decorator. [matches bs4.element.Tag.isSelfClosing]
Line 17: Call to 'div_tag.nextGenerator' -> Marked with a @deprecated decorator. [matches bs4.element.PageElement.nextGenerator]
```

### Scan your own code

1. Drop any library you want indexed into `libraries/<lib_name>/` (it is parsed, not imported, so you can vendor a source tree directly).
2. Replace `test_script.py` with the script you want analyzed (or edit `main.py` to point at a different path).
3. Re-run `python3 main.py`.

## How the codebase works

### Overall flow

Two phases:

1. **Train** — build a knowledge base of deprecated APIs by AST-parsing every `.py` file under `libraries/`.
2. **Analyze** — AST-parse `test_script.py` and report any call whose method name matches one in that knowledge base.

### File roles

- **`main.py`** — Entry point. Installs a custom log formatter so progress lines stream bare (`logger.info`) and warnings get a `WARNING:` prefix, then iterates each subdirectory of `libraries/` (skipping non-directories like `.DS_Store`), runs `train_on_library()` on each, merges results into `master_knowledge`, and finally calls `analyze_script()` against `test_script.py`. Progress is logged to stderr; findings are `print()`ed to stdout so they can be piped or grepped independently.

- **`trainer.py`** — `train_on_library(library_path, base_module_name)` walks every `.py` file in the library. For each file it:
  1. Reads the source, logging a warning on `OSError` / `UnicodeDecodeError` and skipping.
  2. Calls `ast.parse()`, logging a warning with file path, line number, and message on `SyntaxError` and skipping (no silent `pass`).
  3. Builds a fully qualified module name from the relative path (e.g. `bs4.element`).
  4. Runs `ClassVisitor` and `FuncVisitor` over the AST, hands their maps to `extract_deprecations()`, and merges in `ClassVisitor.alias_map` (class-body alias assignments — see below).

- **`visitors.py`** — Two `ast.NodeVisitor`s.
  - `FuncVisitor` collects every `FunctionDef` **and `AsyncFunctionDef`** into `func_map` keyed by `module.func` (or `module.Class.method` when reused for class bodies). For each function it also stores a list of decorator name strings in `func_decorators`, handling bare names (`@deprecated`), dotted attributes (`@pkg.deprecated`), `@deco(...)` calls, **and `@pkg.deco(...)` attribute-call decorators**.
  - `ClassVisitor` collects each `ClassDef` into `class_map`, spawns a nested `FuncVisitor(class_name)` so methods get qualified names like `bs4.element.Tag.has_key`, and additionally scans the class body for `ast.Assign` / `ast.AnnAssign` statements where the right-hand side calls a deprecation-wrapper function (e.g. `findAll = _deprecated_function_alias("findAll", "find_all", "4.0.0")`). Each such alias is recorded in `alias_map` keyed by `Class.<assigned_name>`. This catches the common BeautifulSoup pattern of declaring an old camelCase API as a wrapped alias of the new name.

- **`check_for_deprecation.py`** — The detection rules. Uses **explicit-marker regexes** instead of a loose `"deprecat"` substring:
  - `_DOC_DEPRECATION_PATTERNS` — looks for `.. deprecated::`, `:deprecated:`, `deprecated since`, `is deprecated`, `has been deprecated`, `Deprecated.` at line start, etc. So `"this is not deprecated"` and `"undeprecated"` no longer trigger.
  - `_DECORATOR_DEPRECATION_RE` — matches `deprecat` only when preceded by start, `.`, or `_`, so `@deprecated`, `@_deprecated`, `@pkg.deprecated`, and wrappers like `_deprecated_function_alias` all match while `undeprecated` / `notdeprecated` do not. Exposed via the helper `is_deprecation_wrapper_name(name)`, which `visitors.py` reuses for class-body alias scanning.
  - `_function_emits_deprecation_warning(node)` — walks the function body for any `Call` that resolves (via `_resolve_dotted`) to `warn` / `warnings.warn`, then inspects all positional args and `**kwargs` values for a reference to `DeprecationWarning`, `FutureWarning`, or `PendingDeprecationWarning`. It recognizes bare names (`DeprecationWarning`), dotted attributes (`warnings.DeprecationWarning`), and instantiations passed as the message itself (`DeprecationWarning("...")`).

  `extract_deprecations(class_map, func_map, func_decorators)` runs those three checks in order and returns `{ qualified_name: human_readable_reason }`. The reason also reports which warning class it found (e.g. `"Emits FutureWarning via warnings.warn()."`).

- **`analyzer.py`** — Now import-aware. Two passes over the user script's AST:
  1. `_SymbolTable` (an `ast.NodeVisitor`) handles `visit_Import`, `visit_ImportFrom`, `visit_FunctionDef`, `visit_AsyncFunctionDef`, `visit_ClassDef`, and `visit_Assign`. It records:
     - `bindings` — local name → fully qualified target (`BeautifulSoup → bs4.BeautifulSoup`, `b → bs4`, etc.).
     - `imported_roots` — the set of root packages the script can see (`{"bs4"}`).
     - `star_imports` — packages brought in via `from pkg import *`.
     - `locals` — names defined in this script (def / class / shadowed bindings) so a local `def close()` shadows any imported `close`.
     - Simple `name = ImportedThing(...)` assignments are also tracked, so `soup = BeautifulSoup(...)` makes `soup` resolve to `bs4.BeautifulSoup`. Chained calls like `div_tag = soup.find('div')` are deliberately *not* type-inferred (we'd be guessing return types), so `div_tag` stays unresolved.
  2. `_CallVisitor` records every `Call` (qualified via `_flatten_attr` into things like `div_tag.has_key`) with its line number.

  Matching (`_is_match`) then has three strict rules: (a) a call resolved to a known qualified name matches a deprecated key only when they share a root package, (b) a call with an *unresolved* receiver (e.g. `div_tag.has_key` where `div_tag`'s type is unknown) only matches deprecated keys whose root module is actually imported by the script — so unrelated libraries with a same-named method never produce false positives, and (c) calls whose head name is locally defined are never flagged. `analyze_script()` returns `{line, called, resolved, deprecated_api, warning}` per finding.

- **`test_script.py`** — Sample input that calls three deprecated bs4 APIs (`has_key`, `isSelfClosing`, `nextGenerator`) so the scanner has something real to find.

- **`libraries/bs4/`** — Vendored BeautifulSoup source used as scan input (it is parsed, not imported).
- **`libraries/text_utils.py`** — A tiny synthetic library with one docstring-deprecated function and one `warn(..., FutureWarning)` function, useful for sanity-testing both detection paths.

- **`requirements.txt`** — Notes the scanner itself is stdlib-only, lists `beautifulsoup4>=4.12` so `test_script.py` can also run as actual Python.
- **`.gitignore`** — Standard Python ignores: `__pycache__/`, bytecode, virtualenvs, tooling caches, editor/OS junk, and `.env*` files.

### End-to-end behaviour

Running `python3 main.py` logs which `.py` files are being parsed (stderr), surfaces any read/parse failures via `WARNING:` prefixed lines, reports `Found N deprecations in <lib>` per library (currently 77 in bs4 — up from 55 once class-body alias detection was added), and prints each deprecated call site in `test_script.py` to stdout with the line number, the resolved deprecated API it matched, and the human-readable reason from the knowledge base. The stdout/stderr split lets you do `python3 main.py 2>/dev/null` to get just the findings.
