import ast


class FuncVisitor(ast.NodeVisitor):
    def __init__(self, base_name):
        self.base_name = base_name
        self.func_map = {}
        self.func_decorators = {}

    def flatten_attr(self, node):
        if isinstance(node, ast.Attribute):
            return f"{self.flatten_attr(node.value)}.{node.attr}"
        elif isinstance(node, ast.Name):
            return node.id
        return ""

    def generic_visit(self, node):
        if isinstance(node, ast.FunctionDef):
            func_name = f"{self.base_name}.{node.name}" if self.base_name else node.name
            self.func_map[func_name] = node

            decorators = []
            for dec in node.decorator_list:
                if isinstance(dec, ast.Name):
                    decorators.append(dec.id)
                elif isinstance(dec, ast.Attribute):
                    decorators.append(self.flatten_attr(dec))
                elif isinstance(dec, ast.Call):
                    if isinstance(dec.func, ast.Name):
                        decorators.append(dec.func.id)
            self.func_decorators[func_name] = decorators

        ast.NodeVisitor.generic_visit(self, node)


class ClassVisitor(ast.NodeVisitor):
    def __init__(self, base_name):
        self.base_name = base_name
        self.class_map = {}
        self.func_map = {}
        self.func_decorators = {}

    def generic_visit(self, node):
        if isinstance(node, ast.ClassDef):
            class_name = f"{self.base_name}.{node.name}" if self.base_name else node.name
            self.class_map[class_name] = node

            fv = FuncVisitor(class_name)
            fv.visit(node)
            self.func_map.update(fv.func_map)
            self.func_decorators.update(fv.func_decorators)

        ast.NodeVisitor.generic_visit(self, node)
