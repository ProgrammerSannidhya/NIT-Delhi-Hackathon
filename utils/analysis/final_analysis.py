#!/usr/bin/env python3

import json
import re
import sys
from pathlib import Path

# ---------------- FILE SCAN ----------------

IMPORT_RE = re.compile(
    r'import\s+.*?\s+from\s+[\'"]([^\'"]+)[\'"]|require\(\s*[\'"]([^\'"]+)[\'"]\s*\)'
)

def extract_imports(file_path):
    imports = set()

    try:
        content = file_path.read_text(errors="ignore")

        for match in IMPORT_RE.findall(content):
            dep = match[0] or match[1]

            if not dep:
                continue

            # ignore relative imports
            if dep.startswith("."):
                continue

            # handle scoped packages
            if dep.startswith("@"):
                parts = dep.split("/")
                dep = "/".join(parts[:2])
            else:
                dep = dep.split("/")[0]

            imports.add(dep)

    except Exception:
        pass

    return imports


# ---------------- DEP ANALYSIS ----------------

def get_all_imports(repo):
    used = set()

    for f in Path(repo).rglob("*.[jt]s"):
        used.update(extract_imports(f))

    return used


def get_package_deps(repo):
    deps = set()

    pkg_files = [Path(repo) / "package.json"] + list(Path(repo).glob("*/package.json"))

    for pkg in pkg_files:
        if not pkg.exists():
            continue

        try:
            data = json.loads(pkg.read_text())

            deps.update(data.get("dependencies", {}).keys())
            deps.update(data.get("devDependencies", {}).keys())

        except Exception:
            pass

    return deps


def find_unused_deps(repo):
    declared = get_package_deps(repo)
    used = get_all_imports(repo)

    unused = []

    for dep in declared:
        if dep not in used:
            unused.append({
                "name": dep,
                "confidence": 0.9,
                "reason": "not imported anywhere"
            })

    return unused


# ---------------- EXPORT ANALYSIS ----------------

EXPORT_RE = re.compile(
    r'export\s+(?:const|function|class|default)?\s*([a-zA-Z0-9_]*)'
)

def find_exports(repo):
    exports = []

    for f in Path(repo).rglob("*.[jt]s"):
        try:
            content = f.read_text(errors="ignore")

            for match in EXPORT_RE.findall(content):
                exports.append({
                    "file": str(f),
                    "symbol": match or "default",
                    "confidence": 0.7
                })

        except Exception:
            pass

    return exports


# ---------------- FILE ANALYSIS ----------------

def find_files(repo):
    files = []

    for f in Path(repo).rglob("*.[jt]s"):
        files.append({
            "file": str(f),
            "confidence": 0.5
        })

    return files


# ---------------- MAIN ----------------

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "repo path missing"}))
        return

    repo = sys.argv[1]

    if not Path(repo).exists():
        print(json.dumps({"error": "invalid path"}))
        return

    result = {
        "files": find_files(repo),
        "unusedExports": find_exports(repo),
        "deps": find_unused_deps(repo),
        "unusedCode": [],
        "mode": "static-analysis"
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()