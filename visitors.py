import ast

from check_for_deprecation import is_deprecation_wrapper_name


def _flatten_attr(node):
    if isinstance(node, ast.Attribute):
        base = _flatten_attr(node.value)
        return f"{base}.{node.attr}" if base else ""
    if isinstance(node, ast.Name):
        return node.id
    return ""


class FuncVisitor(ast.NodeVisitor):
    def __init__(self, base_name):
        self.base_name = base_name
        self.func_map = {}
        self.func_decorators = {}

    def flatten_attr(self, node):
        return _flatten_attr(node)

    def generic_visit(self, node):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_name = f"{self.base_name}.{node.name}" if self.base_name else node.name
            self.func_map[func_name] = node

            decorators = []
            for dec in node.decorator_list:
                if isinstance(dec, ast.Name):
                    decorators.append(dec.id)
                elif isinstance(dec, ast.Attribute):
                    decorators.append(_flatten_attr(dec))
                elif isinstance(dec, ast.Call):
                    if isinstance(dec.func, ast.Name):
                        decorators.append(dec.func.id)
                    elif isinstance(dec.func, ast.Attribute):
                        decorators.append(_flatten_attr(dec.func))
            self.func_decorators[func_name] = decorators

        ast.NodeVisitor.generic_visit(self, node)


class ClassVisitor(ast.NodeVisitor):
    def __init__(self, base_name):
        self.base_name = base_name
        self.class_map = {}
        self.func_map = {}
        self.func_decorators = {}
        # Class-body assignments that bind a name to a deprecation-wrapper
        # call, e.g. `findAll = _deprecated_function_alias("findAll", ...)`.
        # qualified_name -> human-readable reason.
        self.alias_map = {}

    def generic_visit(self, node):
        if isinstance(node, ast.ClassDef):
            class_name = f"{self.base_name}.{node.name}" if self.base_name else node.name
            self.class_map[class_name] = node

            fv = FuncVisitor(class_name)
            fv.visit(node)
            self.func_map.update(fv.func_map)
            self.func_decorators.update(fv.func_decorators)

            for stmt in node.body:
                self._scan_class_body_alias(stmt, class_name)

        ast.NodeVisitor.generic_visit(self, node)

    def _scan_class_body_alias(self, stmt, class_name):
        if isinstance(stmt, ast.Assign):
            targets, value = stmt.targets, stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            targets, value = [stmt.target], stmt.value
        else:
            return

        if not isinstance(value, ast.Call):
            return

        callee = _flatten_attr(value.func)
        if not is_deprecation_wrapper_name(callee):
            return

        for target in targets:
            if isinstance(target, ast.Name):
                qualified = f"{class_name}.{target.id}"
                self.alias_map[qualified] = (
                    f"Class-body alias to deprecation wrapper `{callee}`."
                )
