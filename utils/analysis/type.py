#!/usr/bin/env python3

import json
import math
import re
import sys
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

def extract_signals(repo_path):
    repo = Path(repo_path)
    signals = {
        "name": repo.name.lower(),
        "has_bin": False,
        "is_plugin": False,
        "is_monorepo": False,
        "deps": 0,
        "dev_deps": 0,
        "peer_deps": 0,
        "has_runtime_indicators": False,
        "has_scripts": [],
        "keywords": []
    }

    corpus = []
    pkg = repo / "package.json"
    
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text())
            signals["name"] = data.get("name", signals["name"]).lower()
            
            deps = data.get("dependencies", {})
            dev_deps = data.get("devDependencies", {})
            peer_deps = data.get("peerDependencies", {})
            
            signals["deps"] = len(deps)
            signals["dev_deps"] = len(dev_deps)
            signals["peer_deps"] = len(peer_deps)

            if data.get("bin"):
                signals["has_bin"] = True
            if peer_deps:
                signals["is_plugin"] = True
            if data.get("workspaces"):
                signals["is_monorepo"] = True

            # Check scripts for application indicators
            scripts = data.get("scripts", {})
            signals["has_scripts"] = list(scripts.keys())
            
            signals["keywords"] = data.get("keywords", [])
            corpus.append(data.get("description", ""))
            corpus.extend(signals["keywords"])

            # Specific heavy-weight indicators
            if any(k in deps for k in ["express", "next", "react", "vue", "fastify", "nodemon"]):
                signals["has_runtime_indicators"] = True

        except:
            pass

    # Structure checks
    if (repo / "bin").exists() or (repo / "scripts").exists():
        signals["has_bin"] = True
    if (repo / "packages").exists() and (repo / "lerna.json").exists():
        signals["is_monorepo"] = True
    if (repo / "plugins").exists():
        signals["is_plugin"] = True

    runtime_files = ["dockerfile", "docker-compose.yml", "procfile", ".env.example"]
    for p in repo.glob("*"):
        if p.name.lower() in runtime_files:
            signals["has_runtime_indicators"] = True
            break

    # README
    for r in ["README.md", "readme.md", "README.txt"]:
        p = repo / r
        if p.exists():
            corpus.append(read_text(p))
            break

    return signals, " ".join(corpus).lower()

# ---------------- CLASSIFICATION ----------------

def classify(signals, corpus):
    # Start with 0 to ensure we aren't stuck at 0.2
    scores = {t: 0.5 for t in REPO_TYPES}

    # 1. Strong Technical Signals
    if signals["has_bin"]:
        scores["cli"] += 10
        scores["application"] += 2

    if signals["is_plugin"] or "plugin" in signals["keywords"]:
        scores["plugin"] += 12

    if signals["is_monorepo"]:
        scores["framework"] += 8
        scores["application"] += 3

    if signals["has_runtime_indicators"]:
        scores["application"] += 8

    # 2. Dependency Shape
    if signals["peer_deps"] > 0:
        scores["plugin"] += 5
        scores["library"] += 2

    if signals["deps"] > 15:
        scores["application"] += 4
    elif signals["deps"] > 0:
        scores["library"] += 3

    # 3. Script Analysis
    if any(s in signals["has_scripts"] for s in ["start", "serve", "dev"]):
        scores["application"] += 5
    if "build" in signals["has_scripts"] and scores["library"] > 1:
        scores["library"] += 3

    # 4. Name & Keyword Signals
    name = signals["name"]
    if "cli" in name or name.endswith("-tool"):
        scores["cli"] += 7
    if "framework" in name or "core" in name:
        scores["framework"] += 5
    if "lib" in name or "sdk" in name:
        scores["library"] += 6

    # 5. Corpus Regex Analysis
    if re.search(r"\b(command line|terminal|args|flags)\b", corpus):
        scores["cli"] += 4
    if re.search(r"\b(api|middleware|frontend|backend|app)\b", corpus):
        scores["application"] += 4
    if re.search(r"\b(npm install|import {)\b", corpus):
        scores["library"] += 3

    # 6. Conflict Resolution
    if scores["cli"] > 8: scores["library"] *= 0.5
    if scores["plugin"] > 8: scores["application"] *= 0.5

    # 7. Normalization (Softmax)
    max_score = max(scores.values())
    # Subtracting max helps numerical stability
    exps = {k: math.exp(clamp(v - max_score, -50, 50)) for k, v in scores.items()}
    total = sum(exps.values())
    probs = {k: round(safe_div(v, total), 4) for k, v in exps.items()}

    top_type = max(probs, key=probs.get)
    sorted_probs = sorted(probs.values(), reverse=True)
    
    # If top score is very close to second, confidence is lower
    confidence = sorted_probs[0]
    separation = sorted_probs[0] - sorted_probs[1] if len(sorted_probs) > 1 else 0

    return {
        "type": top_type,
        "probabilities": probs,
        "confidence": confidence,
        "separation": separation
    }

def main(repo_path):
    repo = Path(repo_path)
    if not repo.exists():
        print(json.dumps({"error": "invalid path"}))
        return

    signals, corpus = extract_signals(repo)
    result = classify(signals, corpus)
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    if len(sys.argv) > 1:
        main(sys.argv[1])
    else:
        print(json.dumps({"error": "no path provided"}))