#!/usr/bin/env python3

import json
import math
import re
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

# ---------------- SIGNAL EXTRACTION ----------------

def extract_signals(repo):
    signals = {
        "name": repo.name.lower(),
        "has_bin": False,
        "is_plugin": False,
        "is_monorepo": False,
        "deps": 0,
        "dev_deps": 0,
        "peer_deps": 0,
        "has_runtime_indicators": False,
        "has_frontend": False,
        "has_backend": False,
        "has_python": False,
        "has_docker": False,
        "pkg_count": 0,
        "structure": [],
    }

    corpus = []

    # ---- Scan ALL package.json files (root + nested up to depth 3) ----
    # This handles monorepos like AMD Hackathon that have Backend/ and Frontend/ folders
    pkg_files = [repo / "package.json"] + list(repo.glob("*/package.json")) + list(repo.glob("*/*/package.json"))
    for pkg in pkg_files:
        if not pkg.exists():
            continue
        try:
            data = json.loads(pkg.read_text())
            signals["pkg_count"] += 1

            # Use root package.json name preferentially
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
                signals["is_monorepo"] = True

            corpus.append(data.get("description", ""))
            corpus.extend(data.get("keywords", []))
        except:
            pass

    # ---- Folder-structure signals ----
    top_dirs = {d.name.lower() for d in repo.iterdir() if d.is_dir()}

    if (repo / "bin").exists():
        signals["has_bin"] = True
    if (repo / "packages").exists() or signals["pkg_count"] > 1:
        signals["is_monorepo"] = True
    if (repo / "plugins").exists():
        signals["is_plugin"] = True

    # Frontend/Backend split = strong application signal
    if any(d in top_dirs for d in ["frontend", "client", "web", "ui", "app"]):
        signals["has_frontend"] = True
    if any(d in top_dirs for d in ["backend", "server", "api", "services"]):
        signals["has_backend"] = True

    # Python files = likely application (script/service), not a JS library
    py_files = list(repo.rglob("*.py"))
    if py_files:
        signals["has_python"] = True

    # Runtime indicators (strong application signal)
    runtime_files = ["dockerfile", "docker-compose.yml", "manage.py", ".env", ".env.example"]
    for f in runtime_files:
        if any(str(p).lower().endswith(f) for p in repo.rglob("*")):
            signals["has_runtime_indicators"] = True
            if f in ["dockerfile", "docker-compose.yml"]:
                signals["has_docker"] = True
            break

    # README
    for r in ["README.md", "readme.md"]:
        p = repo / r
        if p.exists():
            corpus.append(read_text(p))
            break

    return signals, " ".join(corpus).lower()

# ---------------- CLASSIFICATION ----------------

def classify(signals, corpus):
    # Start at 0 so scores purely reflect evidence weight
    scores = {t: 0.0 for t in REPO_TYPES}

    # ---------- strong structural signals ----------
    if signals["has_bin"]:
        scores["cli"] += 8

    if signals["is_plugin"]:
        scores["plugin"] += 8

    if signals["is_monorepo"]:
        scores["framework"] += 5
        scores["application"] += 2

    if signals["has_runtime_indicators"]:
        scores["application"] += 7

    # Frontend + Backend folders together = fullstack application (very strong)
    if signals.get("has_frontend") and signals.get("has_backend"):
        scores["application"] += 10
    elif signals.get("has_frontend"):
        scores["application"] += 5
    elif signals.get("has_backend"):
        scores["application"] += 4

    # Python files in a JS/TS repo = scripted service, not a library
    if signals.get("has_python"):
        scores["application"] += 3

    # Multiple package.json without workspaces = multi-package app (not a library)
    if signals.get("pkg_count", 0) > 1 and not signals["is_monorepo"]:
        scores["application"] += 4

    # ---------- dependency shape ----------
    if signals["peer_deps"] > 0:
        scores["plugin"] += 5

    if signals["deps"] > 20 and signals["dev_deps"] > signals["deps"]:
        scores["framework"] += 3

    if signals["deps"] < 5 and signals["dev_deps"] > signals["deps"]:
        scores["library"] += 3

    # ---------- name signals ----------
    name = signals["name"]

    if "plugin" in name:
        scores["plugin"] += 5

    if name.endswith("-cli") or name.startswith("cli-"):
        scores["cli"] += 5

    if any(x in name for x in ["framework", "runtime", "core"]):
        scores["framework"] += 4

    if any(x in name for x in ["app", "service", "server", "dashboard", "portal", "hackathon"]):
        scores["application"] += 4

    # ---------- corpus signals ----------
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

    # ---------- conflict resolution ----------
    if scores["cli"] > 10:
        scores["library"] *= 0.4

    if scores["plugin"] > 10:
        scores["application"] *= 0.5

    # Strong application evidence suppresses library (libraries don't have frontends/backends)
    if scores["application"] > 8:
        scores["library"] *= 0.3

    # ---------- fallback: no signals at all → slight lean to library, uncertain ----------
    if max(scores.values()) == 0.0:
        scores["library"] = 2.0
        scores["application"] = 1.0

    # ---------- temperature-scaled softmax ----------
    # Lower temperature = sharper distribution = higher confidence when there's a clear winner
    # Temperature of 2.0 means scores need to differ meaningfully to dominate
    TEMPERATURE = 2.0

    max_score = max(scores.values())
    exps = {
        k: math.exp(clamp((v - max_score) / TEMPERATURE, -50, 50))
        for k, v in scores.items()
    }
    total = sum(exps.values())
    probs = {k: round(safe_div(v, total), 4) for k, v in exps.items()}

    top = max(probs, key=probs.get)
    sorted_probs = sorted(probs.values(), reverse=True)

    confidence = sorted_probs[0]
    separation = sorted_probs[0] - sorted_probs[1] if len(sorted_probs) > 1 else 0

    # ---------- confidence tier ----------
    if confidence >= 0.75:
        tier = "high"
    elif confidence >= 0.50:
        tier = "medium"
    elif confidence >= 0.35:
        tier = "low"
    else:
        tier = "uncertain"

    return {
        "type": top,
        "probabilities": probs,
        "confidence": round(confidence, 4),
        "separation": round(separation, 4),
        "confidence_tier": tier,
        "raw_scores": {k: round(v, 2) for k, v in scores.items()},
    }

# ---------------- MAIN ----------------

def main(repo_path):
    repo = Path(repo_path)

    if not repo.exists():
        print(json.dumps({"error": "invalid path"}))
        return

    signals, corpus = extract_signals(repo)
    result = classify(signals, corpus)

    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    import sys
    main(sys.argv[1])