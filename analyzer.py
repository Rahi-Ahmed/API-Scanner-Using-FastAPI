import ast


def _flatten_attr(node):
    if isinstance(node, ast.Attribute):
        base = _flatten_attr(node.value)
        return f"{base}.{node.attr}" if base else ""
    if isinstance(node, ast.Name):
        return node.id
    return ""


class _SymbolTable(ast.NodeVisitor):
    """Best-effort name resolution for the script under analysis.

    Tracks imports, simple `name = ImportedThing(...)` assignments, and
    locally-defined names so that the analyzer can:
      - Promote `BeautifulSoup(...)` calls to `bs4.BeautifulSoup`.
      - Avoid flagging local `def close()` calls just because some
        unrelated library defines a deprecated `close()`.
      - Gate unresolved-receiver calls (`div_tag.has_key(...)`) by the
        set of modules actually imported by this script.
    """

    def __init__(self):
        # local_name -> qualified target string (e.g. "bs4.BeautifulSoup").
        self.bindings = {}
        # Root packages reachable from any import (e.g. {"bs4"}).
        self.imported_roots = set()
        # Roots brought in via `from pkg import *`.
        self.star_imports = set()
        # Names defined in this script (def / class / shadowed bindings).
        self.locals = set()

    def _shadow(self, name):
        self.bindings.pop(name, None)

    def visit_Import(self, node):
        # For `import a.b.c`, Python binds only the top-level name `a`, and
        # `a.b.c` is reachable through attribute lookup. So bind `a -> a` in
        # that case, otherwise we'd double-prefix (`a -> a.b.c` would turn
        # `a.b.c.foo` into `a.b.c.b.c.foo`). When `as` is used, the alias
        # is bound to the full dotted path.
        for alias in node.names:
            qualified = alias.name
            root = qualified.split(".", 1)[0]
            if alias.asname:
                self.bindings[alias.asname] = qualified
            else:
                self.bindings[root] = root
            self.imported_roots.add(root)

    def visit_ImportFrom(self, node):
        module = node.module or ""
        if module:
            self.imported_roots.add(module.split(".", 1)[0])
        for alias in node.names:
            if alias.name == "*":
                if module:
                    self.star_imports.add(module.split(".", 1)[0])
                continue
            local = alias.asname or alias.name
            qualified = f"{module}.{alias.name}" if module else alias.name
            self.bindings[local] = qualified

    def visit_FunctionDef(self, node):
        self.locals.add(node.name)
        self._shadow(node.name)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self.visit_FunctionDef(node)

    def visit_ClassDef(self, node):
        self.locals.add(node.name)
        self._shadow(node.name)
        self.generic_visit(node)

    def visit_Assign(self, node):
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            inferred = self._infer_value_type(node.value)
            if inferred is not None:
                self.bindings[name] = inferred
        self.generic_visit(node)

    def _infer_value_type(self, value):
        # Only resolve direct constructor-like calls to keep the inference
        # honest. We deliberately do NOT chase chained calls like
        # `soup.find('div')`, since we'd be guessing at the return type.
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            if value.func.id in self.bindings:
                return self.bindings[value.func.id]
        if isinstance(value, ast.Name) and value.id in self.bindings:
            return self.bindings[value.id]
        return None

    def resolve_call(self, dotted_call_name):
        """Return ``(qualified, root, is_local)`` for a call's dotted name."""
        if not dotted_call_name:
            return None, None, False
        head = dotted_call_name.partition(".")[0]
        if head in self.bindings:
            base = self.bindings[head]
            rest = dotted_call_name[len(head):]
            qualified = base + rest
            return qualified, qualified.partition(".")[0], False
        if head in self.locals:
            return None, None, True
        return None, None, False


class _CallVisitor(ast.NodeVisitor):
    def __init__(self):
        self.calls = []

    def visit_Call(self, node):
        name = _flatten_attr(node.func)
        if name:
            self.calls.append({"name": name, "line": node.lineno})
        self.generic_visit(node)


def _is_match(call_ctx, dep_key, symbols):
    if call_ctx["is_local"]:
        return False

    leaf = call_ctx["leaf"]
    if leaf != dep_key.rsplit(".", 1)[-1]:
        return False

    dep_root = dep_key.split(".", 1)[0]
    qualified = call_ctx["qualified"]

    if qualified is not None:
        if dep_key == qualified:
            return True
        # Same root package, same leaf — accept since we cannot follow
        # return types deeply (e.g. soup.find -> Tag).
        return dep_root == qualified.partition(".")[0]

    return dep_root in symbols.imported_roots or dep_root in symbols.star_imports


def analyze_script(script_path: str, knowledge_base: dict) -> list:
    with open(script_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    symbols = _SymbolTable()
    symbols.visit(tree)

    call_visitor = _CallVisitor()
    call_visitor.visit(tree)

    results = []
    for call in call_visitor.calls:
        qualified, root, is_local = symbols.resolve_call(call["name"])
        ctx = {
            "name": call["name"],
            "line": call["line"],
            "leaf": call["name"].rsplit(".", 1)[-1],
            "qualified": qualified,
            "root": root,
            "is_local": is_local,
        }
        for dep_key, warning in knowledge_base.items():
            if _is_match(ctx, dep_key, symbols):
                results.append({
                    "line": call["line"],
                    "called": call["name"],
                    "resolved": qualified or call["name"],
                    "deprecated_api": dep_key,
                    "library": dep_key.split(".")[0], 
                    "warning": warning,
                })
                break

    return results
