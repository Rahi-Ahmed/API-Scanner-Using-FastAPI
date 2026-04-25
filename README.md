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

Expected output (abridged):

```
--- STEP 1: FEEDING LIBRARIES ---

[Scanning Library: bs4]
  -> Parsing element.py...
  -> Parsing __init__.py...
  ...
 -> Found 55 deprecations in bs4

[Total Knowledge Base Built: 55 known deprecations]

--- STEP 2: ANALYZING SCRIPT ---
Analyzing .../test_script.py...

DEPRECATIONS FOUND:
Line 10: Call to 'div_tag.has_key' -> Marked with a @deprecated decorator.
Line 13: Call to 'img_tag.isSelfClosing' -> Marked with a @deprecated decorator.
Line 17: Call to 'div_tag.nextGenerator' -> Marked with a @deprecated decorator.
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

- **`main.py`** — Entry point. Configures `logging.basicConfig(level=INFO)` so warnings from the trainer surface, then iterates each subdirectory of `libraries/` (skipping files like `.DS_Store`), runs `train_on_library()` on each, merges results into `master_knowledge`, and finally calls `analyze_script()` against `test_script.py` and prints findings.

- **`trainer.py`** — `train_on_library(library_path, base_module_name)` walks every `.py` file in the library. For each file it:
  1. Reads the source, logging a warning on `OSError` / `UnicodeDecodeError` and skipping.
  2. Calls `ast.parse()`, logging a warning with file path, line number, and message on `SyntaxError` and skipping (no silent `pass`).
  3. Builds a fully qualified module name from the relative path (e.g. `bs4.element`).
  4. Runs `ClassVisitor` and `FuncVisitor` over the AST, then hands their maps to `extract_deprecations()`.

- **`visitors.py`** — Two `ast.NodeVisitor`s.
  - `FuncVisitor` collects every `FunctionDef` into `func_map` keyed by `module.func` (or `module.Class.method` when the visitor is reused for class bodies). For each function it also stores a list of decorator name strings in `func_decorators`, handling bare names, dotted attributes, and `@deco(...)` calls.
  - `ClassVisitor` collects each `ClassDef` into `class_map`, then spawns a nested `FuncVisitor(class_name)` so methods get qualified names like `bs4.element.Tag.has_key`.

- **`check_for_deprecation.py`** — The detection rules. Uses **explicit-marker regexes** instead of a loose `"deprecat"` substring:
  - `_DOC_DEPRECATION_PATTERNS` — looks for `.. deprecated::`, `:deprecated:`, `deprecated since`, `is deprecated`, `has been deprecated`, `Deprecated.` at line start, etc. So `"this is not deprecated"` and `"undeprecated"` no longer trigger.
  - `_DECORATOR_DEPRECATION_RE` — matches `deprecated` only when preceded by start, `.`, or `_`, so `@deprecated`, `@_deprecated`, and `@pkg.deprecated` all match while `undeprecated` does not.
  - `_function_emits_deprecation_warning(node)` — walks the function body for any `Call` that resolves (via `_resolve_dotted`) to `warn` / `warnings.warn`, then inspects all positional args and `**kwargs` values for a reference to `DeprecationWarning`, `FutureWarning`, or `PendingDeprecationWarning`. It recognizes bare names (`DeprecationWarning`), dotted attributes (`warnings.DeprecationWarning`), and instantiations passed as the message itself (`DeprecationWarning("...")`).

  `extract_deprecations(class_map, func_map, func_decorators)` runs those three checks in order and returns `{ qualified_name: human_readable_reason }`. The reason also reports which warning class it found (e.g. `"Emits FutureWarning via warnings.warn()."`).

- **`analyzer.py`** — `UserCodeVisitor` walks the user script's AST and records every `Call` (qualified via `flatten_attr` into things like `div_tag.has_key`) along with its line number. `analyze_script()` then compares the **last segment** of each observed call against the last segment of every key in the knowledge base, and on a match returns `{line, called, warning}`.

- **`test_script.py`** — Sample input that calls three deprecated bs4 APIs (`has_key`, `isSelfClosing`, `nextGenerator`) so the scanner has something real to find.

