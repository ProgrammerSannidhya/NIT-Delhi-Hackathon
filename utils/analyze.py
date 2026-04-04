import subprocess
import json
import os
import re
import sys
import math
from collections import Counter, defaultdict

# =============================================================================
# UTILITIES
# =============================================================================

def run_cmd(cmd, cwd=None, timeout=120):
    try:
        r = subprocess.run(
            cmd, shell=True, cwd=cwd,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=timeout
        )
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "", "TIMEOUT", -1
    except Exception as e:
        return "", str(e), -1


def normalize(p):
    return (p or "").replace("\\", "/").strip()


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def safe_divide(numerator, denominator, default=0.0):
    try:
        if denominator == 0:
            return default
        return float(numerator) / float(denominator)
    except (ValueError, TypeError):
        return default


def sigmoid(x):
    try:
        return 1.0 / (1.0 + math.exp(-clamp(x, -100, 100)))
    except Exception:
        return 0.5


def robust_softmax(score_dict, temperature=1.0, epsilon=1e-6):
    """
    Convert scores to probabilities with temperature control and epsilon floor.
    """
    keys = list(score_dict.keys())
    vals = [score_dict[k] for k in keys]
    
    if not vals or all(v == 0 for v in vals):
        return {k: 1.0 / max(1, len(keys)) for k in keys}
    
    min_val = min(vals)
    max_val = max(vals)
    score_range = max_val - min_val
    
    if score_range < 0.1:
        return {k: 1.0 / len(keys) for k in keys}
    
    m = max(vals)
    try:
        scaled_vals = [(v - m) / max(0.1, temperature) for v in vals]
        exps = [math.exp(clamp(s, -100, 100)) for s in scaled_vals]
        s = sum(exps)
        
        if s <= 0:
            return {k: 1.0 / len(keys) for k in keys}
        
        raw_probs = {k: (e / s) for k, e in zip(keys, exps)}
        
        # Apply epsilon floor
        floored = {}
        for k, p in raw_probs.items():
            p_floored = max(epsilon, min(1.0 - epsilon, p))
            floored[k] = p_floored
        
        total = sum(floored.values())
        return {k: floored[k] / total for k in keys}
    except Exception:
        return {k: 1.0 / len(keys) for k in keys}


def compute_entropy(probability_dict):
    """Compute Shannon entropy."""
    entropy = 0.0
    for prob in probability_dict.values():
        if prob > 0:
            entropy -= prob * math.log(prob)
    return entropy


def compute_separation(probability_dict):
    """Compute separation between top two classes."""
    probs_sorted = sorted(probability_dict.values(), reverse=True)
    if len(probs_sorted) < 2:
        return probs_sorted[0] if probs_sorted else 0.0
    return probs_sorted[0] - probs_sorted[1]


def compute_normalized_entropy(probability_dict):
    """Compute entropy normalized to [0, 1]."""
    n = len(probability_dict)
    if n <= 1:
        return 0.0
    entropy = compute_entropy(probability_dict)
    max_entropy = math.log(n)
    return entropy / max_entropy if max_entropy > 0 else 0.0


# =============================================================================
# STATE DETECTION
# =============================================================================

class AnalysisState:
    """Tracks analysis pipeline state."""
    
    FAILED = "failed"
    PARTIAL = "partial"
    SUCCESS = "success"
    
    def __init__(self):
        self.state = self.FAILED
        self.signal_categories = set()
        self.missing_categories = set()
        self.notes = []
    
    def add_signal_category(self, category):
        self.signal_categories.add(category)
    
    def mark_missing_category(self, category):
        self.missing_categories.add(category)
    
    def finalize(self, has_unused_findings):
        expected_categories = {"symbol_analysis", "dependency_analysis", "structure_analysis", "tool_coverage"}
        
        if not self.signal_categories:
            self.state = self.FAILED
            self.notes.append("No analysis signals available")
            return
        
        if len(self.signal_categories) >= 3:
            self.state = self.SUCCESS
            self.notes.append("Full multi-tool coverage")
            return
        
        if len(self.signal_categories) >= 1:
            self.state = self.PARTIAL
            missing = expected_categories - self.signal_categories
            self.notes.append(f"Partial analysis: missing {', '.join(sorted(missing))}")
            return
    
    def is_failed(self):
        return self.state == self.FAILED
    
    def is_partial(self):
        return self.state == self.PARTIAL
    
    def is_success(self):
        return self.state == self.SUCCESS
    
    def get_confidence_multiplier(self):
        if self.is_failed():
            return 0.0
        elif self.is_partial():
            return 0.6
        else:
            return 1.0
    
    def get_reliability_multiplier(self):
        if self.is_failed():
            return 0.0
        elif self.is_partial():
            return 0.7
        else:
            return 1.0


# =============================================================================
# TEST FILTERING
# =============================================================================

TEST_DIR_TOKENS = {
    "test", "tests", "testing", "__test__", "__tests__",
    "__mock__", "__mocks__", "fixture", "fixtures",
    "cypress", "playwright", "e2e", "integration",
    "spec", "specs", "bench", "benchmark", "benchmarks"
}

TEST_FILE_REGEXES = [
    re.compile(r".*\.test\.[^/]+$", re.IGNORECASE),
    re.compile(r".*\.spec\.[^/]+$", re.IGNORECASE),
    re.compile(r".*_test\.[^/]+$", re.IGNORECASE),
    re.compile(r".*_spec\.[^/]+$", re.IGNORECASE),
]

TEST_FILE_BASENAMES = {
    "jest.config.js", "jest.config.cjs", "jest.config.mjs", "jest.config.ts",
    "vitest.config.js", "vitest.config.cjs", "vitest.config.mjs", "vitest.config.ts",
    "playwright.config.js", "playwright.config.ts", "cypress.config.js", "cypress.config.ts",
}


def is_test_path(path_value: str) -> bool:
    p = normalize(path_value)
    if not p:
        return False
    lowered = p.lower()
    parts = [part for part in lowered.split("/") if part]
    if any(part in TEST_DIR_TOKENS for part in parts):
        return True
    basename = parts[-1] if parts else lowered
    if basename in TEST_FILE_BASENAMES:
        return True
    return any(rx.match(lowered) for rx in TEST_FILE_REGEXES)


# =============================================================================
# HIERARCHICAL SIGNAL DETECTION
# =============================================================================

class HierarchicalSignalDetector:
    """
    Detects signals with HIERARCHY and SUPPRESSION.
    
    Class hierarchy (strongest to weakest):
    1. CLI (binary, strong identity)
    2. Plugin (extends systems, specific pattern)
    3. Framework (execution ownership)
    4. Library (independence, module exports)
    5. Application (fallback, generic)
    """
    
    HIERARCHY = ["cli", "plugin", "framework", "library", "application"]
    
    def __init__(self, repo_path):
        self.repo_path = repo_path
        self.signals = {}
    
    def detect_cli_entry(self):
        """CLI signal: strongest identity, binary-like."""
        pkg_path = os.path.join(self.repo_path, "package.json")
        has_bin_field = False
        
        if os.path.exists(pkg_path):
            try:
                with open(pkg_path, "r", encoding="utf-8") as f:
                    pkg = json.load(f)
                    has_bin_field = "bin" in pkg
            except Exception:
                pass
        
        arg_parsing_count = 0
        argv_count = 0
        total_files = 0
        
        for root, _, files in os.walk(self.repo_path):
            if any(part in root.lower() for part in ['node_modules', '.git', 'dist', 'build', 'test', 'spec']):
                continue
            
            for f in files:
                if not f.endswith(('.js', '.ts', '.jsx', '.tsx')):
                    continue
                
                total_files += 1
                filepath = os.path.join(root, f)
                
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as file:
                        content = file.read()
                    
                    if re.search(r"(yargs|commander|minimist|meow|chalk)\s*[=(]", content):
                        arg_parsing_count += 1
                    if re.search(r"process\.argv", content):
                        argv_count += 1
                except Exception:
                    pass
        
        signal_strength = 0.0
        if has_bin_field:
            signal_strength = 5.0  # Strong binary signal
        
        if total_files > 0:
            arg_ratio = safe_divide(arg_parsing_count, total_files)
            argv_ratio = safe_divide(argv_count, total_files)
            signal_strength += (arg_ratio * 1.5) + (argv_ratio * 0.8)
        
        self.signals["cli_entry"] = clamp(signal_strength, 0, 7)
        return self.signals["cli_entry"]
    
    def detect_plugin_pattern(self):
        """Plugin signal: specific extension/hook patterns."""
        plugin_patterns = [
            r"(extends|implements)\s+(Plugin|Extension|Adapter)",
            r"(plugin|extension|adapter|hook)\.register\(",
            r"\.registerPlugin\(|\.addExtension\(|\.installAdapter\(",
        ]
        
        matched = 0
        total_files = 0
        
        for root, _, files in os.walk(self.repo_path):
            if any(part in root.lower() for part in ['node_modules', '.git', 'dist', 'build', 'test', 'spec']):
                continue
            
            for f in files:
                if not f.endswith(('.js', '.ts', '.jsx', '.tsx')):
                    continue
                
                total_files += 1
                filepath = os.path.join(root, f)
                
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as file:
                        content = file.read()
                    
                    for pattern in plugin_patterns:
                        if re.search(pattern, content, re.IGNORECASE):
                            matched += 1
                            break
                except Exception:
                    pass
        
        if total_files == 0:
            self.signals["plugin"] = 0.0
            return 0.0
        
        ratio = safe_divide(matched, total_files)
        signal_strength = ratio * 4.5
        
        self.signals["plugin"] = clamp(signal_strength, 0, 6)
        return self.signals["plugin"]
    
    def detect_framework_ownership(self):
        """Framework signal: execution control (IoC, lifecycle)."""
        ioc_patterns = [
            (r"\.on\(['\"]", r"\.emit\(['\"]"),
            (r"\.addEventListener\(", r"\.removeEventListener\("),
            (r"\.subscribe\(", r"\.next\(|\.trigger\("),
            (r"\.use\(\w+\)|\.plugin\(\w+\)|\.middleware\(\w+\)", None),
            (r"(onInit|onDestroy|onMount|onUnmount|beforeCreate|afterCreate|setup)", None),
        ]
        
        lifecycle_patterns = [
            r"(initialize|setup|bootstrap|init|start|load)\s*\([^)]*\)\s*{",
            r"(update|render|change.*detect|tick|apply|process)\s*\([^)]*\)\s*{",
            r"(destroy|cleanup|teardown|unmount|dispose|release)\s*\([^)]*\)\s*{",
        ]
        
        ioc_matched = 0
        lifecycle_matched = 0
        total_files = 0
        
        for root, _, files in os.walk(self.repo_path):
            if any(part in root.lower() for part in ['node_modules', '.git', 'dist', 'build', 'test', 'spec']):
                continue
            
            for f in files:
                if not f.endswith(('.js', '.ts', '.jsx', '.tsx')):
                    continue
                
                total_files += 1
                filepath = os.path.join(root, f)
                
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as file:
                        content = file.read()
                    
                    # Check IoC
                    for pattern_tuple in ioc_patterns:
                        primary, secondary = pattern_tuple
                        if secondary:
                            if re.search(primary, content) and re.search(secondary, content):
                                ioc_matched += 1
                                break
                        else:
                            if re.search(primary, content, re.IGNORECASE):
                                ioc_matched += 1
                                break
                    
                    # Check lifecycle
                    for pattern in lifecycle_patterns:
                        if re.search(pattern, content, re.IGNORECASE):
                            lifecycle_matched += 1
                            break
                except Exception:
                    pass
        
        if total_files == 0:
            self.signals["framework"] = 0.0
            return 0.0
        
        ioc_ratio = safe_divide(ioc_matched, total_files)
        lifecycle_ratio = safe_divide(lifecycle_matched, total_files)
        
        # Combine: lifecycle is stronger indicator
        signal_strength = (lifecycle_ratio * 2.5) + (ioc_ratio * 1.5)
        
        self.signals["framework"] = clamp(signal_strength, 0, 6.5)
        return self.signals["framework"]
    
    def detect_library_independence(self):
        """Library signal: independent modules, high exports, low coupling."""
        graph = defaultdict(set)
        total_files = 0
        files_with_exports = 0
        
        for root, _, files in os.walk(self.repo_path):
            if any(part in root.lower() for part in ['node_modules', '.git', 'dist', 'build', 'test', 'spec']):
                continue
            
            for f in files:
                if not f.endswith(('.js', '.ts', '.jsx', '.tsx')):
                    continue
                
                total_files += 1
                filepath = os.path.join(root, f)
                rel_path = normalize(os.path.relpath(filepath, self.repo_path))
                
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as file:
                        content = file.read()
                    
                    exports = len(re.findall(r'\bexport\b', content))
                    if exports > 0:
                        files_with_exports += 1
                    
                    for pattern in [re.compile(r"from\s+['\"]([^'\"]+)['\"]"),
                                   re.compile(r"import\s+['\"]([^'\"]+)['\"]"),
                                   re.compile(r"require\s*\(\s*['\"]([^'\"]+)['\"]\s*\)")]:
                        for match in pattern.finditer(content):
                            imported = match.group(1)
                            if imported.startswith('.'):
                                graph[rel_path].add(imported)
                except Exception:
                    pass
        
        if total_files == 0:
            self.signals["library"] = 0.0
            return 0.0
        
        total_deps = sum(len(deps) for deps in graph.values())
        avg_deps_per_file = safe_divide(total_deps, total_files)
        coupling_score = max(0, 1.0 - (avg_deps_per_file / 3.0))
        
        export_ratio = safe_divide(files_with_exports, total_files)
        
        isolated = sum(1 for deps in graph.values() if len(deps) == 0)
        isolation_ratio = safe_divide(isolated, total_files)
        
        signal_strength = (coupling_score * 2.0) + (export_ratio * 1.5) + (isolation_ratio * 1.5)
        
        self.signals["library"] = clamp(signal_strength, 0, 6.5)
        return self.signals["library"]
    
    def detect_application_structure(self):
        """Application signal: multi-domain structure (fallback class)."""
        app_domains = {"routes", "pages", "services", "components", "controllers", "models", "views", "features"}
        
        found_dirs = set()
        max_depth = 0
        
        for root, dirs, _ in os.walk(self.repo_path):
            if any(part in root.lower() for part in ['node_modules', '.git', 'dist', 'build']):
                continue
            
            found_dirs.update(d.lower() for d in dirs)
            
            rel = os.path.relpath(root, self.repo_path)
            depth = len([p for p in rel.split(os.sep) if p and p != '.'])
            max_depth = max(max_depth, depth)
        
        domain_count = len(found_dirs & app_domains)
        depth_signal = clamp(sigmoid(max_depth - 3.0), 0, 1)
        
        signal_strength = (domain_count * 1.0) + (depth_signal * 1.2)
        
        self.signals["application"] = clamp(signal_strength, 0, 5)
        return self.signals["application"]
    
    def analyze_all(self):
        """Run all detectors."""
        self.detect_cli_entry()
        self.detect_plugin_pattern()
        self.detect_framework_ownership()
        self.detect_library_independence()
        self.detect_application_structure()
        
        return self.signals


# =============================================================================
# MULTI-TOOL RUNNERS
# =============================================================================

class MultiToolAnalyzer:
    """Runs multiple analysis tools."""
    
    def __init__(self, repo_path):
        self.repo_path = repo_path
        self.tools_run = []
        self.tools_success = []
        self.results = {}
    
    def run_knip(self):
        try:
            raw, err, code = run_cmd("npx knip --reporter json", cwd=self.repo_path, timeout=180)
            self.tools_run.append("knip")
            if not raw or code != 0:
                return None
            try:
                data = json.loads(raw)
                self.tools_success.append("knip")
                return data
            except Exception:
                return None
        except Exception:
            return None
    
    def run_depcheck(self):
        try:
            check, _, _ = run_cmd("npx depcheck --version", cwd=self.repo_path, timeout=10)
            if not check:
                return None
            raw, err, code = run_cmd("npx depcheck --json", cwd=self.repo_path, timeout=60)
            self.tools_run.append("depcheck")
            if not raw:
                return None
            try:
                data = json.loads(raw)
                self.tools_success.append("depcheck")
                return data
            except Exception:
                return None
        except Exception:
            return None
    
    def run_madge(self):
        try:
            check, _, _ = run_cmd("npx madge --version", cwd=self.repo_path, timeout=10)
            if not check:
                return None
            raw, err, code = run_cmd(
                "npx madge --json src 2>/dev/null || npx madge --json . 2>/dev/null || echo '{}'",
                cwd=self.repo_path, timeout=60
            )
            self.tools_run.append("madge")
            if not raw:
                return None
            try:
                data = json.loads(raw)
                self.tools_success.append("madge")
                return data
            except Exception:
                return None
        except Exception:
            return None
    
    def run_ts_prune(self):
        try:
            pkg_path = os.path.join(self.repo_path, "package.json")
            if not os.path.exists(pkg_path):
                return None
            with open(pkg_path, "r") as f:
                pkg = json.load(f)
                if "typescript" not in pkg.get("dependencies", {}) and \
                   "typescript" not in pkg.get("devDependencies", {}):
                    return None
            check, _, _ = run_cmd("npx ts-prune --version", cwd=self.repo_path, timeout=10)
            if not check:
                return None
            raw, err, code = run_cmd("npx ts-prune", cwd=self.repo_path, timeout=60)
            self.tools_run.append("ts-prune")
            if not raw:
                return None
            unused_exports = []
            for line in raw.split("\n"):
                line = line.strip()
                if line and " - " in line:
                    parts = line.split(" - ")
                    if len(parts) >= 2:
                        file_info = parts[0].strip()
                        symbol = parts[1].strip()
                        if ":" in file_info:
                            filepath = file_info.split(":")[0]
                            unused_exports.append((filepath, symbol))
            self.tools_success.append("ts-prune")
            return {"unused": unused_exports} if unused_exports else None
        except Exception:
            return None
    
    def run_all(self):
        if os.path.exists(os.path.join(self.repo_path, "package.json")):
            run_cmd("npm install --ignore-scripts --prefer-offline", cwd=self.repo_path, timeout=120)
        self.results["knip"] = self.run_knip()
        self.results["depcheck"] = self.run_depcheck()
        self.results["madge"] = self.run_madge()
        self.results["ts_prune"] = self.run_ts_prune()
        return self.results


# =============================================================================
# EVIDENCE AGGREGATION
# =============================================================================

class EvidenceAggregator:
    """Aggregates multi-tool outputs."""
    
    def __init__(self, tools_results, repo_path):
        self.tools_results = tools_results
        self.repo_path = repo_path
    
    def aggregate_unused_symbols(self):
        exports = defaultdict(set)
        tool_count = 0
        if self.tools_results.get("knip"):
            tool_count += 1
            for issue in self.tools_results["knip"].get("issues", []):
                for exp in issue.get("exports", []):
                    filepath = normalize(exp.get("file", ""))
                    symbol = exp.get("name") or exp.get("symbol", "")
                    if filepath and symbol and not is_test_path(filepath):
                        exports[(filepath, symbol)].add("knip")
        if self.tools_results.get("ts_prune"):
            tool_count += 1
            for filepath, symbol in self.tools_results["ts_prune"].get("unused", []):
                filepath = normalize(filepath)
                if filepath and symbol and not is_test_path(filepath):
                    exports[(filepath, symbol)].add("ts-prune")
        agreement_counts = {}
        for key, tools in exports.items():
            agreement_counts[key] = len(tools) / max(1, tool_count) if tool_count > 0 else 0
        return dict(exports), agreement_counts, tool_count > 0
    
    def aggregate_unused_files(self):
        files = defaultdict(set)
        tool_count = 0
        if self.tools_results.get("knip"):
            tool_count += 1
            for issue in self.tools_results["knip"].get("issues", []):
                if issue.get("type") == "unused-file":
                    filepath = normalize(issue.get("file", ""))
                    if filepath and not is_test_path(filepath):
                        files[filepath].add("knip")
        if self.tools_results.get("madge"):
            tool_count += 1
            madge_data = self.tools_results["madge"]
            if isinstance(madge_data, dict):
                for module, deps in madge_data.items():
                    if not deps or (isinstance(deps, list) and len(deps) == 0):
                        filepath = normalize(module)
                        if filepath and not is_test_path(filepath):
                            files[filepath].add("madge")
        agreement_counts = {}
        for key, tools in files.items():
            agreement_counts[key] = len(tools) / max(1, tool_count) if tool_count > 0 else 0
        return dict(files), agreement_counts, tool_count > 0
    
    def aggregate_unused_dependencies(self):
        deps = defaultdict(set)
        tool_count = 0
        if self.tools_results.get("knip"):
            tool_count += 1
            for issue in self.tools_results["knip"].get("issues", []):
                for d in issue.get("dependencies", []) + issue.get("devDependencies", []):
                    dep_name = d.get("name") or d.get("symbol", "")
                    if dep_name:
                        deps[dep_name].add("knip")
        if self.tools_results.get("depcheck"):
            tool_count += 1
            unused_list = self.tools_results["depcheck"].get("dependencies", [])
            for dep_name in unused_list:
                if dep_name:
                    deps[dep_name].add("depcheck")
        agreement_counts = {}
        for key, tools in deps.items():
            agreement_counts[key] = len(tools) / max(1, tool_count) if tool_count > 0 else 0
        return dict(deps), agreement_counts, tool_count > 0


# =============================================================================
# HIERARCHICAL CLASSIFICATION
# =============================================================================

REPO_TYPES = ["application", "library", "framework", "cli", "plugin"]

REPO_TYPE_MODIFIERS = {
    "library":     {"unusedExport": 0.3,  "unusedFile": 0.8,  "unusedDependency": 1.0},
    "application": {"unusedExport": 0.8,  "unusedFile": 1.0,  "unusedDependency": 1.0},
    "framework":   {"unusedExport": 0.5,  "unusedFile": 0.6,  "unusedDependency": 0.9},
    "cli":         {"unusedExport": 0.6,  "unusedFile": 0.9,  "unusedDependency": 1.0},
    "plugin":      {"unusedExport": 0.4,  "unusedFile": 0.7,  "unusedDependency": 0.9},
}


def ensure_repo_probabilities(repo_probs):
    """Ensure valid probability distribution."""
    if not repo_probs:
        uniform = 1.0 / len(REPO_TYPES)
        return {t: uniform for t in REPO_TYPES}
    
    cleaned = {}
    for t in REPO_TYPES:
        v = repo_probs.get(t, 0.0)
        try:
            v = float(v)
        except (ValueError, TypeError):
            v = 0.0
        cleaned[t] = max(0.0, v)
    
    total = sum(cleaned.values())
    if total <= 0:
        uniform = 1.0 / len(REPO_TYPES)
        return {t: uniform for t in REPO_TYPES}
    
    return {t: cleaned[t] / total for t in REPO_TYPES}


def classify_repo_type(strong_signals):
    """
    Hierarchical classification with suppression rules.
    
    Hierarchy (strongest to weakest):
    1. CLI: binary identity, strongest
    2. Plugin: specific extension pattern
    3. Framework: execution ownership (IoC + lifecycle)
    4. Library: independence + exports
    5. Application: fallback, generic multi-domain
    """
    # Start with equal baseline
    scores = {t: 1.0 for t in REPO_TYPES}
    
    cli_signal = strong_signals.get("cli_entry", 0.0)
    plugin_signal = strong_signals.get("plugin", 0.0)
    framework_signal = strong_signals.get("framework", 0.0)
    library_signal = strong_signals.get("library", 0.0)
    app_signal = strong_signals.get("application", 0.0)
    
    # === THRESHOLD-BASED SUPPRESSION ===
    # Only apply suppression when signal exceeds threshold
    
    # TIER 1: CLI (strongest, binary identity)
    CLI_THRESHOLD = 2.0
    if cli_signal >= CLI_THRESHOLD:
        scores["cli"] += cli_signal * 3.0
        # CLI suppresses everything else heavily
        scores["application"] *= 0.15
        scores["framework"] *= 0.2
        scores["library"] *= 0.25
        scores["plugin"] *= 0.3
    
    # TIER 2: Plugin (specific pattern)
    PLUGIN_THRESHOLD = 1.5
    if plugin_signal >= PLUGIN_THRESHOLD and cli_signal < CLI_THRESHOLD:
        scores["plugin"] += plugin_signal * 2.5
        # Plugin suppresses application and library
        scores["application"] *= 0.3
        scores["library"] *= 0.4
    
    # TIER 3: Framework (execution ownership - MUST override application)
    FRAMEWORK_THRESHOLD = 1.0
    if framework_signal >= FRAMEWORK_THRESHOLD:
        scores["framework"] += framework_signal * 3.0
        # Framework STRONGLY suppresses application (critical)
        scores["application"] *= 0.2
        # Framework moderately suppresses library
        scores["library"] *= 0.5
        # If framework is strong, reduce plugin
        if framework_signal >= 3.0:
            scores["plugin"] *= 0.5
    
    # TIER 4: Library (independence, should override application)
    LIBRARY_THRESHOLD = 1.5
    if library_signal >= LIBRARY_THRESHOLD:
        scores["library"] += library_signal * 2.2
        # Library suppresses application moderately
        scores["application"] *= 0.4
        # But not plugin (plugin can be a library extension)
    
    # TIER 5: Application (fallback, only if no stronger signal)
    # Application baseline is already 1.0, but it gets suppressed by everything else
    # Only boost if weak signal and no other class is strong
    if app_signal > 1.0 and \
       framework_signal < FRAMEWORK_THRESHOLD and \
       library_signal < LIBRARY_THRESHOLD and \
       plugin_signal < PLUGIN_THRESHOLD and \
       cli_signal < CLI_THRESHOLD:
        scores["application"] += app_signal * 1.0
    
    # === CONFLICT RESOLUTION ===
    # If multiple strong signals from competing classes exist
    framework_lib_conflict = min(framework_signal, library_signal)
    if framework_lib_conflict >= 2.0:
        # Both strong: reduce both slightly
        conflict_penalty = 0.15
        scores["framework"] *= (1.0 - conflict_penalty)
        scores["library"] *= (1.0 - conflict_penalty)
    
    # === TEMPERATURE CALIBRATION ===
    # Hierarchy allows sharper distributions
    max_signal = max(cli_signal, plugin_signal, framework_signal, library_signal, app_signal)
    strong_signal_count = sum(1 for s in [cli_signal, plugin_signal, framework_signal, library_signal, app_signal] if s >= 2.0)
    
    if max_signal >= 4.0:
        temperature = 0.6  # Sharp
    elif max_signal >= 2.5:
        temperature = 0.9  # Medium-sharp
    elif max_signal >= 1.5:
        temperature = 1.3  # Medium
    else:
        temperature = 2.2  # Flat (uncertainty)
    
    probs = robust_softmax(scores, temperature=temperature, epsilon=1e-6)
    probs = ensure_repo_probabilities(probs)
    
    return scores, probs


def make_repo_type_decision(probs, detection_reliability, analysis_state):
    """Make probabilistic decision with calibrated thresholds."""
    
    if analysis_state.is_failed():
        return {
            "type": "unknown",
            "confidence": 0.0,
            "probabilities": {k: round(v, 4) for k, v in probs.items()},
            "separation": 0.0,
            "entropy": 0.0,
            "reason": "Insufficient analysis signals"
        }
    
    entropy = compute_normalized_entropy(probs)
    separation = compute_separation(probs)
    
    top_type = max(probs, key=probs.get)
    top_prob = probs[top_type]
    
    if analysis_state.is_partial():
        SEPARATION_THRESHOLD = 0.12
        ENTROPY_THRESHOLD = 0.75
        RELIABILITY_THRESHOLD = 0.35
        CONFIDENCE_THRESHOLD = 0.25
    else:
        SEPARATION_THRESHOLD = 0.18
        ENTROPY_THRESHOLD = 0.65
        RELIABILITY_THRESHOLD = 0.5
        CONFIDENCE_THRESHOLD = 0.35
    
    if detection_reliability < RELIABILITY_THRESHOLD:
        return {
            "type": "uncertain",
            "confidence": round(detection_reliability, 4),
            "probabilities": {k: round(v, 4) for k, v in probs.items()},
            "separation": round(separation, 4),
            "entropy": round(entropy, 4),
            "reason": "Detection reliability too low"
        }
    
    if top_prob < CONFIDENCE_THRESHOLD:
        return {
            "type": "uncertain",
            "confidence": round(top_prob, 4),
            "probabilities": {k: round(v, 4) for k, v in probs.items()},
            "separation": round(separation, 4),
            "entropy": round(entropy, 4),
            "reason": "No class achieves minimum confidence"
        }
    
    if entropy > ENTROPY_THRESHOLD:
        return {
            "type": "uncertain",
            "confidence": round(top_prob, 4),
            "probabilities": {k: round(v, 4) for k, v in probs.items()},
            "separation": round(separation, 4),
            "entropy": round(entropy, 4),
            "reason": "Distribution too flat (high entropy)"
        }
    
    if separation < SEPARATION_THRESHOLD:
        return {
            "type": "uncertain",
            "confidence": round(top_prob, 4),
            "probabilities": {k: round(v, 4) for k, v in probs.items()},
            "separation": round(separation, 4),
            "entropy": round(entropy, 4),
            "reason": "Insufficient separation between classes"
        }
    
    final_confidence = clamp(
        top_prob * (1.0 + separation) * (1.0 - entropy) * detection_reliability,
        0, 0.95
    )
    
    return {
        "type": top_type,
        "confidence": round(final_confidence, 4),
        "probabilities": {k: round(v, 4) for k, v in probs.items()},
        "separation": round(separation, 4),
        "entropy": round(entropy, 4),
        "reason": None
    }


def expected_repo_modifier(repo_probs, item_type):
    """Compute expected modifier across repo types."""
    rp = ensure_repo_probabilities(repo_probs)
    return sum(rp[t] * REPO_TYPE_MODIFIERS[t][item_type] for t in REPO_TYPES)


# =============================================================================
# CONFIDENCE & SCORING
# =============================================================================

WEIGHTS = {
    "w1": 3.0, "w2": 2.0, "w3": 3.5, "w4": 4.0, "w5": 4.5, "w6": 2.5
}

BASE_SEVERITY = {
    "unusedFile": 1.0, "unusedDependency": 1.0, "unusedExport": 0.7
}

PENALTY_WEIGHT = {
    "unusedFile": 2.0, "unusedDependency": 2.0, "unusedExport": 1.0
}

DEPENDENCY_MODIFIERS = {
    "runtime": 1.0, "optional": 0.6, "tooling": 0.5, "example": 0.4
}


def heuristic_feature_scores(item_type, path_or_name):
    """Compute heuristic features for an item."""
    x = normalize(path_or_name).lower()
    
    referenceScore = 0.7
    usageScore = 0.7
    reachability = 0.7
    dynamicPenalty = 0.1
    contextPenalty = 0.1
    ecosystemUncertainty = 0.1
    
    if item_type == "unusedExport":
        if any(k in x for k in ["/index.", "/lib/", "/api/", "/exports", "/utils"]):
            contextPenalty += 0.5
            ecosystemUncertainty += 0.2
        if any(k in x for k in ["/internal/", "/private/"]):
            referenceScore += 0.2
            usageScore += 0.2
            contextPenalty = max(0, contextPenalty - 0.1)
    
    if item_type == "unusedFile":
        if any(k in x for k in ["/core/", "/src/core/", "/server/", "/runtime/"]):
            reachability += 0.25
        if any(k in x for k in ["/utils/", "/helpers/"]):
            usageScore = max(0, usageScore - 0.15)
    
    if item_type == "unusedDependency":
        if any(k in x for k in ["babel", "webpack", "vite", "eslint", "prettier", "jest", "vitest"]):
            ecosystemUncertainty += 0.2
    
    return (
        clamp(referenceScore, 0, 1),
        clamp(usageScore, 0, 1),
        clamp(reachability, 0, 1),
        clamp(dynamicPenalty, 0, 1),
        clamp(contextPenalty, 0, 1),
        clamp(ecosystemUncertainty, 0, 1),
    )


def classify_dependency_context(dep_name: str) -> str:
    """Classify dependency type."""
    d = (dep_name or "").lower()
    if d in ["eslint", "prettier", "jest", "vitest", "babel", "webpack", "vite", "rollup", "parcel"]:
        return "tooling"
    if d in ["morgan", "ejs", "hbs", "express-session", "connect-redis"]:
        return "optional"
    if "example" in d or "demo" in d:
        return "example"
    return "runtime"


def detect_usage_context(repo_path):
    """Detect usage context."""
    paths = []
    for root, dirs, _ in os.walk(repo_path):
        for d in dirs:
            paths.append(os.path.join(root, d).lower())
    return {
        "has_examples": any("example" in p or "demo" in p for p in paths),
        "has_docs": any("doc" in p for p in paths),
        "has_playground": any("playground" in p for p in paths),
    }


def compute_evidence_factor(item_type, repo_probs, dependency_type=None, context=None):
    """Compute evidence factor."""
    factor = 1.0
    context = context or {}
    rp = ensure_repo_probabilities(repo_probs)
    if rp.get("library", 0) > 0.6:
        factor *= 0.82
    if item_type == "unusedDependency":
        factor *= 0.85
    if dependency_type == "optional":
        factor *= 0.75
    if context.get("has_examples") or context.get("has_docs"):
        if item_type == "unusedDependency":
            factor *= 0.80
    return clamp(factor, 0.5, 1.5)


def compute_detection_reliability(summary, repo_probs, tools_successful, analysis_state):
    """Compute detection reliability."""
    total = summary.get("total", 0)
    reliability = 1.0
    rp = ensure_repo_probabilities(repo_probs)
    if total == 0:
        reliability *= 0.75
    if rp.get("library", 0) > 0.65:
        reliability *= 0.92
    if rp.get("framework", 0) > 0.50:
        reliability *= 0.85
    if len(tools_successful) >= 3:
        reliability *= 1.18
    elif len(tools_successful) >= 2:
        reliability *= 1.08
    reliability *= analysis_state.get_reliability_multiplier()
    return clamp(reliability, 0.0, 1.0)


def base_confidence(item_type, path_or_name):
    """Compute base confidence."""
    r, u, reach, dyn, ctx, eco = heuristic_feature_scores(item_type, path_or_name)
    s = (
        WEIGHTS["w1"] * r +
        WEIGHTS["w2"] * u +
        WEIGHTS["w3"] * reach -
        WEIGHTS["w4"] * dyn -
        WEIGHTS["w5"] * ctx -
        WEIGHTS["w6"] * eco
    )
    return sigmoid(s)


def classify_confidence(c):
    """Classify confidence level."""
    if c >= 0.75:
        return "high"
    if c >= 0.45:
        return "medium"
    return "low"


def item_score(confidence, item_type, impact=1.0, context_factor=1.0):
    """Compute item score."""
    return 100.0 * confidence * BASE_SEVERITY[item_type] * impact * context_factor


# =============================================================================
# MAIN SCAN
# =============================================================================

def scan_repo(repo_path):
    """Main scanning function using hierarchical classification."""
    if not os.path.exists(repo_path):
        return {"error": "repo path not found"}
    
    analysis_state = AnalysisState()
    
    try:
        # ===== RUN HIERARCHICAL SIGNAL DETECTION =====
        signal_detector = HierarchicalSignalDetector(repo_path)
        strong_signals = signal_detector.analyze_all()
        
        # ===== RUN MULTI-TOOL ANALYSIS =====
        analyzer = MultiToolAnalyzer(repo_path)
        tools_results = analyzer.run_all()
        
        knip_data = tools_results.get("knip")
        
        if knip_data:
            analysis_state.add_signal_category("symbol_analysis")
        else:
            analysis_state.mark_missing_category("symbol_analysis")
        
        # ===== AGGREGATE EVIDENCE =====
        aggregator = EvidenceAggregator(tools_results, repo_path)
        evidence_symbols, symbol_agreement, has_symbol_data = aggregator.aggregate_unused_symbols()
        evidence_files, file_agreement, has_file_data = aggregator.aggregate_unused_files()
        evidence_deps, dep_agreement, has_dep_data = aggregator.aggregate_unused_dependencies()
        
        if has_symbol_data:
            analysis_state.add_signal_category("symbol_analysis")
        if has_file_data:
            analysis_state.add_signal_category("file_analysis")
        if has_dep_data:
            analysis_state.add_signal_category("dependency_analysis")
        
        analysis_state.add_signal_category("structure_analysis")
        analysis_state.add_signal_category("tool_coverage")
        
        # ===== FINALIZE STATE =====
        has_unused_findings = (len(evidence_files) + len(evidence_symbols) + len(evidence_deps)) > 0
        analysis_state.finalize(has_unused_findings)
        
        if analysis_state.is_failed():
            return {
                "status": "failed",
                "error": "Insufficient analysis signals",
                "notes": analysis_state.notes,
                "toolsRun": analyzer.tools_run,
                "toolsSuccess": analyzer.tools_success,
            }
        
        # ===== CLASSIFY REPO TYPE (HIERARCHICAL) =====
        repo_scores, repo_probs = classify_repo_type(strong_signals)
        
        # ===== MAKE DECISION =====
        summary = {
            "files": len(evidence_files),
            "exports": len(evidence_symbols),
            "deps": len(evidence_deps),
            "total": len(evidence_files) + len(evidence_symbols) + len(evidence_deps)
        }
        
        detection_reliability = compute_detection_reliability(summary, repo_probs, analyzer.tools_success, analysis_state)
        decision = make_repo_type_decision(repo_probs, detection_reliability, analysis_state)
        
        # ===== PROCESS FINDINGS =====
        usage_context = detect_usage_context(repo_path)
        
        unusedFiles, unusedExports, unusedDeps = [], [], []
        all_items = []
        
        confidence_multiplier = analysis_state.get_confidence_multiplier()
        
        for filepath in evidence_files:
            bc = base_confidence("unusedFile", filepath)
            mod = expected_repo_modifier(repo_probs, "unusedFile")
            agreement = file_agreement.get(filepath, 0)
            agreement_boost = 1.0 + (agreement - 1.0 / 3) * 0.2 if agreement > 0 else 0.88
            fc = clamp(bc * mod * agreement_boost * confidence_multiplier, 0, 1)
            sc = item_score(fc, "unusedFile")
            
            unusedFiles.append({
                "file": filepath,
                "type": "unusedFile",
                "baseConfidence": round(bc, 4),
                "repoTypeModifier": round(mod, 4),
                "toolAgreement": round(agreement, 4),
                "finalConfidence": round(fc, 4),
                "confidenceLabel": classify_confidence(fc),
                "score": round(sc, 2)
            })
            all_items.append(unusedFiles[-1])
        
        for (filepath, symbol), tools in evidence_symbols.items():
            bc = base_confidence("unusedExport", f"{filepath}::{symbol}")
            mod = expected_repo_modifier(repo_probs, "unusedExport")
            agreement = symbol_agreement.get((filepath, symbol), 0)
            agreement_boost = 1.0 + (agreement - 0.5) * 0.2 if agreement > 0 else 0.88
            fc = clamp(bc * mod * agreement_boost * confidence_multiplier, 0, 1)
            sc = item_score(fc, "unusedExport")
            
            unusedExports.append({
                "file": filepath,
                "name": symbol,
                "type": "unusedExport",
                "baseConfidence": round(bc, 4),
                "repoTypeModifier": round(mod, 4),
                "toolAgreement": round(agreement, 4),
                "finalConfidence": round(fc, 4),
                "confidenceLabel": classify_confidence(fc),
                "score": round(sc, 2)
            })
            all_items.append(unusedExports[-1])
        
        for dep_name in evidence_deps:
            bc = base_confidence("unusedDependency", dep_name)
            mod = expected_repo_modifier(repo_probs, "unusedDependency")
            dep_type = classify_dependency_context(dep_name)
            dep_modifier = DEPENDENCY_MODIFIERS[dep_type]
            ev_factor = compute_evidence_factor("unusedDependency", repo_probs, dep_type, usage_context)
            agreement = dep_agreement.get(dep_name, 0)
            agreement_boost = 1.0 + (agreement - 0.5) * 0.2 if agreement > 0 else 0.88
            
            fc = clamp(bc * mod * dep_modifier * ev_factor * agreement_boost * confidence_multiplier, 0, 1)
            sc = item_score(fc, "unusedDependency")
            
            unusedDeps.append({
                "name": dep_name,
                "type": "unusedDependency",
                "dependencyType": dep_type,
                "dependencyModifier": dep_modifier,
                "evidenceFactor": round(ev_factor, 4),
                "baseConfidence": round(bc, 4),
                "repoTypeModifier": round(mod, 4),
                "toolAgreement": round(agreement, 4),
                "finalConfidence": round(fc, 4),
                "confidenceLabel": classify_confidence(fc),
                "score": round(sc, 2)
            })
            all_items.append(unusedDeps[-1])
        
        # ===== COMPUTE SCORES =====
        repo_penalty = sum(PENALTY_WEIGHT[i["type"]] * i["finalConfidence"] for i in all_items)
        actionable_penalty = sum(
            PENALTY_WEIGHT[i["type"]] * i["finalConfidence"]
            for i in all_items if i["finalConfidence"] >= 0.45
        )
        
        reliability_penalty = (1.0 - detection_reliability) * 10.0
        overall = round(max(0.0, 100.0 - (repo_penalty + reliability_penalty)), 2)
        actionable = round(max(0.0, 100.0 - actionable_penalty), 2)
        
        counts = defaultdict(int)
        for i in all_items:
            counts[i["confidenceLabel"]] += 1
        
        if summary["total"] == 0:
            analysis = {
                "status": "no_unused_code" if detection_reliability >= 0.5 else "low_reliability",
                "message": "No unused code detected" if detection_reliability >= 0.5 else "Unable to reliably detect unused code"
            }
        else:
            analysis = {
                "status": "unused_code_detected",
                "message": "Unused code found with computed confidence"
            }
        
        entropy = compute_normalized_entropy(decision["probabilities"])
        separation = compute_separation(decision["probabilities"])
        
        return {
            "status": analysis_state.state,
            "repoType": decision,
            "repoTypeScores": {k: round(v, 4) for k, v in repo_scores.items()},
            "unusedFiles": unusedFiles,
            "unusedExports": unusedExports,
            "unusedDeps": unusedDeps,
            "summary": summary,
            "scores": {
                "repoPenalty": round(repo_penalty, 4),
                "overall": overall,
                "actionable": actionable,
                "countsByConfidence": {
                    "high": counts["high"],
                    "medium": counts["medium"],
                    "low": counts["low"]
                },
                "detectionReliability": round(detection_reliability, 4)
            },
            "analysis": analysis,
            "debug": {
                "analysisState": {
                    "state": analysis_state.state,
                    "notes": analysis_state.notes,
                },
                "strongSignals": {k: round(v, 4) for k, v in strong_signals.items()},
                "distribution": {
                    "entropy": round(entropy, 4),
                    "separation": round(separation, 4)
                },
                "toolsRun": analyzer.tools_run,
                "toolsSuccess": analyzer.tools_success,
            }
        }
    
    except Exception as e:
        import traceback
        return {
            "status": "error",
            "error": str(e),
            "trace": traceback.format_exc()
        }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "repo path required"}))
        sys.exit(1)
    
    repo_path = sys.argv[1]
    result = scan_repo(repo_path)
    print(json.dumps(result, indent=2))