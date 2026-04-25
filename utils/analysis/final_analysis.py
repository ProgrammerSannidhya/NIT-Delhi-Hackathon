#!/usr/bin/env python3

import json
import subprocess
import sys
import re
import shlex
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
    installed = False

    for pkg in [Path(repo) / "package.json"] + list(Path(repo).glob("*/package.json")):
        if pkg.exists():
            cwd = str(pkg.parent)
            sys.stderr.write(f"[INFO] npm install in {cwd}...\n")

            _, code = run_cmd(
                "npm install --ignore-scripts --prefer-offline --silent",
                cwd
            )

            if code != 0:
                run_cmd("npm install --ignore-scripts --silent", cwd)

            installed = True

    if installed:
        sys.stderr.write("[INFO] npm install done\n")


# ---------------- TEST FILE DETECTION ----------------

_TEST_PATH_PATTERNS = re.compile(
    r'(^|/)(__tests__|tests?|spec|cypress|e2e|fixtures?|mocks?|__mocks__)(/|$)'
    r'|\.(?:test|spec)\.[jt]sx?$',
    re.IGNORECASE,
)


def _is_test_file(path_str: str) -> bool:
    return bool(_TEST_PATH_PATTERNS.search(path_str))


# ---------------- SCRIPT EXTRACTION ----------------

def _extract_script_commands(script_val: str) -> set:
    tokens = set()

    try:
        for segment in re.split(r'[&|;]', script_val):
            segment = segment.strip()

            if not segment:
                continue

            parts = shlex.split(segment)

            if parts:
                tokens.add(parts[0].split("/")[-1])

    except Exception:
        for token in re.findall(r'[\w][\w\-]+', script_val):
            tokens.add(token)

    return tokens


# ---------------- CONTEXT ----------------

def get_repo_context(repo):
    ctx = {
        "has_gruntfile": False,
        "has_gulpfile": False,
        "has_makefile": False,
        "has_ci": False,
        "has_dynamic_require": False,
        "script_used_deps": set(),
        "ci_used_deps": set(),
        "barrel_files": set(),
        "ignored_paths": set(),
    }

    repo = Path(repo)

    if (repo / "Gruntfile.js").exists() or (repo / "Gruntfile.coffee").exists():
        ctx["has_gruntfile"] = True

    if (repo / "gulpfile.js").exists() or (repo / "Gulpfile.js").exists():
        ctx["has_gulpfile"] = True

    if (repo / "Makefile").exists():
        ctx["has_makefile"] = True

    ci_paths = [
        ".travis.yml",
        ".github/workflows",
        "circle.yml",
        ".circleci/config.yml",
        "Jenkinsfile",
        ".gitlab-ci.yml"
    ]

    for ci in ci_paths:
        p = repo / ci
        if p.exists():
            ctx["has_ci"] = True

            try:
                text = p.read_text(errors="ignore") if p.is_file() else ""
                ctx["ci_used_deps"].update(_extract_script_commands(text))
            except Exception:
                pass

            break

    pkg_files = [repo / "package.json"] + list(repo.glob("*/package.json"))

    for pkg in pkg_files:
        try:
            data = json.loads(pkg.read_text())

            for script_val in data.get("scripts", {}).values():
                ctx["script_used_deps"].update(
                    _extract_script_commands(script_val)
                )
        except Exception:
            pass

    dynamic_patterns = [
        r'\brequire\s*\(\s*[^"\']',
        r'\[[\w]+\]\s*\(',
        r'Object\.keys\(',
    ]

    for js_file in list(repo.rglob("*.js"))[:100]:
        try:
            content = js_file.read_text(errors="ignore")

            if any(re.search(p, content) for p in dynamic_patterns):
                ctx["has_dynamic_require"] = True
                break
        except Exception:
            pass

    barrel_re = re.compile(
        r'^\s*export\s*\*\s*from\s*["\']',
        re.MULTILINE
    )

    for idx_file in list(repo.rglob("index.js")) + list(repo.rglob("index.ts")):
        try:
            content = idx_file.read_text(errors="ignore")

            if barrel_re.search(content):
                ctx["barrel_files"].add(str(idx_file.resolve()))
        except Exception:
            pass

    import fnmatch

    for fname in [".gitignore", ".npmignore"]:
        ig = repo / fname

        if not ig.exists():
            continue

        for line in ig.read_text(errors="ignore").splitlines():
            line = line.strip()

            if not line or line.startswith("#"):
                continue

            for f in repo.rglob("*"):
                rel = str(f.relative_to(repo))

                if fnmatch.fnmatch(rel, line) or fnmatch.fnmatch(f.name, line):
                    ctx["ignored_paths"].add(rel)

    return ctx


# ---------------- SCORING ----------------

KNOWN_CLI_ONLY_DEPS = {
    "grunt", "gulp", "webpack", "rollup", "babel",
    "eslint", "prettier", "jest", "mocha",
    "node", "npx", "bash"
}


def score_dep(dep_name, ctx):
    name = dep_name.lower().strip()

    if name in KNOWN_CLI_ONLY_DEPS:
        return False, 0.0, "CLI-only tool"

    if name in ctx["script_used_deps"]:
        return False, 0.0, "referenced in scripts"

    if name in ctx["ci_used_deps"]:
        return True, 0.4, "CI dependency"

    return True, 0.85, "not found in imports"


def score_export(symbol, file_path, ctx):
    if str(Path(file_path).resolve()) in ctx["barrel_files"]:
        return True, 0.2, "public API barrel"

    if ctx["has_dynamic_require"]:
        return True, 0.55, "dynamic require exists"

    return True, 0.8, "unused export"


def score_file(file_path, ctx):
    fp = file_path.lower()

    if _is_test_file(fp):
        return False, 0.0, "test file"

    if file_path in ctx["ignored_paths"]:
        return False, 0.0, "ignored file"

    if ctx["has_dynamic_require"]:
        return True, 0.4, "dynamic require"

    return True, 0.75, "unused file"


# ---------------- FILTERS ----------------

def filter_deps(raw_deps, ctx):
    result = []

    for dep in raw_deps:
        name = dep if isinstance(dep, str) else dep.get("name", "")
        keep, conf, reason = score_dep(name, ctx)

        if keep:
            result.append({
                "name": name,
                "confidence": conf,
                "reason": reason
            })

    return result


def filter_exports(raw_exports, ctx):
    result = []

    for exp in raw_exports:
        keep, conf, reason = score_export(
            exp.get("symbol", ""),
            exp.get("file", ""),
            ctx
        )

        if keep:
            result.append({**exp, "confidence": conf, "reason": reason})

    return result


def filter_files(raw_files, ctx, max_confidence=0.75):
    result = []

    for f in raw_files:
        file_path = f if isinstance(f, str) else f.get("file", "")
        keep, conf, reason = score_file(file_path, ctx)

        if keep:
            result.append({
                "file": file_path,
                "confidence": min(conf, max_confidence),
                "reason": reason
            })

    return result


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
            return {
                "files": [],
                "exports": [],
                "dependencies": []
            }

        data = json.loads(out)

        files = data.get("files", [])
        exports = []

        for issue in data.get("issues", []):
            file_path = issue.get("file", "unknown")

            for exp in issue.get("exports", []):
                exports.append({
                    "file": file_path,
                    "symbol": exp.get("symbol") or exp.get("name", "?"),
                    "type": exp.get("type", "export"),
                    "line": exp.get("line"),
                    "col": exp.get("col"),
                })

        dependencies = (
            data.get("dependencies", []) +
            data.get("devDependencies", [])
        )

        return {
            "files": files,
            "exports": exports,
            "dependencies": dependencies
        }

    except Exception:
        return {
            "files": [],
            "exports": [],
            "dependencies": []
        }


def run_depcheck(repo):
    out, _ = run_cmd("npx --yes depcheck --json", repo)

    if not out:
        return []

    try:
        data = json.loads(out)

        prod = data.get("dependencies", [])
        dev = data.get("devDependencies", [])

        if isinstance(prod, dict):
            prod = list(prod.keys())

        if isinstance(dev, dict):
            dev = list(dev.keys())

        return prod + dev

    except Exception:
        return []


def run_eslint(repo):
    has_existing_config = any(
        (Path(repo) / f).exists()
        for f in [
            ".eslintrc",
            ".eslintrc.js",
            ".eslintrc.json",
            "eslint.config.js"
        ]
    )

    config_path = Path(repo) / ".eslint_dead_scan.json"

    try:
        if has_existing_config:
            cmd = "npx --yes eslint . -f json --ext .js,.mjs,.cjs,.ts,.tsx"
        else:
            eslint_config = json.dumps({
                "env": {"es2021": True, "node": True},
                "rules": {"no-unused-vars": "error"},
                "parserOptions": {
                    "ecmaVersion": 2021,
                    "sourceType": "module"
                }
            })

            config_path.write_text(eslint_config)

            cmd = (
                "npx --yes eslint . -f json "
                "--no-eslintrc -c .eslint_dead_scan.json "
                "--ext .js,.mjs,.cjs"
            )

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
            fpath = file_report.get("filePath", "")

            if _is_test_file(fpath):
                continue

            for msg in file_report.get("messages", []):
                rule = msg.get("ruleId") or ""

                if "unused" in rule:
                    results.append({
                        "file": fpath,
                        "line": msg.get("line"),
                        "message": msg.get("message"),
                        "confidence": 0.9,
                    })
    except Exception:
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


# ---------------- ANALYSIS ----------------

def analyze_application(repo):
    ctx = get_repo_context(repo)
    knip = run_knip(repo)

    return {
        "files": filter_files(knip["files"], ctx, 0.4),
        "unusedExports": filter_exports(knip["exports"], ctx),
        "deps": filter_deps(run_depcheck(repo), ctx),
        "unusedCode": run_eslint(repo),
        "mode": "application-balanced",
    }


def analyze_library(repo):
    ctx = get_repo_context(repo)
    knip = run_knip(repo)

    return {
        "files": filter_files(knip["files"], ctx),
        "unusedExports": filter_exports(knip["exports"], ctx),
        "deps": filter_deps(run_depcheck(repo), ctx),
        "unusedCode": run_eslint(repo),
        "mode": "library-strict",
    }


def analyze_cli(repo):
    ctx = get_repo_context(repo)
    knip = run_knip(repo)

    raw = filter_runtime_files(
        filter_cli_files(repo, knip["files"])
    )

    return {
        "files": filter_files(raw, ctx),
        "unusedExports": filter_exports(knip["exports"], ctx),
        "deps": filter_deps(run_depcheck(repo), ctx),
        "unusedCode": run_eslint(repo),
        "mode": "cli-safe",
    }


def analyze_plugin(repo):
    ctx = get_repo_context(repo)
    knip = run_knip(repo)

    return {
        "files": filter_files(knip["files"], ctx),
        "unusedExports": filter_exports(knip["exports"], ctx),
        "deps": filter_deps(run_depcheck(repo), ctx),
        "unusedCode": run_eslint(repo),
        "mode": "plugin",
    }


def analyze_framework(repo):
    ctx = get_repo_context(repo)

    return {
        "files": [],
        "unusedExports": [],
        "deps": filter_deps(run_depcheck(repo), ctx),
        "unusedCode": run_eslint(repo),
        "mode": "monorepo-safe",
    }


# ---------------- MAIN ----------------

def main():
    if len(sys.argv) < 3:
        print(json.dumps({
            "error": "usage: final_analysis.py <repo> <type>"
        }))
        sys.exit(1)

    repo = sys.argv[1]
    final_type = sys.argv[2]

    if not Path(repo).exists():
        print(json.dumps({
            "error": f"repo path does not exist: {repo}"
        }))
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