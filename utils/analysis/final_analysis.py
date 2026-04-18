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
    out, code = run_cmd("npx knip --reporter json", repo)

    if code != 0 or not out:
        return {"files": [], "exports": [], "dependencies": []}

    try:
        data = json.loads(out)
        return {
            "files": data.get("files", []),
            "exports": data.get("exports", []),
            "dependencies": data.get("dependencies", [])
        }
    except:
        return {"files": [], "exports": [], "dependencies": []}


def run_depcheck(repo):
    out, code = run_cmd("npx depcheck --json", repo)

    if code != 0 or not out:
        return []

    try:
        return json.loads(out).get("dependencies", [])
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


# ---------------- TYPE ANALYSIS ----------------

def analyze_application(repo):
    knip = run_knip(repo)
    eslint = run_eslint(repo)
    deps = run_depcheck(repo)

    # DO NOT hide files → just lower confidence
    files = [
        {
            "file": f,
            "confidence": 0.4,
            "reason": "not statically referenced (may be used at runtime)"
        }
        for f in knip["files"]
    ]

    return {
        "files": files,
        "unusedExports": knip["exports"],
        "deps": deps,
        "unusedCode": eslint,
        "mode": "application-balanced"
    }


def analyze_library(repo):
    knip = run_knip(repo)

    return {
        "files": knip["files"],
        "unusedExports": knip["exports"],
        "deps": run_depcheck(repo),
        "unusedCode": run_eslint(repo),
        "mode": "library-strict"
    }


def analyze_cli(repo):
    knip = run_knip(repo)

    files = knip["files"]
    files = filter_cli_files(repo, files)
    files = filter_runtime_files(files)

    return {
        "files": files,
        "unusedExports": knip["exports"],
        "deps": run_depcheck(repo),
        "unusedCode": run_eslint(repo),
        "mode": "cli-safe"
    }


def analyze_plugin(repo):
    knip = run_knip(repo)

    return {
        "files": knip["files"],
        "unusedExports": knip["exports"],
        "deps": run_depcheck(repo),
        "unusedCode": run_eslint(repo),
        "mode": "plugin"
    }


def analyze_framework(repo):
    # monorepo → file-level unreliable
    return {
        "files": [],
        "unusedExports": [],
        "deps": run_depcheck(repo),
        "unusedCode": run_eslint(repo),
        "mode": "monorepo-safe"
    }


# ---------------- MAIN ----------------

def main():
    if len(sys.argv) < 3:
        print(json.dumps({"error": "usage: repoPath finalType"}))
        return

    repo = sys.argv[1]
    final_type = sys.argv[2]

    if final_type == "application":
        result = analyze_application(repo)

    elif final_type == "library":
        result = analyze_library(repo)

    elif final_type == "cli":
        result = analyze_cli(repo)

    elif final_type == "plugin":
        result = analyze_plugin(repo)

    elif final_type == "framework":
        result = analyze_framework(repo)

    else:
        result = analyze_application(repo)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
