#!/usr/bin/env python3

import json
import subprocess
import sys
import os
from pathlib import Path


# ---------------- UTIL ----------------

def run_cmd(cmd, cwd):
    try:
        res = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return res.stdout.strip(), res.returncode
    except:
        return "", -1


# ---------------- TOOLS ----------------

def run_knip(repo):
    """
    Parse knip --reporter json output.

    Knip's JSON reporter emits:
      { "issues": [ { "file": "...", "files": <bool>,
                      "exports": [{"name": "..."}],
                      "dependencies": [{"name": "..."}],
                      "devDependencies": [{"name": "..."}] } ] }

    Returns normalised dicts so every consumer gets consistent shapes.
    """
    out, code = run_cmd("npx knip --reporter json", repo)

    # knip exits 1 when it finds issues (normal), 0 when clean
    if code not in (0, 1) or not out:
        return {"files": [], "unusedExports": [], "dependencies": []}

    try:
        data = json.loads(out)
        issues = data.get("issues", [])

        files = []           # list[str]  — paths of unused files
        unused_exports = []  # list[{file, name}]
        dep_names = []       # list[str]  — deduplicated dep names
        seen_deps = set()

        for entry in issues:
            f = entry.get("file", "")

            # "files" is a boolean flag on each issue entry
            if entry.get("files"):
                files.append(f)

            for exp in entry.get("exports", []):
                name = exp.get("name") or exp.get("symbol") or "?"
                unused_exports.append({"file": f, "name": name})

            raw_deps = (
                entry.get("dependencies", []) +
                entry.get("devDependencies", [])
            )
            for d in raw_deps:
                name = (d.get("name") or d.get("symbol") or "") if isinstance(d, dict) else str(d)
                if name and name not in seen_deps:
                    seen_deps.add(name)
                    dep_names.append(name)

        return {
            "files": files,
            "unusedExports": unused_exports,
            "dependencies": dep_names,
        }
    except:
        return {"files": [], "unusedExports": [], "dependencies": []}


def run_depcheck(repo):
    """
    depcheck --json output:
      { "dependencies": ["pkg-a", ...], "devDependencies": ["pkg-b", ...], ... }

    Returns a deduplicated list of unused package names covering both
    dependencies and devDependencies.
    """
    out, code = run_cmd("npx depcheck --json", repo)

    # depcheck exits 0 (clean) or non-zero when issues found — both OK
    if not out:
        return []

    try:
        data = json.loads(out)
        deps     = data.get("dependencies", [])
        dev_deps = data.get("devDependencies", [])

        seen   = set()
        result = []
        for name in deps + dev_deps:
            if name and name not in seen:
                seen.add(name)
                result.append(name)
        return result
    except:
        return []


def run_eslint(repo):
    cmd = (
        "npx eslint . -f json "
        "--rule 'no-unused-vars:error' "
        "--rule '@typescript-eslint/no-unused-vars:error'"
    )

    out, code = run_cmd(cmd, repo)

    results = []

    if code != 0 and not out:
        return results

    try:
        data = json.loads(out)

        for file in data:
            path = file.get("filePath")

            for msg in file.get("messages", []):
                rule = msg.get("ruleId") or ""
                if "unused" in rule:
                    results.append({
                        "file": path,
                        "line": msg.get("line"),
                        "message": msg.get("message"),
                        "confidence": 0.9
                    })
    except:
        pass

    return results


# ---------------- HELPERS ----------------

def get_package_json(repo):
    pkg = Path(repo) / "package.json"
    if not pkg.exists():
        return {}

    try:
        return json.loads(pkg.read_text())
    except:
        return {}


def get_cli_entries(repo):
    data = get_package_json(repo)
    entries = []

    bin_field = data.get("bin", {})

    if isinstance(bin_field, dict):
        entries.extend(bin_field.values())
    elif isinstance(bin_field, str):
        entries.append(bin_field)

    return [
        str((Path(repo) / e).resolve())
        for e in entries
        if (Path(repo) / e).exists()
    ]


def is_monorepo(repo):
    data = get_package_json(repo)
    return "workspaces" in data


def filter_cli_files(repo, files):
    """Remove bin entry-point files from the unused-files list."""
    entries = get_cli_entries(repo)
    cleaned = []
    for f in files:
        full = str((Path(repo) / f).resolve())
        if full not in entries:
            cleaned.append(f)
    return cleaned


def filter_runtime_files(files):
    ignore = ["bin/", "cli", "commands", "scripts", "middleware"]
    return [
        f for f in files
        if not any(x in f.lower() for x in ignore)
    ]


def make_file_objects(files, confidence, reason):
    """Convert a list of file-path strings to the normalised object shape."""
    return [
        {"file": f, "confidence": confidence, "reason": reason}
        for f in files
    ]


# ---------------- TYPE ANALYSIS ----------------

def analyze_application(repo):
    knip   = run_knip(repo)
    eslint = run_eslint(repo)
    deps   = run_depcheck(repo)

    # Lower confidence: application files are often loaded at runtime
    files = make_file_objects(
        knip["files"],
        confidence=0.4,
        reason="not statically referenced (may be used at runtime)"
    )

    return {
        "files":         files,
        "unusedExports": knip["unusedExports"],   # [{file, name}]
        "deps":          deps,                    # [str]
        "unusedCode":    eslint,
        "mode":          "application-balanced"
    }


def analyze_library(repo):
    knip   = run_knip(repo)
    eslint = run_eslint(repo)
    deps   = run_depcheck(repo)

    # Libraries are fully static — high confidence
    files = make_file_objects(
        knip["files"],
        confidence=0.9,
        reason="not reachable from any entry point"
    )

    return {
        "files":         files,
        "unusedExports": knip["unusedExports"],
        "deps":          deps,
        "unusedCode":    eslint,
        "mode":          "library-strict"
    }


def analyze_cli(repo):
    knip   = run_knip(repo)
    eslint = run_eslint(repo)
    deps   = run_depcheck(repo)

    # Remove bin entries and known runtime directories before scoring
    raw_files = filter_cli_files(repo, knip["files"])
    raw_files = filter_runtime_files(raw_files)

    files = make_file_objects(
        raw_files,
        confidence=0.8,
        reason="not reachable from any entry point"
    )

    return {
        "files":         files,
        "unusedExports": knip["unusedExports"],
        "deps":          deps,
        "unusedCode":    eslint,
        "mode":          "cli-safe"
    }


def analyze_plugin(repo):
    knip   = run_knip(repo)
    eslint = run_eslint(repo)
    deps   = run_depcheck(repo)

    files = make_file_objects(
        knip["files"],
        confidence=0.85,
        reason="not reachable from any entry point"
    )

    return {
        "files":         files,
        "unusedExports": knip["unusedExports"],
        "deps":          deps,
        "unusedCode":    eslint,
        "mode":          "plugin"
    }


def analyze_framework(repo):
    # Monorepos / frameworks: file-level analysis is unreliable
    # Focus only on dependency analysis
    return {
        "files":         [],
        "unusedExports": [],
        "deps":          run_depcheck(repo),
        "unusedCode":    run_eslint(repo),
        "mode":          "monorepo-safe"
    }


# ---------------- MAIN ----------------

def main():
    if len(sys.argv) < 3:
        print(json.dumps({"error": "usage: final_analysis.py <repoPath> <finalType>"}))
        return

    repo       = sys.argv[1]
    final_type = sys.argv[2]

    dispatch = {
        "application": analyze_application,
        "library":     analyze_library,
        "cli":         analyze_cli,
        "plugin":      analyze_plugin,
        "framework":   analyze_framework,
    }

    analyze = dispatch.get(final_type, analyze_application)
    result  = analyze(repo)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()