import os
import logging

from trainer import train_on_library
from analyzer import analyze_script

logger = logging.getLogger("api_scanner")


class _CleanFormatter(logging.Formatter):
    """Show INFO progress lines bare; prefix anything WARN+ with its level."""

    def format(self, record):
        if record.levelno <= logging.INFO:
            return record.getMessage()
        return f"{record.levelname}: {record.getMessage()}"


def _configure_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(_CleanFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def run():
    _configure_logging()

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    libraries_dir = os.path.join(BASE_DIR, "libraries")

    master_knowledge = {}

    logger.info("--- STEP 1: FEEDING LIBRARIES ---")

    for lib_name in os.listdir(libraries_dir):
        lib_path = os.path.join(libraries_dir, lib_name)
        if not os.path.isdir(lib_path):
            continue

        logger.info("[Scanning Library: %s]", lib_name)
        lib_knowledge = train_on_library(lib_path, base_module_name=lib_name)
        master_knowledge.update(lib_knowledge)
        logger.info(" -> Found %d deprecations in %s", len(lib_knowledge), lib_name)

    logger.info(
        "[Total Knowledge Base Built: %d known deprecations]",
        len(master_knowledge),
    )

    logger.info("--- STEP 2: ANALYZING SCRIPT ---")
    script_path = os.path.join(BASE_DIR, "test_script.py")
    logger.info("Analyzing %s", script_path)

    findings = analyze_script(script_path, master_knowledge)

    print()
    if not findings:
        print("No deprecations found! Your code is clean.")
        return

    print("DEPRECATIONS FOUND:")
    for issue in findings:
        resolved = issue.get("resolved") or issue["called"]
        suffix = ""
        if resolved and resolved != issue["called"]:
            suffix = f" (resolved as {resolved})"
        dep_api = issue.get("deprecated_api", "")
        match_note = f" [matches {dep_api}]" if dep_api else ""
        print(
            f"Line {issue['line']}: Call to '{issue['called']}'"
            f"{suffix} -> {issue['warning']}{match_note}"
        )


if __name__ == "__main__":
    run()
