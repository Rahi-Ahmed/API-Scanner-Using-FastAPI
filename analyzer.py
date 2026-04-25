import ast


class UserCodeVisitor(ast.NodeVisitor):
    def __init__(self):
        self.used_calls = []

    def flatten_attr(self, node):
        if isinstance(node, ast.Attribute):
            return f"{self.flatten_attr(node.value)}.{node.attr}"
        elif isinstance(node, ast.Name):
            return node.id
        return ""

    def generic_visit(self, node):
        if isinstance(node, ast.Call):
            call_name = self.flatten_attr(node.func)
            if call_name:
                self.used_calls.append({
                    "name": call_name,
                    "line": node.lineno
                })
        ast.NodeVisitor.generic_visit(self, node)


def analyze_script(script_path: str, knowledge_base: dict) -> list:
    results = []
    with open(script_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    visitor = UserCodeVisitor()
    visitor.visit(tree)

    for call in visitor.used_calls:
        called_method_name = call["name"].split('.')[-1]

        for deprecated_api, warning in knowledge_base.items():
            deprecated_method_name = deprecated_api.split('.')[-1]

            if called_method_name == deprecated_method_name:
                results.append({
                    "line": call["line"],
                    "called": call["name"],
                    "warning": warning,
                })
                break

    return results
