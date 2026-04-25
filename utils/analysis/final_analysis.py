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
            cmd, shell=True, cwd=cwd,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=180
        )
        return res.stdout.strip(), res.returncode
    except Exception as e:
        sys.stderr.write(f"[ERROR] {e}\n")
        return "", -1

def install_deps(repo):
    if not (Path(repo) / "package.json").exists():
        return
    # Use --package-lock-only or --prefer-offline for speed
    sys.stderr.write("[INFO] Preparing dependencies...\n")
    run_cmd("npm install --ignore-scripts --prefer-offline --silent", repo)

# ---------------- TOOLS ----------------

def run_knip(repo):
    install_deps(repo)
    # Using --no-exit-code because knip exits with count of issues
    out, _ = run_cmd("npx --yes knip --reporter json", repo)
    
    if not out:
        return {"files": [], "exports": [], "dependencies": []}

    try:
        data = json.loads(out)
        files = data.get("files", [])
        
        exports = []
        for issue in data.get("issues", []):
            file_path = issue.get("file", "unknown")
            for key in ["exports", "types", "nsExports"]:
                for item in issue.get(key, []):
                    exports.append({
                        "file": file_path,
                        "symbol": item.get("symbol") or item.get("name"),
                        "type": key[:-1] if key.endswith('s') else key
                    })

        return {
            "files": files,
            "exports": exports,
            "dependencies": data.get("dependencies", []) + data.get("devDependencies", [])
        }
    except:
        return {"files": [], "exports": [], "dependencies": []}

def run_depcheck(repo):
    out, _ = run_cmd("npx --yes depcheck --json", repo)
    if not out: return []
    try:
        data = json.loads(out)
        d = data.get("dependencies", [])
        dv = data.get("devDependencies", [])
        return (list(d.keys()) if isinstance(d, dict) else d) + \
               (list(dv.keys()) if isinstance(dv, dict) else dv)
    except:
        return []

# ---------------- ANALYSIS MODES ----------------

def analyze_application(repo):
    k = run_knip(repo)
    # Apps have high false positives for "unused files" (e.g. entry points, routes)
    return {
        "dead_files": [{"path": f, "confidence": 0.3} for f in k["files"]],
        "unused_deps": run_depcheck(repo),
        "mode": "application-relaxed"
    }

def analyze_library(repo):
    k = run_knip(repo)
    # Libraries should have very few unused exports
    return {
        "dead_files": [{"path": f, "confidence": 0.8} for f in k["files"]],
        "unused_exports": k["exports"],
        "unused_deps": run_depcheck(repo),
        "mode": "library-strict"
    }

def analyze_cli(repo):
    k = run_knip(repo)
    # Filter out common CLI entry points from dead file list
    clean_files = [f for f in k["files"] if not any(x in f.lower() for x in ["bin", "cli", "main"])]
    return {
        "dead_files": clean_files,
        "unused_deps": run_depcheck(repo),
        "mode": "cli-standard"
    }

def analyze_generic(repo):
    return {"dead_files": run_knip(repo)["files"], "unused_deps": run_depcheck(repo), "mode": "generic"}

# ---------------- MAIN ----------------

def main():
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: final_analysis.py <path> <type>"}))
        sys.exit(1)

    repo = sys.argv[1]
    repo_type = sys.argv[2]

    dispatch = {
        "application": analyze_application,
        "library": analyze_library,
        "cli": analyze_cli,
        "framework": analyze_generic,
        "plugin": analyze_library
    }

    handler = dispatch.get(repo_type, analyze_generic)
    results = handler(repo)
    
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    main()