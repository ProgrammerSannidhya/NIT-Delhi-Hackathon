#!/usr/bin/env python3
"""
Static analysis and repository classification tool.

This script:
1. Classifies a repository as application, library, framework, cli, or plugin.
2. Runs knip and depcheck when available.
3. Aggregates unused files, exports, and dependencies into a single JSON result.
"""

import json
import math
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


def clamp(value, lower, upper):
    return max(lower, min(upper, value))


def normalize(path_value):
    return (path_value or "").replace("\\", "/").strip()


def safe_divide(numerator, denominator, default=0.0):
    try:
        if denominator == 0:
            return default
        return float(numerator) / float(denominator)
    except (TypeError, ValueError):
        return default


def sigmoid(value):
    try:
        return 1.0 / (1.0 + math.exp(-clamp(value, -100, 100)))
    except Exception:
        return 0.5


def run_cmd(command, cwd=None, timeout=120):
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        return completed.stdout.strip(), completed.stderr.strip(), completed.returncode
    except subprocess.TimeoutExpired:
        return "", "TIMEOUT", -1
    except Exception as exc:
        return "", str(exc), -1


def read_text_safely(file_path, limit=None):
    try:
        text = Path(file_path).read_text(encoding="utf-8", errors="ignore")
        return text[:limit] if limit else text
    except Exception:
        return ""


REPO_TYPES = ["application", "library", "framework", "cli", "plugin"]

COMPOSER_TYPE_MAP = {
    "project": "application",
    "library": "library",
    "composer-plugin": "plugin",
    "wordpress-plugin": "plugin",
    "wordpress-muplugin": "plugin",
    "drupal-module": "plugin",
    "symfony-bundle": "plugin",
    "laravel-package": "plugin",
    "cakephp-plugin": "plugin",
    "magento2-module": "plugin",
}

FILE_STRUCTURE_SIGNALS = [
    ("Dockerfile", False, 9.0, "application"),
    ("docker-compose.yml", False, 9.0, "application"),
    ("docker-compose.yaml", False, 9.0, "application"),
    ("manage.py", False, 8.0, "application"),
    ("wsgi.py", False, 6.0, "application"),
    (".env.example", False, 4.0, "application"),
    ("artisan", False, 8.0, "application"),
    ("next.config.js", False, 7.0, "application"),
    ("next.config.mjs", False, 7.0, "application"),
    ("nuxt.config.ts", False, 7.0, "application"),
    ("nuxt.config.js", False, 7.0, "application"),
    ("prisma", True, 6.0, "application"),
    ("config/routes.rb", False, 6.0, "application"),
    ("public/index.php", False, 6.0, "application"),
    ("packages", True, 7.0, "framework"),
    ("workspaces", True, 7.0, "framework"),
    ("crates", True, 6.0, "framework"),
    ("nx.json", False, 6.0, "framework"),
    ("turbo.json", False, 5.0, "framework"),
    ("bin", True, 8.0, "cli"),
    ("cmd", True, 8.0, "cli"),
    ("src/bin", True, 7.0, "cli"),
    ("main.go", False, 6.0, "cli"),
    ("src/index.ts", False, 5.0, "library"),
    ("src/index.tsx", False, 5.0, "library"),
    ("src/index.js", False, 5.0, "library"),
    ("src/index.jsx", False, 5.0, "library"),
    ("src/lib.rs", False, 6.0, "library"),
    ("lib", True, 3.0, "library"),
    ("include", True, 4.0, "library"),
    ("plugins", True, 6.0, "plugin"),
    ("plugin", True, 6.0, "plugin"),
    ("extensions", True, 6.0, "plugin"),
    ("extension", True, 6.0, "plugin"),
    ("middleware", True, 4.0, "plugin"),
    ("presets", True, 5.0, "plugin"),
]

PLUGIN_NAME_PREFIXES = [
    "babel-plugin-",
    "commitlint-config-",
    "eslint-config-",
    "eslint-plugin-",
    "gatsby-plugin-",
    "parcel-config-",
    "parcel-namer-",
    "parcel-optimizer-",
    "parcel-packager-",
    "parcel-reporter-",
    "parcel-resolver-",
    "parcel-runtime-",
    "parcel-transformer-",
    "postcss-",
    "prettier-plugin-",
    "remark-",
    "rehype-",
    "rollup-plugin-",
    "semantic-release-",
    "stylelint-config-",
    "stylelint-",
    "unplugin-",
    "vite-plugin-",
    "webpack-plugin-",
]

CLI_NAME_PREFIXES = [
    "cli-",
    "cmd-",
    "command-",
    "exec-",
    "run-",
    "tool-",
]

CLI_NAME_SUFFIXES = [
    "-cli",
    "-cmd",
    "-bin",
    "-command",
    "-run",
    "-tool",
    "-exec",
]

FRAMEWORK_NAME_SIGNALS = [
    "framework",
    "runtime",
    "boilerplate",
    "starter",
    "sveltekit",
    "fastify",
    "nuxt",
    "next",
    "remix",
    "angular",
    "ember",
    "backbone",
    "koa",
    "nest",
]

CORPUS_SCORE_WEIGHTS = {"strong": 4.0, "weak": 1.5}
CORPUS_MAX_OCCURRENCES = 3
CORPUS_NAME_BONUS = 8.0

CORPUS_KW_MAP = {
    "application": {
        "strong": [
            "admin dashboard",
            "content management",
            "customer portal",
            "multi-tenant",
            "self-hosted",
            "web application",
        ],
        "weak": [
            "dashboard",
            "platform",
            "saas",
            "workspace",
            "fullstack",
            "back office",
        ],
    },
    "library": {
        "strong": [
            "client library",
            "helper library",
            "software library",
            "utility library",
            "package for",
            "programming library",
        ],
        "weak": [
            "library",
            "module",
            "package",
            "toolkit",
            "utilities",
            "utility",
        ],
    },
    "framework": {
        "strong": [
            "application framework",
            "framework core",
            "meta-framework",
            "plugin system",
            "runtime core",
            "scaffolding framework",
        ],
        "weak": [
            "convention",
            "framework",
            "opinionated",
            "runtime",
            "starter kit",
            "starter",
        ],
    },
    "cli": {
        "strong": [
            "build tool",
            "command line",
            "command-line",
            "developer tool",
            "shell utility",
            "terminal application",
            "npx ",
        ],
        "weak": [
            "cli",
            "console app",
            "daemon",
            "repl",
            "subcommand",
            "terminal",
        ],
    },
    "plugin": {
        "strong": [
            "adapter for",
            "build plugin",
            "compiler plugin",
            "extension for",
            "integration for",
            "plugin for",
            "theme plugin",
        ],
        "weak": [
            "adapter",
            "extension",
            "loader",
            "middleware",
            "plugin",
            "preset",
            "transformer",
        ],
    },
}


def count_occurrences(text, token, cap=CORPUS_MAX_OCCURRENCES):
    return min(text.count(token), cap)


def extract_multilingual_metadata(repo_path):
    """Safely parse manifests across JS, Python, Rust, PHP, Java, Ruby, and Go."""
    signals = {
        "name": repo_path.name.lower(),
        "is_private": False,
        "has_bin": False,
        "is_plugin": False,
        "deps_count": 0,
        "dev_deps_count": 0,
        "is_monorepo": False,
        "app_files_count": 0,
        "explicit_type": None,
        "structure_hits": [],
    }
    corpus_parts = []

    try:
        for relative_path, is_dir, boost, category in FILE_STRUCTURE_SIGNALS:
            full_path = repo_path / relative_path
            exists = full_path.is_dir() if is_dir else full_path.exists()
            if not exists:
                continue

            signals["structure_hits"].append(
                {"path": relative_path, "category": category, "boost": boost}
            )

            if category == "application":
                signals["app_files_count"] += 1
            if relative_path in {"packages", "workspaces", "crates"}:
                signals["is_monorepo"] = True
            if relative_path in {"bin", "cmd", "src/bin"}:
                signals["has_bin"] = True

        pkg_path = repo_path / "package.json"
        if pkg_path.exists():
            try:
                with pkg_path.open("r", encoding="utf-8", errors="ignore") as handle:
                    pkg = json.load(handle)

                signals["name"] = str(pkg.get("name", signals["name"])).lower()
                signals["is_private"] = bool(pkg.get("private", False))
                signals["deps_count"] += len(pkg.get("dependencies", {}) or {})
                signals["dev_deps_count"] += len(pkg.get("devDependencies", {}) or {})

                if pkg.get("bin"):
                    signals["has_bin"] = True
                if pkg.get("peerDependencies"):
                    signals["is_plugin"] = True
                if pkg.get("workspaces"):
                    signals["is_monorepo"] = True

                corpus_parts.append(str(pkg.get("description", "")))
                keywords = pkg.get("keywords", [])
                if isinstance(keywords, list):
                    corpus_parts.append(" ".join(str(keyword) for keyword in keywords if keyword))
            except Exception:
                pass

        comp_path = repo_path / "composer.json"
        if comp_path.exists():
            try:
                with comp_path.open("r", encoding="utf-8", errors="ignore") as handle:
                    composer = json.load(handle)

                signals["name"] = str(composer.get("name", signals["name"])).lower()
                signals["deps_count"] += len(composer.get("require", {}) or {})
                signals["dev_deps_count"] += len(composer.get("require-dev", {}) or {})

                if composer.get("bin"):
                    signals["has_bin"] = True

                composer_type = str(composer.get("type", "")).lower()
                for type_key, explicit_type in COMPOSER_TYPE_MAP.items():
                    if type_key in composer_type:
                        signals["explicit_type"] = explicit_type
                        break

                corpus_parts.append(str(composer.get("description", "")))
            except Exception:
                pass

        for toml_file in ["Cargo.toml", "pyproject.toml"]:
            toml_path = repo_path / toml_file
            if not toml_path.exists():
                continue

            text = read_text_safely(toml_path, limit=4000)
            lowered = text.lower()
            if not lowered:
                continue

            corpus_parts.append(lowered)

            name_match = re.search(r'name\s*=\s*["\']([^"\']+)["\']', lowered)
            if name_match:
                signals["name"] = name_match.group(1)

            if any(
                marker in lowered
                for marker in ("[[bin]]", "[project.scripts]", "[tool.poetry.scripts]", "console_scripts")
            ):
                signals["has_bin"] = True

        go_mod_path = repo_path / "go.mod"
        if go_mod_path.exists():
            lowered = read_text_safely(go_mod_path, limit=3000).lower()
            corpus_parts.append(lowered)
            module_match = re.search(r"module\s+([^\s]+)", lowered)
            if module_match:
                signals["name"] = module_match.group(1).split("/")[-1]

        gemfile_path = repo_path / "Gemfile"
        if gemfile_path.exists():
            corpus_parts.append(read_text_safely(gemfile_path, limit=3000).lower())

        gemspec_files = list(repo_path.glob("*.gemspec"))
        if gemspec_files:
            gemspec_text = read_text_safely(gemspec_files[0], limit=4000)
            lowered = gemspec_text.lower()
            corpus_parts.append(lowered)

            name_match = re.search(r"\.name\s*=\s*['\"]([^'\"]+)['\"]", gemspec_text)
            if name_match:
                signals["name"] = name_match.group(1).lower()

            if "executables" in lowered or ".bindir" in lowered:
                signals["has_bin"] = True

        for java_file in ["pom.xml", "build.gradle", "build.gradle.kts"]:
            java_path = repo_path / java_file
            if not java_path.exists():
                continue

            lowered = read_text_safely(java_path, limit=4000).lower()
            corpus_parts.append(lowered)

            if "<packaging>war</packaging>" in lowered or "spring-boot" in lowered:
                signals["explicit_type"] = "application"
            elif "maven-plugin" in lowered:
                signals["explicit_type"] = "plugin"

        for readme_name in ["README.md", "readme.md", "README.MD"]:
            readme_path = repo_path / readme_name
            if readme_path.exists():
                corpus_parts.append(read_text_safely(readme_path, limit=6000).lower())
                break
    except Exception:
        pass

    return signals, " ".join(part for part in corpus_parts if part)


def compute_classification(signals, corpus):
    scores = {repo_type: 0.1 for repo_type in REPO_TYPES}
    name = str(signals.get("name", "") or "").lower()
    corpus_lower = (corpus or "").lower()
    structure_hits = signals.get("structure_hits", [])

    if signals.get("explicit_type") in scores:
        scores[signals["explicit_type"]] += 15.0

    if signals.get("is_private"):
        scores["application"] += 8.0

    if signals.get("has_bin"):
        scores["cli"] += 6.0
        scores["application"] += 2.0

    if signals.get("is_plugin"):
        scores["plugin"] += 10.0

    if signals.get("is_monorepo"):
        scores["framework"] += 8.0
        scores["application"] += 2.0

    for hit in structure_hits:
        category = hit.get("category")
        boost = float(hit.get("boost", 0.0) or 0.0)
        if category in scores:
            scores[category] += boost

    if (
        not structure_hits
        and not signals.get("has_bin")
        and not signals.get("is_plugin")
        and not signals.get("is_monorepo")
        and not signals.get("explicit_type")
    ):
        scores["library"] += 5.0

    if any(name.startswith(prefix) for prefix in PLUGIN_NAME_PREFIXES):
        scores["plugin"] += 15.0
        scores["cli"] *= 0.2

    if "plugin" in name or name.endswith(("-loader", "-preset", "-adapter", "-extension")):
        scores["plugin"] += 12.0

    if any(name.startswith(prefix) for prefix in CLI_NAME_PREFIXES) or any(
        name.endswith(suffix) for suffix in CLI_NAME_SUFFIXES
    ):
        scores["cli"] += 15.0

    if any(signal in name for signal in FRAMEWORK_NAME_SIGNALS):
        scores["framework"] += 10.0

    for category, tier_map in CORPUS_KW_MAP.items():
        for tier, words in tier_map.items():
            weight = CORPUS_SCORE_WEIGHTS.get(tier, 1.0)
            for word in words:
                hit_count = count_occurrences(corpus_lower, word)
                if hit_count > 0:
                    scores[category] += hit_count * weight
                if word in name:
                    scores[category] += CORPUS_NAME_BONUS

    max_score = max(scores.values())
    exps = {
        repo_type: math.exp(clamp(score - max_score, -100, 100))
        for repo_type, score in scores.items()
    }
    total = sum(exps.values())
    probabilities = {
        repo_type: round(safe_divide(exps[repo_type], total, default=0.2), 4)
        for repo_type in REPO_TYPES
    }

    entropy = -sum(prob * math.log(prob) for prob in probabilities.values() if prob > 0)
    sorted_probs = sorted(probabilities.values(), reverse=True)
    separation = sorted_probs[0] - sorted_probs[1] if len(sorted_probs) > 1 else 0.0
    top_class = max(probabilities, key=probabilities.get)

    return {
        "type": top_class,
        "probabilities": probabilities,
        "confidence": round(sorted_probs[0], 4),
        "entropy": round(entropy, 4),
        "separation": round(separation, 4),
    }


def expected_repo_modifier(repo_probs, item_type):
    modifiers = {
        "library": {"unusedExport": 0.3, "unusedFile": 0.8, "unusedDependency": 1.0},
        "application": {"unusedExport": 0.8, "unusedFile": 1.0, "unusedDependency": 1.0},
        "framework": {"unusedExport": 0.5, "unusedFile": 0.6, "unusedDependency": 0.9},
        "cli": {"unusedExport": 0.6, "unusedFile": 0.9, "unusedDependency": 1.0},
        "plugin": {"unusedExport": 0.4, "unusedFile": 0.7, "unusedDependency": 0.9},
    }
    return sum(
        repo_probs.get(repo_type, 0.2)
        * modifiers.get(repo_type, modifiers["library"]).get(item_type, 1.0)
        for repo_type in REPO_TYPES
    )


class AnalysisState:
    FAILED = "failed"
    PARTIAL = "partial"
    SUCCESS = "success"

    def __init__(self):
        self.state = self.FAILED
        self.signal_categories = set()
        self.notes = []

    def add_signal_category(self, category):
        self.signal_categories.add(category)

    def finalize(self):
        if not self.signal_categories:
            self.state = self.FAILED
        elif len(self.signal_categories) >= 3:
            self.state = self.SUCCESS
        else:
            self.state = self.PARTIAL

    def get_confidence_multiplier(self):
        if self.state == self.FAILED:
            return 0.0
        if self.state == self.PARTIAL:
            return 0.6
        return 1.0

    def get_reliability_multiplier(self):
        if self.state == self.FAILED:
            return 0.0
        if self.state == self.PARTIAL:
            return 0.7
        return 1.0


def is_test_path(path_value):
    normalized = normalize(path_value).lower()
    if not normalized:
        return False

    test_tokens = {
        "__test__",
        "__tests__",
        "cypress",
        "fixture",
        "fixtures",
        "playwright",
        "spec",
        "specs",
        "test",
        "testing",
        "tests",
    }
    parts = [part for part in normalized.split("/") if part]
    return any(part in test_tokens for part in parts) or ".test." in normalized or ".spec." in normalized


class MultiToolAnalyzer:
    def __init__(self, repo_path):
        self.repo_path = repo_path
        self.tools_run = []
        self.tools_success = []

    def run_all(self):
        results = {}

        package_json_path = os.path.join(self.repo_path, "package.json")
        node_modules_path = os.path.join(self.repo_path, "node_modules")
        if os.path.exists(package_json_path) and not os.path.exists(node_modules_path):
            run_cmd("npm install --ignore-scripts --prefer-offline", cwd=self.repo_path, timeout=120)

        knip_raw, _, knip_code = run_cmd("npx knip --reporter json", cwd=self.repo_path, timeout=180)
        self.tools_run.append("knip")
        if knip_raw and knip_code == 0:
            try:
                results["knip"] = json.loads(knip_raw)
                self.tools_success.append("knip")
            except Exception:
                pass

        depcheck_raw, _, depcheck_code = run_cmd("npx depcheck --json", cwd=self.repo_path, timeout=90)
        self.tools_run.append("depcheck")
        if depcheck_raw and depcheck_code == 0:
            try:
                results["depcheck"] = json.loads(depcheck_raw)
                self.tools_success.append("depcheck")
            except Exception:
                pass

        return results


class EvidenceAggregator:
    def __init__(self, tools_results, repo_path):
        self.tools_results = tools_results
        self.repo_path = repo_path

    def _record_file(self, store, file_value, source):
        normalized = normalize(file_value)
        if normalized and not is_test_path(normalized):
            store[normalized].add(source)

    def _record_export(self, store, file_value, export_name, source):
        normalized = normalize(file_value)
        export_name = (export_name or "").strip()
        if normalized and export_name and not is_test_path(normalized):
            store[(normalized, export_name)].add(source)

    def _record_dependency(self, store, dep_name, source):
        dep_name = (dep_name or "").strip()
        if dep_name:
            store[dep_name].add(source)

    def _parse_knip(self, payload, unused_files, unused_symbols, unused_deps):
        if not isinstance(payload, dict):
            return

        issues = payload.get("issues", [])
        if isinstance(issues, list):
            for issue in issues:
                if not isinstance(issue, dict):
                    continue

                issue_type = issue.get("type")
                issue_file = issue.get("file") or issue.get("path")

                if issue_type == "unused-file":
                    self._record_file(unused_files, issue_file, "knip")

                for export_info in issue.get("exports", []) or []:
                    if isinstance(export_info, dict):
                        self._record_export(
                            unused_symbols,
                            issue_file or export_info.get("file") or export_info.get("path"),
                            export_info.get("name"),
                            "knip",
                        )
                    elif isinstance(export_info, str):
                        self._record_export(unused_symbols, issue_file, export_info, "knip")

                for dep_info in (issue.get("dependencies", []) or []) + (issue.get("devDependencies", []) or []):
                    if isinstance(dep_info, dict):
                        self._record_dependency(unused_deps, dep_info.get("name"), "knip")
                    elif isinstance(dep_info, str):
                        self._record_dependency(unused_deps, dep_info, "knip")

        for file_entry in payload.get("files", []) or []:
            if isinstance(file_entry, dict):
                self._record_file(unused_files, file_entry.get("file") or file_entry.get("path"), "knip")
            elif isinstance(file_entry, str):
                self._record_file(unused_files, file_entry, "knip")

        for export_entry in payload.get("exports", []) or []:
            if not isinstance(export_entry, dict):
                continue
            self._record_export(
                unused_symbols,
                export_entry.get("file") or export_entry.get("path"),
                export_entry.get("name"),
                "knip",
            )

        for dep_key in ("dependencies", "devDependencies"):
            for dep_entry in payload.get(dep_key, []) or []:
                if isinstance(dep_entry, dict):
                    self._record_dependency(unused_deps, dep_entry.get("name"), "knip")
                elif isinstance(dep_entry, str):
                    self._record_dependency(unused_deps, dep_entry, "knip")

    def aggregate(self):
        unused_files = defaultdict(set)
        unused_symbols = defaultdict(set)
        unused_deps = defaultdict(set)

        knip_payload = self.tools_results.get("knip")
        if knip_payload is not None:
            self._parse_knip(knip_payload, unused_files, unused_symbols, unused_deps)

        depcheck_payload = self.tools_results.get("depcheck", {})
        if isinstance(depcheck_payload, dict):
            for dep_name in depcheck_payload.get("dependencies", []) or []:
                self._record_dependency(unused_deps, dep_name, "depcheck")
            for dep_name in depcheck_payload.get("devDependencies", []) or []:
                self._record_dependency(unused_deps, dep_name, "depcheck")

        return unused_files, unused_symbols, unused_deps


def scan_repo(repo_path):
    repo_root = Path(repo_path)
    if not repo_root.exists():
        return {"error": "Repository path not found"}

    signals, corpus = extract_multilingual_metadata(repo_root)
    repo_type = compute_classification(signals, corpus)
    repo_probs = repo_type["probabilities"]

    analysis_state = AnalysisState()
    analyzer = MultiToolAnalyzer(str(repo_root))
    tools_results = analyzer.run_all()

    aggregator = EvidenceAggregator(tools_results, str(repo_root))
    unused_file_map, unused_symbol_map, unused_dep_map = aggregator.aggregate()

    if "knip" in analyzer.tools_success:
        analysis_state.add_signal_category("symbol_analysis")
    if unused_file_map:
        analysis_state.add_signal_category("file_analysis")
    if unused_dep_map:
        analysis_state.add_signal_category("dependency_analysis")
    analysis_state.add_signal_category("structure_analysis")
    analysis_state.finalize()

    confidence_multiplier = analysis_state.get_confidence_multiplier()

    unused_files = []
    for file_path in sorted(unused_file_map):
        modifier = expected_repo_modifier(repo_probs, "unusedFile")
        confidence = clamp(0.7 * modifier * confidence_multiplier, 0, 1)
        unused_files.append(
            {
                "file": file_path,
                "score": round(100 * confidence, 2),
                "confidence": round(confidence, 4),
            }
        )

    unused_exports = []
    for file_path, export_name in sorted(unused_symbol_map):
        modifier = expected_repo_modifier(repo_probs, "unusedExport")
        confidence = clamp(0.6 * modifier * confidence_multiplier, 0, 1)
        unused_exports.append(
            {
                "file": file_path,
                "name": export_name,
                "score": round(100 * confidence, 2),
                "confidence": round(confidence, 4),
            }
        )

    unused_deps = []
    for dep_name in sorted(unused_dep_map):
        modifier = expected_repo_modifier(repo_probs, "unusedDependency")
        confidence = clamp(0.8 * modifier * confidence_multiplier, 0, 1)
        unused_deps.append(
            {
                "name": dep_name,
                "score": round(100 * confidence, 2),
                "confidence": round(confidence, 4),
            }
        )

    summary = {
        "files": len(unused_files),
        "exports": len(unused_exports),
        "deps": len(unused_deps),
        "total": len(unused_files) + len(unused_exports) + len(unused_deps),
    }

    scores = {
        "overall": round(clamp(100 - (summary["total"] * 2), 0, 100), 2),
        "reliability": round(analysis_state.get_reliability_multiplier(), 4),
    }

    return {
        "repoType": repo_type,
        "unusedFiles": unused_files,
        "unusedExports": unused_exports,
        "unusedDeps": unused_deps,
        "summary": summary,
        "scores": scores,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "No path provided"}))
        sys.exit(1)

    result = scan_repo(sys.argv[1])
    print(json.dumps(result, indent=2))
