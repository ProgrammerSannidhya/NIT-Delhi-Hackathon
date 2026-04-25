#!/usr/bin/env python3

import json
import subprocess
import sys
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
            text=True,
            timeout=120
        )
        return res.stdout.strip(), res.returncode
    except subprocess.TimeoutExpired:
        sys.stderr.write(f"[TIMEOUT] Command timed out: {cmd}\n")
        return "", -1
    except Exception as e:
        sys.stderr.write(f"[ERROR] run_cmd failed: {e}\n")
        return "", -1


# ---------------- SETUP ----------------

def install_deps(repo):
    pkg = Path(repo) / "package.json"
    if not pkg.exists():
        return

    sys.stderr.write("[INFO] Running npm install...\n")
    _, code = run_cmd("npm install --ignore-scripts --prefer-offline --silent", repo)
    if code != 0:
        run_cmd("npm install --ignore-scripts --silent", repo)
    sys.stderr.write("[INFO] npm install done\n")


# ---------------- TOOLS ----------------

def run_knip(repo):
    install_deps(repo)

    try:
        process = subprocess.run(
            ["npx", "--yes", "knip", "--reporter", "json"],
            cwd=repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        out = process.stdout.strip()

        if not out:
            sys.stderr.write(f"[WARN] knip returned no output (exit code {process.returncode})\n")
            return {"files": [], "exports": [], "dependencies": []}

        try:
            data = json.loads(out)
        except json.JSONDecodeError as e:
            sys.stderr.write(f"[ERROR] knip JSON parse failed: {e}\nRaw: {out[:500]}\n")
            return {"files": [], "exports": [], "dependencies": []}

        files = data.get("files", [])

        exports = []
        for issue in data.get("issues", []):
            file_path = issue.get("file", "unknown")

            for exp in issue.get("exports", []):
                symbol = exp.get("symbol") or exp.get("name", "?")
                exports.append({
                    "file": file_path,
                    "symbol": symbol,
                    "type": exp.get("type", "export"),
                    "line": exp.get("line"),
                    "col": exp.get("col"),
                })

            for t in issue.get("types", []):
                symbol = t.get("symbol") or t.get("name", "?")
                exports.append({
                    "file": file_path,
                    "symbol": symbol,
                    "type": "type",
                    "line": t.get("line"),
                    "col": t.get("col"),
                })

            for ns in issue.get("nsExports", []):
                symbol = ns.get("symbol") or ns.get("name", "?")
                exports.append({
                    "file": file_path,
                    "symbol": symbol,
                    "type": "nsExport",
                    "line": ns.get("line"),
                    "col": ns.get("col"),
                })

        dependencies = (
            data.get("dependencies", []) +
            data.get("devDependencies", [])
        )

        return {
            "files": files,
            "exports": exports,
            "dependencies": dependencies,
        }

    except Exception as e:
        sys.stderr.write(f"[ERROR] knip execution failed: {e}\n")
        return {"files": [], "exports": [], "dependencies": []}


def run_depcheck(repo):
    out, code = run_cmd("npx --yes depcheck --json", repo)

    if not out:
        sys.stderr.write(f"[WARN] depcheck returned no output (exit code {code})\n")
        return []

    try:
        data = json.loads(out)

        prod_deps = data.get("dependencies", [])
        dev_deps = data.get("devDependencies", [])

        if isinstance(prod_deps, dict):
            prod_deps = list(prod_deps.keys())
        if isinstance(dev_deps, dict):
            dev_deps = list(dev_deps.keys())

        return prod_deps + dev_deps

    except json.JSONDecodeError as e:
        sys.stderr.write(f"[ERROR] depcheck JSON parse failed: {e}\n")
        return []


def run_eslint(repo):
    eslint_config = json.dumps({
        "env": {"es2021": True, "node": True},
        "rules": {"no-unused-vars": "error"},
        "parserOptions": {"ecmaVersion": 2021, "sourceType": "module"}
    })

    config_path = Path(repo) / ".eslint_dead_scan.json"

    try:
        config_path.write_text(eslint_config)

        cmd = "npx --yes eslint . -f json --no-eslintrc -c .eslint_dead_scan.json --ext .js,.mjs,.cjs 2>/dev/null"
        out, _ = run_cmd(cmd, repo)

    finally:
        if config_path.exists():
            config_path.unlink()

    results = []

    if not out:
        return results

    try:
        data = json.loads(out)
        for file_report in data:
            path = file_report.get("filePath", "")
            for msg in file_report.get("messages", []):
                rule = msg.get("ruleId") or ""
                if "unused" in rule:
                    results.append({
                        "file": path,
                        "line": msg.get("line"),
                        "message": msg.get("message"),
                        "confidence": 0.9,
                    })
    except json.JSONDecodeError:
        pass

    return results


# ---------------- HELPERS ----------------

def get_package_json(repo):
    pkg = Path(repo) / "package.json"
    if not pkg.exists():
        return {}

    try:
        return json.loads(pkg.read_text())
    except Exception:
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
    return "workspaces" in get_package_json(repo)


def filter_cli_files(repo, files):
    entries = get_cli_entries(repo)
    return [
        f for f in files
        if str((Path(repo) / f).resolve()) not in entries
    ]


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

    files = [
        {
            "file": f,
            "confidence": 0.4,
            "reason": "not statically referenced (may be used at runtime)",
        }
        for f in knip["files"]
    ]

    return {
        "files": files,
        "unusedExports": knip["exports"],
        "deps": deps,
        "unusedCode": eslint,
        "mode": "application-balanced",
    }


def analyze_library(repo):
    knip = run_knip(repo)
    return {
        "files": knip["files"],
        "unusedExports": knip["exports"],
        "deps": run_depcheck(repo),
        "unusedCode": run_eslint(repo),
        "mode": "library-strict",
    }


def analyze_cli(repo):
    knip = run_knip(repo)
    files = filter_runtime_files(filter_cli_files(repo, knip["files"]))

    return {
        "files": files,
        "unusedExports": knip["exports"],
        "deps": run_depcheck(repo),
        "unusedCode": run_eslint(repo),
        "mode": "cli-safe",
    }


def analyze_plugin(repo):
    knip = run_knip(repo)
    return {
        "files": knip["files"],
        "unusedExports": knip["exports"],
        "deps": run_depcheck(repo),
        "unusedCode": run_eslint(repo),
        "mode": "plugin",
    }


def analyze_framework(repo):
    return {
        "files": [],
        "unusedExports": [],
        "deps": run_depcheck(repo),
        "unusedCode": run_eslint(repo),
        "mode": "monorepo-safe",
    }


# ---------------- MAIN ----------------

def main():
    if len(sys.argv) < 3:
        print(json.dumps({"error": "usage: final_analysis.py <repo> <type>"}))
        sys.exit(1)

    repo = sys.argv[1]
    final_type = sys.argv[2]

    if not Path(repo).exists():
        print(json.dumps({"error": f"repo path does not exist: {repo}"}))
        sys.exit(1)

    dispatch = {
        "application": analyze_application,
        "library": analyze_library,
        "cli": analyze_cli,
        "plugin": analyze_plugin,
        "framework": analyze_framework,
    }

    analyze_fn = dispatch.get(final_type, analyze_application)
    result = analyze_fn(repo)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()