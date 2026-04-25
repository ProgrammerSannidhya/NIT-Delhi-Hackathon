#!/usr/bin/env python3

import json
import math
import re
import shlex
from pathlib import Path

REPO_TYPES = ["application", "library", "framework", "cli", "plugin"]

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def read_text(path, limit=6000):
    try:
        return Path(path).read_text(encoding="utf-8", errors="ignore")[:limit]
    except:
        return ""

def safe_div(a, b):
    return a / b if b else 0

# ──────────────────────────────────────────────────────────────────
# IMPROVEMENT 4 — precise script command extraction (was: loose
# re.findall on full script string which matched incidental tokens
# like "node", "dist", "js" as if they were package names)
# ──────────────────────────────────────────────────────────────────
def _extract_script_commands(script_val: str) -> set:
    """
    Extract only the actual command names from an npm script string.
    e.g. "tsc && node dist/index.js" → {"tsc", "node"}
    Splits on shell operators, takes the first token of each segment.
    """
    tokens = set()
    try:
        for segment in re.split(r'[&|;]', script_val):
            segment = segment.strip()
            if not segment:
                continue
            parts = shlex.split(segment)
            if parts:
                # basename only — handles "./node_modules/.bin/eslint" → "eslint"
                tokens.add(parts[0].split("/")[-1])
    except Exception:
        # shlex can fail on complex shell syntax — fall back conservatively
        for token in re.findall(r'[\w][\w\-]+', script_val):
            tokens.add(token)
    return tokens


# ──────────────────────────────────────────────────────────────────
# IMPROVEMENT 5 — .gitignore / .npmignore awareness
# Files listed there are intentionally excluded from the package and
# should never be counted as "dead" application code.
# ──────────────────────────────────────────────────────────────────
def _load_ignore_patterns(repo: Path) -> list:
    patterns = []
    for fname in [".gitignore", ".npmignore"]:
        p = repo / fname
        if not p.exists():
            continue
        for line in p.read_text(errors="ignore").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                # convert glob to a simple regex-compatible fragment
                patterns.append(line)
    return patterns

def _is_ignored(path_str: str, ignore_patterns: list) -> bool:
    import fnmatch
    for pat in ignore_patterns:
        if fnmatch.fnmatch(path_str, pat) or fnmatch.fnmatch(Path(path_str).name, pat):
            return True
    return False


# ──────────────────────────────────────────────────────────────────
# IMPROVEMENT 6 — tsconfig.json analysis
# TypeScript projects expose their root files, outDir and path aliases
# which are strong typing signals missed by JS-only scanning.
# ──────────────────────────────────────────────────────────────────
def _parse_tsconfig(repo: Path) -> dict:
    result = {"is_typescript": False, "has_paths": False, "has_out_dir": False,
              "has_composite": False, "include": [], "exclude": []}
    for fname in ["tsconfig.json", "tsconfig.base.json"]:
        p = repo / fname
        if not p.exists():
            continue
        try:
            # Strip JS-style comments before parsing (tsconfig allows them)
            raw = re.sub(r'//[^\n]*', '', p.read_text(errors="ignore"))
            raw = re.sub(r'/\*.*?\*/', '', raw, flags=re.DOTALL)
            data = json.loads(raw)
            co   = data.get("compilerOptions", {})
            result["is_typescript"] = True
            result["has_paths"]     = bool(co.get("paths"))
            result["has_out_dir"]   = bool(co.get("outDir"))
            result["has_composite"] = bool(co.get("composite"))
            result["include"]       = data.get("include", [])
            result["exclude"]       = data.get("exclude", [])
        except Exception:
            result["is_typescript"] = True  # file exists, parsing failed — still TS
        break
    return result


# ──────────────────────────────────────────────────────────────────
# SIGNAL EXTRACTION
# ──────────────────────────────────────────────────────────────────
def extract_signals(repo):
    repo = Path(repo)

    signals = {
        "name":                   repo.name.lower(),
        "has_bin":                False,
        "is_plugin":              False,
        "is_monorepo":            False,
        "has_workspaces":         False,         # IMPROVEMENT 2 — tracked separately
        "deps":                   0,
        "dev_deps":               0,
        "peer_deps":              0,
        "has_runtime_indicators": False,
        "has_frontend":           False,
        "has_backend":            False,
        "has_python":             False,
        "has_docker":             False,
        "pkg_count":              0,
        "structure":              [],
        # new signals
        "has_express":            False,         # IMPROVEMENT 1
        "has_react_vue_next":     False,         # IMPROVEMENT 1
        "has_cli_usage":          False,         # IMPROVEMENT 1
        "is_typescript":          False,         # IMPROVEMENT 6
        "has_ts_paths":           False,         # IMPROVEMENT 6
        "ignore_patterns":        [],            # IMPROVEMENT 5
    }

    corpus = []

    # ── Load ignore patterns early so signal extraction can use them ──────────
    signals["ignore_patterns"] = _load_ignore_patterns(repo)   # IMPROVEMENT 5

    # ── Scan ALL package.json files (root + nested up to depth 3) ─────────────
    pkg_files = (
        [repo / "package.json"]
        + list(repo.glob("*/package.json"))
        + list(repo.glob("*/*/package.json"))
    )
    for pkg in pkg_files:
        if not pkg.exists():
            continue
        try:
            data = json.loads(pkg.read_text())
            signals["pkg_count"] += 1

            if pkg.parent == repo:
                signals["name"] = data.get("name", signals["name"]).lower()

            signals["deps"]      += len(data.get("dependencies", {}))
            signals["dev_deps"]  += len(data.get("devDependencies", {}))
            signals["peer_deps"] += len(data.get("peerDependencies", {}))

            if data.get("bin"):
                signals["has_bin"] = True
            if data.get("peerDependencies"):
                signals["is_plugin"] = True
            if data.get("workspaces"):
                # IMPROVEMENT 2 — separate workspaces flag from is_monorepo
                signals["has_workspaces"] = True
                signals["is_monorepo"]    = True

            corpus.append(data.get("description", ""))
            corpus.extend(data.get("keywords", []))

            # IMPROVEMENT 4 — extract precise script commands only
            for script_val in data.get("scripts", {}).values():
                corpus.append(script_val)   # keep for keyword matching
                # (script_used_deps is built separately in final_analysis)

        except Exception:
            pass

    # ── Folder-structure signals ───────────────────────────────────────────────
    try:
        top_dirs = {d.name.lower() for d in repo.iterdir() if d.is_dir()}
    except Exception:
        top_dirs = set()

    if (repo / "bin").exists():
        signals["has_bin"] = True

    # IMPROVEMENT 2 — monorepo requires packages/ dir OR workspaces field,
    # NOT just multiple package.jsons (fullstack apps have 2 package.jsons
    # but are not monorepos)
    if (repo / "packages").exists() and not signals["is_monorepo"]:
        signals["is_monorepo"] = True

    if (repo / "plugins").exists():
        signals["is_plugin"] = True

    if any(d in top_dirs for d in ["frontend", "client", "web", "ui", "app"]):
        signals["has_frontend"] = True
    if any(d in top_dirs for d in ["backend", "server", "api", "services"]):
        signals["has_backend"] = True

    py_files = list(repo.rglob("*.py"))
    if py_files:
        signals["has_python"] = True

    runtime_files = ["dockerfile", "docker-compose.yml", "manage.py", ".env", ".env.example"]
    for f in runtime_files:
        if any(str(p).lower().endswith(f) for p in repo.rglob("*")):
            signals["has_runtime_indicators"] = True
            if f in ["dockerfile", "docker-compose.yml"]:
                signals["has_docker"] = True
            break

    # IMPROVEMENT 6 — tsconfig analysis
    ts_info = _parse_tsconfig(repo)
    signals["is_typescript"] = ts_info["is_typescript"]
    signals["has_ts_paths"]  = ts_info["has_paths"]
    if ts_info["has_composite"]:
        signals["is_monorepo"] = True  # composite TS = multi-package setup

    # IMPROVEMENT 1 — scan source files for hard import-level signals
    # Limit to 60 files to stay fast; prioritise root-level src/
    js_ts_files = (
        list((repo / "src").rglob("*.ts"))[:20] if (repo / "src").exists() else []
      + list((repo / "src").rglob("*.js"))[:10] if (repo / "src").exists() else []
      + list(repo.rglob("*.ts"))[:20]
      + list(repo.rglob("*.js"))[:20]
    )
    # deduplicate while preserving order
    seen = set()
    unique_files = []
    for f in js_ts_files:
        if f not in seen:
            seen.add(f)
            unique_files.append(f)

    for js in unique_files[:60]:
        try:
            content = js.read_text(errors="ignore")[:3000]
            corpus.append(content)

            if re.search(r'from ["\']express|require\(["\']express', content):
                signals["has_backend"]  = True
                signals["has_express"]  = True
            if re.search(r'from ["\'](?:react|vue|next|nuxt)|require\(["\'](?:react|vue)', content):
                signals["has_frontend"]      = True
                signals["has_react_vue_next"] = True
            if re.search(r'\.command\(|yargs|commander|minimist|meow\.default|cac\(', content):
                signals["has_cli_usage"] = True
                signals["has_bin"]       = True   # CLI library usage is as strong as bin field
            if re.search(r'fastify|koa|hapi|nestjs|@nestjs', content):
                signals["has_backend"] = True
        except Exception:
            pass

    # ── README ────────────────────────────────────────────────────────────────
    for r in ["README.md", "readme.md", "README.rst"]:
        p = repo / r
        if p.exists():
            corpus.append(read_text(p))
            break

    return signals, " ".join(corpus).lower()


# ──────────────────────────────────────────────────────────────────
# CLASSIFICATION
# ──────────────────────────────────────────────────────────────────
def classify(signals, corpus):
    scores = {t: 0.0 for t in REPO_TYPES}

    # ── Strong structural signals ──────────────────────────────────────────────
    if signals["has_bin"] or signals.get("has_cli_usage"):
        scores["cli"] += 8

    if signals["is_plugin"]:
        scores["plugin"] += 8

    # IMPROVEMENT 2 — only real monorepos (workspaces/packages/) get framework boost
    if signals["is_monorepo"] and signals.get("has_workspaces"):
        scores["framework"]    += 5
        scores["application"]  += 2
    elif signals["is_monorepo"]:
        # multi-package without workspaces = likely fullstack app
        scores["application"]  += 3

    if signals["has_runtime_indicators"]:
        scores["application"] += 7

    if signals.get("has_frontend") and signals.get("has_backend"):
        scores["application"] += 10
    elif signals.get("has_frontend"):
        scores["application"] += 5
    elif signals.get("has_backend"):
        scores["application"] += 4

    # IMPROVEMENT 1 — source-level import signals (hard evidence)
    if signals.get("has_express"):
        scores["application"] += 5
        scores["library"]     -= 3
    if signals.get("has_react_vue_next"):
        scores["application"] += 4
    if signals.get("has_cli_usage"):
        scores["cli"]         += 4

    if signals.get("has_python"):
        scores["application"] += 3

    # IMPROVEMENT 2 — multiple package.jsons without workspaces = fullstack app
    if signals.get("pkg_count", 0) > 1 and not signals["is_monorepo"]:
        scores["application"] += 4

    # ── TypeScript signals (IMPROVEMENT 6) ────────────────────────────────────
    if signals.get("is_typescript"):
        # TS + path aliases strongly implies a structured library or framework
        if signals.get("has_ts_paths"):
            scores["library"]   += 2
            scores["framework"] += 1
        # TS itself is neutral — many apps use it too

    # ── Dependency shape ───────────────────────────────────────────────────────
    if signals["peer_deps"] > 0:
        scores["plugin"] += 5

    if signals["deps"] > 20 and signals["dev_deps"] > signals["deps"]:
        scores["framework"] += 3

    if signals["deps"] < 5 and signals["dev_deps"] > signals["deps"]:
        scores["library"] += 3

    # ── Name signals ───────────────────────────────────────────────────────────
    name = signals["name"]

    if "plugin" in name:
        scores["plugin"] += 5
    if name.endswith("-cli") or name.startswith("cli-"):
        scores["cli"] += 5
    if any(x in name for x in ["framework", "runtime", "core"]):
        scores["framework"] += 4
    if any(x in name for x in ["app", "service", "server", "dashboard", "portal", "hackathon"]):
        scores["application"] += 4

    # ── Corpus keyword signals ─────────────────────────────────────────────────
    if "command line" in corpus or " cli " in corpus:
        scores["cli"] += 3
    if "plugin" in corpus or "extension" in corpus:
        scores["plugin"] += 3
    if "framework" in corpus:
        scores["framework"] += 3
    if "library" in corpus or "utility" in corpus:
        scores["library"] += 3
    if "web app" in corpus or "full stack" in corpus or "fullstack" in corpus:
        scores["application"] += 3

    # ── Conflict resolution ────────────────────────────────────────────────────
    if scores["cli"] > 10:
        scores["library"] *= 0.4
    if scores["plugin"] > 10:
        scores["application"] *= 0.5
    if scores["application"] > 8:
        scores["library"] *= 0.3

    # ── Fallback ───────────────────────────────────────────────────────────────
    if max(scores.values()) == 0.0:
        scores["library"]     = 2.0
        scores["application"] = 1.0

    # IMPROVEMENT 3 — lower temperature = confidence honestly reflects score gap
    # (was 2.0 which inflated confidence when scores were close)
    TEMPERATURE = 1.0

    max_score = max(scores.values())
    exps = {
        k: math.exp(clamp((v - max_score) / TEMPERATURE, -50, 50))
        for k, v in scores.items()
    }
    total  = sum(exps.values())
    probs  = {k: round(safe_div(v, total), 4) for k, v in exps.items()}

    top    = max(probs, key=probs.get)
    sorted_probs = sorted(probs.values(), reverse=True)
    confidence   = sorted_probs[0]
    separation   = sorted_probs[0] - sorted_probs[1] if len(sorted_probs) > 1 else 0

    # IMPROVEMENT 3 — added "ambiguous" tier when scores are genuinely close
    if separation < 0.15 and confidence < 0.6:
        tier = "ambiguous"   # caller should prompt for human confirmation
    elif confidence >= 0.75:
        tier = "high"
    elif confidence >= 0.50:
        tier = "medium"
    elif confidence >= 0.35:
        tier = "low"
    else:
        tier = "uncertain"

    return {
        "type":             top,
        "probabilities":    probs,
        "confidence":       round(confidence, 4),
        "separation":       round(separation, 4),
        "confidence_tier":  tier,
        "raw_scores":       {k: round(v, 2) for k, v in scores.items()},
    }


# ──────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────
def main(repo_path):
    repo = Path(repo_path)
    if not repo.exists():
        import json as _json
        print(_json.dumps({"error": "invalid path"}))
        return

    signals, corpus = extract_signals(repo)
    result          = classify(signals, corpus)

    import json as _json
    print(_json.dumps(result, indent=2))

if __name__ == "__main__":
    import sys
    main(sys.argv[1])