#!/usr/bin/env python3

import json
import subprocess
import sys
import re
from pathlib import Path

# ---------------- UTIL ----------------

def run_cmd(cmd, cwd):
    try:
        res = subprocess.run(
            cmd, shell=True, cwd=cwd,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=120
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
            _, code = run_cmd("npm install --ignore-scripts --prefer-offline --silent", cwd)
            if code != 0:
                run_cmd("npm install --ignore-scripts --silent", cwd)
            installed = True
    if installed:
        sys.stderr.write("[INFO] npm install done\n")

# ---------------- FALSE-POSITIVE CONTEXT ----------------

def get_repo_context(repo):
    ctx = {
        "has_gruntfile":       False,
        "has_gulpfile":        False,
        "has_makefile":        False,
        "has_ci":              False,
        "has_dynamic_require": False,
        "script_used_deps":    set(),
        "ci_used_deps":        set(),
    }
    repo = Path(repo)

    if (repo / "Gruntfile.js").exists() or (repo / "Gruntfile.coffee").exists():
        ctx["has_gruntfile"] = True
    if (repo / "gulpfile.js").exists() or (repo / "Gulpfile.js").exists():
        ctx["has_gulpfile"] = True
    if (repo / "Makefile").exists():
        ctx["has_makefile"] = True

    ci_paths = [".travis.yml", ".github/workflows", "circle.yml",
                ".circleci/config.yml", "Jenkinsfile", ".gitlab-ci.yml"]
    for ci in ci_paths:
        if (repo / ci).exists():
            ctx["has_ci"] = True
            try:
                text = (repo / ci).read_text(errors="ignore") if (repo / ci).is_file() else ""
                ctx["ci_used_deps"].update(re.findall(r'[\w][\w\-\.]+', text))
            except:
                pass
            break

    pkg_files = [repo / "package.json"] + list(repo.glob("*/package.json"))
    for pkg in pkg_files:
        if not pkg.exists():
            continue
        try:
            data = json.loads(pkg.read_text())
            for script_val in data.get("scripts", {}).values():
                ctx["script_used_deps"].update(re.findall(r'[\w][\w\-\.]+', script_val))
        except:
            pass

    dynamic_patterns = [
        r'\brequire\s*\(\s*[^"\']',
        r'\[[\w]+\]\s*\(',
        r'_\.\w+\s*\[',
        r'Object\.keys\(',
    ]
    for js_file in list(repo.rglob("*.js"))[:100]:
        try:
            content = js_file.read_text(errors="ignore")
            if any(re.search(p, content) for p in dynamic_patterns):
                ctx["has_dynamic_require"] = True
                break
        except:
            pass

    return ctx

# ---------------- CONFIDENCE SCORING ----------------

KNOWN_CLI_ONLY_DEPS = {
    "grunt", "gulp", "webpack", "rollup", "babel", "tsc", "typescript",
    "eslint", "prettier", "jest", "mocha", "jasmine", "karma", "istanbul",
    "nyc", "coveralls", "codecov", "codecov.io", "sauce-tunnel", "sauce-connect",
    "serve", "concurrently", "nodemon", "ts-node", "cross-env", "rimraf",
    "mkdirp", "copyfiles", "npm-run-all", "husky", "lint-staged",
    "standard", "xo", "ava", "tap", "nsp", "snyk", "ecstatic", "http-server",
}

KNOWN_DYNAMIC_FILE_PATTERNS = [
    r"middleware", r"plugin", r"route", r"handler", r"controller",
    r"hook", r"interceptor", r"resolver", r"migration", r"seed",
    r"fixture", r"config", r"\.d\.ts$", r"index\.(js|ts)$",
]

KNOWN_DYNAMIC_EXPORT_PATTERNS = [
    r"^_", r"Mapping$", r"Map$", r"Config$", r"Options$",
    r"Default", r"^alias", r"ToReal$", r"ToAlias$",
]

def score_dep(dep_name, ctx):
    name = dep_name.lower().strip()
    if name in KNOWN_CLI_ONLY_DEPS:
        return False, 0.0, "CLI-only tool, not require()'d"
    if name in ctx["script_used_deps"] or name.replace("-", "") in ctx["script_used_deps"]:
        return False, 0.0, "referenced in npm scripts"
    if name in ctx["ci_used_deps"]:
        return True, 0.4, "may be CI-only dependency"
    if name.startswith("grunt-") and ctx["has_gruntfile"]:
        return False, 0.0, "grunt plugin, loaded by Gruntfile"
    if name.startswith("gulp-") and ctx["has_gulpfile"]:
        return False, 0.0, "gulp plugin, loaded by Gulpfile"
    if name.startswith("@types/"):
        return True, 0.5, "TypeScript type package, may be indirect"
    return True, 0.85, "not found in import graph"

def score_export(symbol, file_path, ctx):
    if ctx["has_dynamic_require"]:
        for pat in KNOWN_DYNAMIC_EXPORT_PATTERNS:
            if re.search(pat, symbol, re.IGNORECASE):
                return True, 0.3, "may be consumed via dynamic lookup"
        return True, 0.55, "dynamic require patterns detected in repo"
    for pat in KNOWN_DYNAMIC_EXPORT_PATTERNS:
        if re.search(pat, symbol, re.IGNORECASE):
            return True, 0.35, "naming pattern suggests dynamic access"
    return True, 0.8, "not found in static import graph"

def score_file(file_path, ctx):
    fp = file_path.lower()
    for pat in KNOWN_DYNAMIC_FILE_PATTERNS:
        if re.search(pat, fp):
            return True, 0.3, "path pattern suggests dynamic loading"
    if ctx["has_dynamic_require"]:
        return True, 0.4, "dynamic require patterns detected"
    return True, 0.75, "not statically imported"

# ---------------- FILTERING ----------------

def filter_deps(raw_deps, ctx):
    result = []
    for dep in raw_deps:
        name = dep if isinstance(dep, str) else dep.get("name", "")
        keep, conf, reason = score_dep(name, ctx)
        if keep and conf > 0:
            result.append({"name": name, "confidence": conf, "reason": reason})
    return result

def filter_exports(raw_exports, ctx):
    result = []
    for exp in raw_exports:
        symbol    = exp.get("symbol", "")
        file_path = exp.get("file", "")
        keep, conf, reason = score_export(symbol, file_path, ctx)
        if keep:
            result.append({**exp, "confidence": conf, "reason": reason})
    return result

def filter_files(raw_files, ctx, max_confidence=0.75):
    result = []
    for f in raw_files:
        file_path = f if isinstance(f, str) else f.get("file", "")
        keep, conf, reason = score_file(file_path, ctx)
        if keep:
            result.append({"file": file_path, "confidence": min(conf, max_confidence), "reason": reason})
    return result

# ---------------- TOOLS ----------------

def run_knip(repo):
    install_deps(repo)
    out, code = run_cmd("npx --yes knip --reporter json 2>/dev/null", repo)
    if not out:
        sys.stderr.write(f"[WARN] knip returned no output (exit {code})\n")
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
            exports.append({"file": file_path, "symbol": symbol,
                            "type": exp.get("type", "export"),
                            "line": exp.get("line"), "col": exp.get("col")})
        for t in issue.get("types", []):
            symbol = t.get("symbol") or t.get("name", "?")
            exports.append({"file": file_path, "symbol": symbol, "type": "type",
                            "line": t.get("line"), "col": t.get("col")})
        for ns in issue.get("nsExports", []):
            symbol = ns.get("symbol") or ns.get("name", "?")
            exports.append({"file": file_path, "symbol": symbol, "type": "nsExport",
                            "line": ns.get("line"), "col": ns.get("col")})

    dependencies = data.get("dependencies", []) + data.get("devDependencies", [])
    return {"files": files, "exports": exports, "dependencies": dependencies}


def run_depcheck(repo):
    out, code = run_cmd("npx --yes depcheck --json", repo)
    if not out:
        sys.stderr.write(f"[WARN] depcheck returned no output (exit {code})\n")
        return []
    try:
        data = json.loads(out)
        prod_deps = data.get("dependencies", [])
        dev_deps  = data.get("devDependencies", [])
        if isinstance(prod_deps, dict): prod_deps = list(prod_deps.keys())
        if isinstance(dev_deps, dict):  dev_deps  = list(dev_deps.keys())
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
        cmd = 'npx --yes eslint . -f json --no-eslintrc -c .eslint_dead_scan.json --ext .js,.mjs,.cjs 2>/dev/null'
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
            for msg in file_report.get("messages", []):
                rule = msg.get("ruleId") or ""
                if "unused" in rule:
                    results.append({"file": fpath, "line": msg.get("line"),
                                    "message": msg.get("message"), "confidence": 0.9})
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
    if isinstance(bin_field, dict): entries.extend(bin_field.values())
    elif isinstance(bin_field, str): entries.append(bin_field)
    return [str((Path(repo) / e).resolve()) for e in entries if (Path(repo) / e).exists()]

def filter_cli_files(repo, files):
    entries = get_cli_entries(repo)
    return [f for f in files if str((Path(repo) / f).resolve()) not in entries]

def filter_runtime_files(files):
    ignore = ["bin/", "cli", "commands", "scripts", "middleware"]
    return [f for f in files if not any(x in f.lower() for x in ignore)]

# ---------------- TYPE ANALYSIS ----------------

def analyze_application(repo):
    ctx    = get_repo_context(repo)
    knip   = run_knip(repo)
    eslint = run_eslint(repo)
    deps   = run_depcheck(repo)
    return {
        "files":         filter_files(knip["files"], ctx, max_confidence=0.4),
        "unusedExports": filter_exports(knip["exports"], ctx),
        "deps":          filter_deps(deps, ctx),
        "unusedCode":    eslint,
        "mode":          "application-balanced",
    }

def analyze_library(repo):
    ctx  = get_repo_context(repo)
    knip = run_knip(repo)
    return {
        "files":         filter_files(knip["files"], ctx),
        "unusedExports": filter_exports(knip["exports"], ctx),
        "deps":          filter_deps(run_depcheck(repo), ctx),
        "unusedCode":    run_eslint(repo),
        "mode":          "library-strict",
    }

def analyze_cli(repo):
    ctx   = get_repo_context(repo)
    knip  = run_knip(repo)
    raw   = filter_runtime_files(filter_cli_files(repo, knip["files"]))
    return {
        "files":         filter_files(raw, ctx),
        "unusedExports": filter_exports(knip["exports"], ctx),
        "deps":          filter_deps(run_depcheck(repo), ctx),
        "unusedCode":    run_eslint(repo),
        "mode":          "cli-safe",
    }

def analyze_plugin(repo):
    ctx  = get_repo_context(repo)
    knip = run_knip(repo)
    return {
        "files":         filter_files(knip["files"], ctx),
        "unusedExports": filter_exports(knip["exports"], ctx),
        "deps":          filter_deps(run_depcheck(repo), ctx),
        "unusedCode":    run_eslint(repo),
        "mode":          "plugin",
    }

def analyze_framework(repo):
    ctx = get_repo_context(repo)
    return {
        "files":         [],
        "unusedExports": [],
        "deps":          filter_deps(run_depcheck(repo), ctx),
        "unusedCode":    run_eslint(repo),
        "mode":          "monorepo-safe",
    }

# ---------------- MAIN ----------------

def main():
    if len(sys.argv) < 3:
        print(json.dumps({"error": "usage: final_analysis.py <repo> <type>"}))
        sys.exit(1)

    repo       = sys.argv[1]
    final_type = sys.argv[2]

    if not Path(repo).exists():
        print(json.dumps({"error": f"repo path does not exist: {repo}"}))
        sys.exit(1)

    dispatch = {
        "application": analyze_application,
        "library":     analyze_library,
        "cli":         analyze_cli,
        "plugin":      analyze_plugin,
        "framework":   analyze_framework,
    }

    analyze_fn = dispatch.get(final_type, analyze_application)
    result     = analyze_fn(repo)
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()