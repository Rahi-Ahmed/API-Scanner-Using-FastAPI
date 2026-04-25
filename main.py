import os
import logging

from trainer import train_on_library
from analyzer import analyze_script


def run():
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    libraries_dir = os.path.join(BASE_DIR, "libraries")

    master_knowledge = {}

    print("--- STEP 1: FEEDING LIBRARIES ---")

    for lib_name in os.listdir(libraries_dir):
        lib_path = os.path.join(libraries_dir, lib_name)
        if not os.path.isdir(lib_path):
            continue

        print(f"\n[Scanning Library: {lib_name}]")
        lib_knowledge = train_on_library(lib_path, base_module_name=lib_name)
        master_knowledge.update(lib_knowledge)
        print(f" -> Found {len(lib_knowledge)} deprecations in {lib_name}")

    print(f"\n[Total Knowledge Base Built: {len(master_knowledge)} known deprecations]")

    print("\n--- STEP 2: ANALYZING SCRIPT ---")
    script_path = os.path.join(BASE_DIR, "test_script.py")
    print(f"Analyzing {script_path}...\n")

    findings = analyze_script(script_path, master_knowledge)

    if not findings:
        print("No deprecations found! Your code is clean.")
    else:
        print("DEPRECATIONS FOUND:")
        for issue in findings:
            print(f"Line {issue['line']}: Call to '{issue['called']}' -> {issue['warning']}")


if __name__ == "__main__":
    run()
