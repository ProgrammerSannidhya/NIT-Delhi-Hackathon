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
        "structure": [],
    }

    corpus = []

    pkg = repo / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text())

            signals["name"] = data.get("name", signals["name"]).lower()
            signals["deps"] += len(data.get("dependencies", {}))
            signals["dev_deps"] += len(data.get("devDependencies", {}))
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

    # structure signals (not filenames, categories)
    if (repo / "bin").exists():
        signals["has_bin"] = True

    if (repo / "packages").exists():
        signals["is_monorepo"] = True

    if (repo / "plugins").exists():
        signals["is_plugin"] = True

    # runtime indicators (strong application signal)
    runtime_files = ["dockerfile", "docker-compose.yml", "manage.py"]
    for f in runtime_files:
        if any(str(p).lower().endswith(f) for p in repo.rglob("*")):
            signals["has_runtime_indicators"] = True
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

    scores = {t: 1.0 for t in REPO_TYPES}

    # ---------- strong signals ----------

    if signals["has_bin"]:
        scores["cli"] += 8

    if signals["is_plugin"]:
        scores["plugin"] += 8

    if signals["is_monorepo"]:
        scores["framework"] += 5
        scores["application"] += 2

    if signals["has_runtime_indicators"]:
        scores["application"] += 7

    # dependency shape
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

    # ---------- corpus signals ----------

    if "command line" in corpus or "cli" in corpus:
        scores["cli"] += 3

    if "plugin" in corpus or "extension" in corpus:
        scores["plugin"] += 3

    if "framework" in corpus:
        scores["framework"] += 3

    if "library" in corpus or "package" in corpus:
        scores["library"] += 3

    if "web app" in corpus or "application" in corpus:
        scores["application"] += 3

    # ---------- conflict resolution ----------

    if scores["cli"] > 10:
        scores["library"] *= 0.4

    if scores["plugin"] > 10:
        scores["application"] *= 0.5

    # ---------- normalization ----------

    max_score = max(scores.values())

    exps = {
        k: math.exp(clamp(v - max_score, -50, 50))
        for k, v in scores.items()
    }

    total = sum(exps.values())

    probs = {k: round(safe_div(v, total), 4) for k, v in exps.items()}

    top = max(probs, key=probs.get)

    sorted_probs = sorted(probs.values(), reverse=True)

    confidence = sorted_probs[0]
    separation = sorted_probs[0] - sorted_probs[1] if len(sorted_probs) > 1 else 0

    return {
        "type": top,
        "probabilities": probs,
        "confidence": round(confidence, 4),
        "separation": round(separation, 4),
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
