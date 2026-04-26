# API Deprecation Scanner (Web UI)

A full-stack static analysis tool that AST-parses third-party libraries to build a knowledge base of deprecated APIs, then scans a user script for any calls to those APIs.

FastAPI backend for in-memory AST processing, frontend for uploading libraries and analyzing scripts dynamically.

## How to run

### Requirements
- Python 3.9+
- FastAPI suite: `fastapi`, `uvicorn`, `python-multipart`, `pydantic-settings`

### Setup
```bash
git clone <this-repo>
cd API-Scanner-Using-FastAPI

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Run the Application
1. Start the backend server:
   ```bash
   uvicorn api:app --reload
   ```
   The API will start at `http://127.0.0.1:8000`. You can view the auto-generated Swagger documentation at `http://127.0.0.1:8000/docs`.

2. Open the frontend: Simply double-click the `index.html` file to open it in your web browser (e.g., Chrome, Edge, Safari). No frontend build step is required.

### Scan your own code
1. **Train the Engine**: Zip a library's source code folder (e.g., compress the `bs4` folder into `bs4.zip`). In the UI under "1. Train Library", upload the `.zip` file. The backend will extract it, parse the ASTs, and update `knowledge_base.json`.
2. **Analyze a Script**: In the UI under "2. Analyze Script", upload the `.py` script you want analyzed (like `test_script.py`).
3. **View Results**: The UI will display a clean table showing the line numbers, the called API, the source library it belongs to, and the reason it was flagged as deprecated.
4. **Reset**: Use the "Reset Knowledge Base" button to wipe the `.json` database and start fresh.

## How the codebase works

### Overall flow
- **Two phases**:
  - **Train (`POST /train`)** — Unzips an uploaded library, builds a knowledge base of deprecated APIs by AST-parsing every `.py` file, and saves it to `knowledge_base.json`.
  - **Analyze (`POST /analyze`)** — AST-parses an uploaded `.py` script and cross-references its method calls against the `knowledge_base.json`, returning a JSON array of matches to the frontend.

### File roles

- **`api.py`** — The FastAPI entry point. Replaces the old CLI orchestrator. It manages application settings via `pydantic-settings`, sets up CORS so the browser can communicate with it, and defines the three core REST endpoints (`/train`, `/analyze`, `/reset`). It handles temporary file saving, ZIP extraction, and cleanup gracefully.

- **`index.html`** — A standalone, dependency-free frontend using vanilla JavaScript and CSS. It uses the `fetch` API to send `FormData` to the backend and dynamically renders the results into an HTML table, complete with status badges and error handling.

- **`trainer.py`** — `train_on_library(library_path, base_module_name)` walks every `.py` file in the extracted library. For each file it:
  - Reads the source, safely catching and skipping on `OSError` / `UnicodeDecodeError`.
  - Calls `ast.parse()`, safely catching and logging on `SyntaxError`.
  - Builds a fully qualified module name from the relative path (e.g. `bs4.element`).
  - Runs `ClassVisitor` and `FuncVisitor` over the AST, hands their maps to `extract_deprecations()`, and merges in `ClassVisitor.alias_map` (class-body alias assignments — see below).

- **`visitors.py`** — Two `ast.NodeVisitor`s.
  - `FuncVisitor` collects every `FunctionDef` and `AsyncFunctionDef` into `func_map` keyed by `module.func` (or `module.Class.method` when reused for class bodies). For each function it also stores a list of decorator name strings in `func_decorators`, handling bare names (`@deprecated`), dotted attributes (`@pkg.deprecated`), `@deco(...)` calls, and `@pkg.deco(...)` attribute-call decorators.
  - `ClassVisitor` collects each `ClassDef` into `class_map`, spawns a nested `FuncVisitor(class_name)` so methods get qualified names like `bs4.element.Tag.has_key`, and additionally scans the class body for `ast.Assign` / `ast.AnnAssign` statements where the right-hand side calls a deprecation-wrapper function (e.g. `findAll = _deprecated_function_alias("findAll", "find_all", "4.0.0")`). Each such alias is recorded in `alias_map` keyed by `Class.<assigned_name>`. This catches the common BeautifulSoup pattern of declaring an old camelCase API as a wrapped alias of the new name.

- **`check_for_deprecation.py`** — The detection rules. Uses explicit-marker regexes instead of a loose "deprecat" substring:
  - `_DOC_DEPRECATION_PATTERNS` — looks for `.. deprecated::`, `:deprecated:`, `deprecated since`, `is deprecated`, `has been deprecated`, `Deprecated.` at line start, etc. So "this is not deprecated" and "undeprecated" no longer trigger.
  - `_DECORATOR_DEPRECATION_RE` — matches `deprecat` only when preceded by start, `.`, or `_`, so `@deprecated`, `@_deprecated`, `@pkg.deprecated`, and wrappers like `_deprecated_function_alias` all match while `undeprecated` / `notdeprecated` do not. Exposed via the helper `is_deprecation_wrapper_name(name)`.
  - `_function_emits_deprecation_warning(node)` — walks the function body for any `Call` that resolves (via `_resolve_dotted`) to `warn` / `warnings.warn`, then inspects all args and kwargs for a reference to `DeprecationWarning`, `FutureWarning`, or `PendingDeprecationWarning`.
  - `extract_deprecations()` runs those three checks in order and returns `{ qualified_name: human_readable_reason }`.

- **`analyzer.py`** — Import-aware script scanner. Two passes over the user script's AST:
  - `_SymbolTable` (an `ast.NodeVisitor`) handles imports, functions, classes, and assignments. It records bindings (local name → fully qualified target), `imported_roots` (packages the script can see), star_imports, and locals (names defined in this script). Simple `name = ImportedThing(...)` assignments are tracked (`soup = BeautifulSoup(...)` makes `soup` resolve to `bs4.BeautifulSoup`).
  - `_CallVisitor` records every `Call` (qualified via `_flatten_attr` into things like `div_tag.has_key`) with its line number.
  - Matching (`_is_match`) has strict rules: (a) a resolved call matches only if they share a root package, (b) an unresolved receiver (e.g., `div_tag.has_key`) only matches if the deprecated key's root module is actually imported by the script, and (c) local definitions are never flagged. Returns a dictionary including the newly extracted library name.

- **`test_script.py`** — Sample input that calls deprecated `bs4` APIs (`has_key`, `isSelfClosing`, `nextGenerator`) for quick testing.
