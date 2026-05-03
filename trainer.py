import os
import ast
import logging

from visitors import ClassVisitor, FuncVisitor
from check_for_deprecation import extract_deprecations

logger = logging.getLogger(__name__)


def train_on_library(library_path: str, base_module_name: str) -> dict:
    master_knowledge = {}

    for root, _, files in os.walk(library_path):
        for file in files:
            if not file.endswith(".py"):
                continue

            filepath = os.path.join(root, file)
            logger.info("  -> Parsing %s", file)

            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    source = f.read()
            except (OSError, UnicodeDecodeError) as exc:
                logger.warning("Could not read %s: %s", filepath, exc)
                continue

            try:
                tree = ast.parse(source)
            except SyntaxError as exc:
                logger.warning(
                    "Skipping %s: invalid Python syntax at line %s: %s",
                    filepath, exc.lineno, exc.msg,
                )
                continue

            rel_path = os.path.relpath(filepath, library_path)
            module_name = rel_path.replace(".py", "").replace(os.sep, ".")
            full_module_name = f"{base_module_name}.{module_name}"

            cv = ClassVisitor(full_module_name)
            cv.visit(tree)

            fv = FuncVisitor(full_module_name, skip_classes=True)
            fv.visit(tree)

            combined_funcs = {**cv.func_map, **fv.func_map}
            combined_decs = {**cv.func_decorators, **fv.func_decorators}

            file_deprecations = extract_deprecations(
                cv.class_map, combined_funcs, combined_decs
            )
            file_deprecations.update(cv.alias_map)
            master_knowledge.update(file_deprecations)

    # Remove entries whose function name or containing module/class name contains "deprecat". 
    def _is_deprecation_helper(key: str) -> bool:
        parts = key.lower().split(".")
        return any("deprecat" in p for p in parts[-2:])

    master_knowledge = {
        key: value
        for key, value in master_knowledge.items()
        if not _is_deprecation_helper(key)
    }

    return master_knowledge
