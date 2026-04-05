import subprocess
import json
import os
import re
import sys
import math
from collections import defaultdict
from pathlib import Path

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
    keys = list(score_dict.keys())
    vals = [score_dict[k] for k in keys]

    if not vals or all(v == 0 for v in vals):
        return {k: 1.0 / max(1, len(keys)) for k in keys}

    min_val = min(vals)
    max_val = max(vals)

    if (max_val - min_val) < 0.05:
        return {k: 1.0 / len(keys) for k in keys}

    m = max_val
    try:
        scaled = [(v - m) / max(0.05, temperature) for v in vals]
        exps   = [math.exp(clamp(s, -100, 100)) for s in scaled]
        s      = sum(exps)
        if s <= 0:
            return {k: 1.0 / len(keys) for k in keys}
        raw = {k: e / s for k, e in zip(keys, exps)}
        flo = {k: max(epsilon, min(1.0 - epsilon, p)) for k, p in raw.items()}
        tot = sum(flo.values())
        return {k: flo[k] / tot for k in keys}
    except Exception:
        return {k: 1.0 / len(keys) for k in keys}


def compute_entropy(probability_dict):
    entropy = 0.0
    for prob in probability_dict.values():
        if prob > 0:
            entropy -= prob * math.log(prob)
    return entropy


def compute_separation(probability_dict):
    probs_sorted = sorted(probability_dict.values(), reverse=True)
    if len(probs_sorted) < 2:
        return probs_sorted[0] if probs_sorted else 0.0
    return probs_sorted[0] - probs_sorted[1]


def compute_normalized_entropy(probability_dict):
    n = len(probability_dict)
    if n <= 1:
        return 0.0
    entropy     = compute_entropy(probability_dict)
    max_entropy = math.log(n)
    return entropy / max_entropy if max_entropy > 0 else 0.0


# =============================================================================
# STATE DETECTION
# =============================================================================

class AnalysisState:
    FAILED  = "failed"
    PARTIAL = "partial"
    SUCCESS = "success"

    def __init__(self):
        self.state              = self.FAILED
        self.signal_categories  = set()
        self.missing_categories = set()
        self.notes              = []

    def add_signal_category(self, category):    self.signal_categories.add(category)
    def mark_missing_category(self, category):  self.missing_categories.add(category)

    def finalize(self, has_unused_findings):
        if not self.signal_categories:
            self.state = self.FAILED
            self.notes.append("No analysis signals available")
            return
        if len(self.signal_categories) >= 3:
            self.state = self.SUCCESS
            self.notes.append("Full multi-signal coverage")
            return
        self.state = self.PARTIAL
        self.notes.append(f"Partial: {len(self.signal_categories)} signal categories")

    def is_failed(self):  return self.state == self.FAILED
    def is_partial(self): return self.state == self.PARTIAL
    def is_success(self): return self.state == self.SUCCESS

    def get_confidence_multiplier(self):
        if self.is_failed():  return 0.0
        if self.is_partial(): return 0.6
        return 1.0

    def get_reliability_multiplier(self):
        if self.is_failed():  return 0.0
        if self.is_partial(): return 0.7
        return 1.0


# =============================================================================
# TEST FILTERING
# =============================================================================

TEST_DIR_TOKENS = {
    "test","tests","testing","__test__","__tests__",
    "__mock__","__mocks__","fixture","fixtures",
    "cypress","playwright","e2e","integration",
    "spec","specs","bench","benchmark","benchmarks"
}

TEST_FILE_REGEXES = [
    re.compile(r".*\.test\.[^/]+$",  re.IGNORECASE),
    re.compile(r".*\.spec\.[^/]+$",  re.IGNORECASE),
    re.compile(r".*_test\.[^/]+$",   re.IGNORECASE),
    re.compile(r".*_spec\.[^/]+$",   re.IGNORECASE),
]

TEST_FILE_BASENAMES = {
    "jest.config.js","jest.config.cjs","jest.config.mjs","jest.config.ts",
    "vitest.config.js","vitest.config.cjs","vitest.config.mjs","vitest.config.ts",
    "playwright.config.js","playwright.config.ts",
    "cypress.config.js","cypress.config.ts",
}


def is_test_path(path_value: str) -> bool:
    p = normalize(path_value)
    if not p: return False
    lowered = p.lower()
    parts   = [x for x in lowered.split("/") if x]
    if any(part in TEST_DIR_TOKENS for part in parts): return True
    basename = parts[-1] if parts else lowered
    if basename in TEST_FILE_BASENAMES: return True
    return any(rx.match(lowered) for rx in TEST_FILE_REGEXES)


# =============================================================================
# HIERARCHICAL SIGNAL DETECTOR
# Fixes applied:
#   FIX 1 — Framework gates relaxed; decorator+DI patterns added
#   FIX 2 — Library uses export concentration not raw export ratio
#   FIX 3 — Package.json fallback when all file-walk signals < 1.0
#   FIX 4 — Classifier rebalanced so library doesn't dominate
#   FIX 5 — Application strengthened with entry point + private field
# =============================================================================

class HierarchicalSignalDetector:

    def __init__(self, repo_path):
        self.repo_path = repo_path
        self.signals   = {}
        self.features  = {}

    def _iter_code_files(self):
        skip = {"node_modules",".git","dist","build","test","tests",
                "spec","specs","__tests__","__mocks__","coverage",
                ".next",".nuxt","out",".cache"}
        for root, dirs, files in os.walk(self.repo_path):
            dirs[:] = [d for d in dirs if d.lower() not in skip]
            for f in files:
                if f.endswith((".js",".ts",".jsx",".tsx")):
                    yield root, f

    def _read(self, filepath):
        try:
            return Path(filepath).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""

    def _load_pkg(self):
        pkg_path = os.path.join(self.repo_path, "package.json")
        if not os.path.exists(pkg_path):
            return {}
        try:
            with open(pkg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    # ── FIX 3: Package.json fallback ─────────────────────────────────────────

    def _pkg_fallback_signals(self):
        pkg      = self._load_pkg()
        fallback = {t: 0.0 for t in ["application","library","framework","cli","plugin"]}
        if not pkg:
            return fallback

        if "bin" in pkg:
            fallback["cli"] += 4.0

        peer = pkg.get("peerDependencies", {}) or {}
        if len(peer) >= 2:
            fallback["library"] += 2.5

        if any(k in pkg for k in ["main","module","exports"]):
            fallback["library"] += 2.0

        keywords = [k.lower() for k in pkg.get("keywords", [])]
        kw       = " ".join(keywords)
        if any(k in kw for k in ["plugin","extension","adapter","preset"]):   fallback["plugin"]      += 3.0
        if any(k in kw for k in ["framework","scaffolding","boilerplate"]):    fallback["framework"]   += 2.5
        if any(k in kw for k in ["cli","command","terminal","shell"]):         fallback["cli"]         += 2.5
        if any(k in kw for k in ["utility","utilities","helper","toolkit"]):   fallback["library"]     += 2.0
        if any(k in kw for k in ["app","application","dashboard","saas"]):     fallback["application"] += 2.0

        deps    = pkg.get("dependencies",    {}) or {}
        dev     = pkg.get("devDependencies", {}) or {}
        runtime = len(deps)
        devdeps = len(dev)
        if runtime > devdeps * 1.5: fallback["application"] += 1.5
        elif devdeps > runtime * 1.5: fallback["library"]   += 1.0

        if pkg.get("private", False):
            fallback["application"] += 2.5
            fallback["library"]     -= 1.5

        return fallback

    # ── SIGNAL: CLI ───────────────────────────────────────────────────────────

    def detect_cli_entry(self):
        pkg     = self._load_pkg()
        has_bin = "bin" in pkg
        scripts = pkg.get("scripts", {})
        script_blob = " ".join(str(v).lower() for v in scripts.values())
        has_cli_scripts = any(k in script_blob for k in ["node ","ts-node","bin/"])

        arg_p = argv = flow = total = 0
        for root, f in self._iter_code_files():
            total += 1
            content = self._read(os.path.join(root, f))
            if re.search(r"(yargs|commander|minimist|meow|cac|oclif|clipanion)\b", content):       arg_p += 1
            if re.search(r"process\.argv", content):                                                argv  += 1
            if re.search(r"(program\.command\(|\.parse\(\s*process\.argv|yargs\(|command\()", content): flow += 1

        strength = 0.0
        if has_bin:        strength += 3.5
        if has_cli_scripts: strength += 1.2
        if total > 0:
            strength += safe_divide(arg_p, total) * 2.0
            strength += safe_divide(argv,  total) * 1.4
            strength += safe_divide(flow,  total) * 1.6

        self.features["cli"] = {
            "has_bin_field":      has_bin,
            "arg_parsing_count":  arg_p,
            "argv_count":         argv,
            "command_flow_count": flow,
            "total_files":        total,
        }
        self.signals["cli_entry"] = clamp(strength, 0, 7)
        return self.signals["cli_entry"]

    # ── SIGNAL: PLUGIN ────────────────────────────────────────────────────────

    def detect_plugin_pattern(self):
        plugin_pats = [
            r"(extends|implements)\s+(Plugin|Extension|Adapter)",
            r"(plugin|extension|adapter|hook)\.register\(",
            r"\.registerPlugin\(|\.addExtension\(|\.installAdapter\(",
            r"\bcreatePlugin\(",
            r"\bwithPlugin\(",
        ]
        host_re = re.compile(
            r"(eslint|vite|rollup|webpack|babel|remark|rehype|postcss|gatsby|nuxt)"
            r"(\.config|plugin\()", re.IGNORECASE
        )

        matched = host = total = 0
        for root, f in self._iter_code_files():
            total  += 1
            content = self._read(os.path.join(root, f))
            if any(re.search(p, content, re.IGNORECASE) for p in plugin_pats): matched += 1
            if host_re.search(content):                                         host    += 1

        if total == 0:
            self.features["plugin"] = {}
            self.signals["plugin"]  = 0.0
            return 0.0

        strength = safe_divide(matched, total) * 4.0 + safe_divide(host, total) * 2.0
        self.features["plugin"] = {"matched": matched, "host_integration": host, "total_files": total}
        self.signals["plugin"]  = clamp(strength, 0, 6)
        return self.signals["plugin"]

    # ── SIGNAL: FRAMEWORK ────────────────────────────────────────────────────
    # FIX 1: Added decorator / DI / module patterns for nestjs, angular, next.js

    def detect_framework_ownership(self):
        decorator_pats = [
            r"@(Module|Injectable|Controller|Component|Directive|Pipe|Guard|Interceptor)\b",
            r"@(Get|Post|Put|Delete|Patch|UseGuards|UseInterceptors)\b",
            r"@(NgModule|Component|Directive|Pipe|Injectable)\b",
        ]
        di_pats = [
            r"(Inject|provide|inject|forRoot|forChild|createModule|DynamicModule)",
            r"(container\.bind|container\.get|Container\b|Injector\b)",
            r"(Provider|ValueProvider|ClassProvider|FactoryProvider)\b",
        ]
        lifecycle_pats = [
            r"(onModuleInit|onModuleDestroy|onApplicationBootstrap|onApplicationShutdown)",
            r"(ngOnInit|ngOnDestroy|ngOnChanges|ngAfterViewInit|ngAfterContentInit)",
            r"(getInitialProps|getServerSideProps|getStaticProps|getStaticPaths)\b",
            r"(initialize|bootstrap|setup|configure)\s*\([^)]*\)\s*\{",
        ]
        module_pats = [
            r"(createApp|bootstrap|NestFactory|platformBrowserDynamic)\(",
            r"(Module|App|Server)\s*\.\s*(create|bootstrap|register|init)\(",
            r"app\.(use|get|post|set|register|decorate)\(",
        ]

        dec = di = life = mod = total = 0
        for root, f in self._iter_code_files():
            total  += 1
            content = self._read(os.path.join(root, f))
            if any(re.search(p, content) for p in decorator_pats):                dec  += 1
            if any(re.search(p, content, re.IGNORECASE) for p in di_pats):        di   += 1
            if any(re.search(p, content, re.IGNORECASE) for p in lifecycle_pats): life += 1
            if any(re.search(p, content, re.IGNORECASE) for p in module_pats):    mod  += 1

        if total == 0:
            self.features["framework"] = {}
            self.signals["framework"]  = 0.0
            return 0.0

        dec_r  = safe_divide(dec,  total)
        di_r   = safe_divide(di,   total)
        life_r = safe_divide(life, total)
        mod_r  = safe_divide(mod,  total)

        strength = dec_r*4.5 + di_r*3.0 + life_r*2.5 + mod_r*2.0

        self.features["framework"] = {
            "decorator_ratio":  dec_r,
            "di_ratio":         di_r,
            "lifecycle_ratio":  life_r,
            "module_ratio":     mod_r,
            "total_files":      total,
        }
        self.signals["framework"] = clamp(strength, 0, 8.0)
        return self.signals["framework"]

    # ── SIGNAL: LIBRARY ───────────────────────────────────────────────────────
    # FIX 2: Uses export CONCENTRATION not raw ratio; penalizes orchestration

    def detect_library_independence(self):
        total         = 0
        export_counts = {}
        orch_hits     = 0
        graph         = defaultdict(set)

        orch_pats = [
            r"\bserver\.listen\(", r"\bapp\.listen\(",
            r"\bcreateServer\(",   r"\bapp\.start\(",
            r"\blisten\(\s*\d+",   r"process\.on\(['\"]SIGINT",
        ]

        for root, f in self._iter_code_files():
            total   += 1
            filepath = os.path.join(root, f)
            rel      = normalize(os.path.relpath(filepath, self.repo_path))
            content  = self._read(filepath)

            cnt = len(re.findall(r'\bexport\b', content))
            if cnt > 0:
                export_counts[rel] = cnt

            if any(re.search(p, content) for p in orch_pats):
                orch_hits += 1

            for pat in [
                re.compile(r"from\s+['\"]([^'\"]+)['\"]"),
                re.compile(r"require\s*\(\s*['\"]([^'\"]+)['\"]\s*\)"),
            ]:
                for m in pat.finditer(content):
                    imp = m.group(1)
                    if imp.startswith('.'):
                        graph[rel].add(imp)

        if total == 0:
            self.features["library"] = {}
            self.signals["library"]  = 0.0
            return 0.0

        total_exports    = sum(export_counts.values())
        num_export_files = len(export_counts)

        if total_exports > 0 and num_export_files > 0:
            top_exports       = max(export_counts.values())
            concentration     = safe_divide(top_exports, total_exports)
            exports_per_file  = safe_divide(total_exports, num_export_files)
            concentration_score = concentration * min(1.0, exports_per_file / 5.0)
        else:
            concentration_score = 0.0

        total_deps   = sum(len(d) for d in graph.values())
        avg_deps     = safe_divide(total_deps, total)
        coupling     = clamp(1.0 - (avg_deps / 4.0), 0, 1)
        orch_ratio   = safe_divide(orch_hits, total)

        entry_files  = ["server.ts","server.js","app.ts","app.js","main.ts","main.js",
                        "src/server.ts","src/server.js","src/app.ts","src/app.js",
                        "src/main.ts","src/main.js"]
        has_entry    = any(os.path.exists(os.path.join(self.repo_path, e)) for e in entry_files)

        strength = (concentration_score * 3.5) + \
                   (coupling            * 1.5) - \
                   (orch_ratio          * 3.0) - \
                   (1.5 if has_entry else 0.0)

        self.features["library"] = {
            "concentration_score": concentration_score,
            "coupling_score":      coupling,
            "orchestration_ratio": orch_ratio,
            "has_entry_point":     has_entry,
            "total_files":         total,
        }
        self.signals["library"] = clamp(strength, 0, 6.5)
        return self.signals["library"]

    # ── SIGNAL: APPLICATION ───────────────────────────────────────────────────
    # FIX 5: Strengthened with entry point hits + private field

    def detect_application_structure(self):
        app_dirs = {"routes","pages","services","components","controllers",
                    "models","views","features","screens","store","context",
                    "middleware","handlers","resolvers","subscribers"}

        found_dirs = set()
        max_depth  = 0

        for root, dirs, _ in os.walk(self.repo_path):
            if any(p in root.lower() for p in ["node_modules",".git","dist","build"]):
                continue
            found_dirs.update(d.lower() for d in dirs)
            rel   = os.path.relpath(root, self.repo_path)
            depth = len([p for p in rel.split(os.sep) if p and p != "."])
            max_depth = max(max_depth, depth)

        domain_count = len(found_dirs & app_dirs)
        depth_signal = clamp(sigmoid(max_depth - 2.5), 0, 1)

        entry_files  = ["server.ts","server.js","app.ts","app.js","main.ts","main.js",
                        "src/server.ts","src/server.js","src/app.ts","src/app.js",
                        "src/main.ts","src/main.js","index.ts","index.js",
                        "src/index.ts","src/index.js"]
        entry_hits   = sum(1 for e in entry_files if os.path.exists(os.path.join(self.repo_path, e)))

        pkg     = self._load_pkg()
        private = pkg.get("private", False)

        strength = (domain_count    * 1.2) + \
                   (depth_signal    * 1.0) + \
                   (min(entry_hits, 3) * 0.8) + \
                   (2.0 if private else 0.0)

        self.features["application"] = {
            "domain_count": domain_count,
            "max_depth":    max_depth,
            "entry_hits":   entry_hits,
            "private":      private,
        }
        self.signals["application"] = clamp(strength, 0, 6.0)
        return self.signals["application"]

    # ── ANALYZE ALL ───────────────────────────────────────────────────────────

    def analyze_all(self):
        self.detect_cli_entry()
        self.detect_plugin_pattern()
        self.detect_framework_ownership()
        self.detect_library_independence()
        self.detect_application_structure()

        # FIX 1: Relaxed gates
        cli = self.features.get("cli", {})
        if not (cli.get("has_bin_field",False) or
                cli.get("command_flow_count",0) >= 1 or
                cli.get("arg_parsing_count", 0) >= 1):
            self.signals["cli_entry"] = 0.0

        pl = self.features.get("plugin", {})
        if not (pl.get("matched",0) >= 1 or pl.get("host_integration",0) >= 1):
            self.signals["plugin"] = 0.0

        fw = self.features.get("framework", {})
        has_fw = (fw.get("decorator_ratio", 0) >= 0.02 or
                  fw.get("di_ratio",        0) >= 0.05 or
                  fw.get("lifecycle_ratio", 0) >= 0.05 or
                  fw.get("module_ratio",    0) >= 0.05)
        if not has_fw:
            self.signals["framework"] = 0.0

        # FIX 3: Fallback when all signals weak
        max_signal = max(self.signals.values()) if self.signals else 0.0
        if max_signal < 1.0:
            fallback = self._pkg_fallback_signals()
            for t, score in fallback.items():
                key = "cli_entry" if t == "cli" else t
                if score > self.signals.get(key, 0.0):
                    self.signals[key] = score

        return self.signals


# =============================================================================
# MULTI-TOOL RUNNERS
# =============================================================================

class MultiToolAnalyzer:
    def __init__(self, repo_path):
        self.repo_path     = repo_path
        self.tools_run     = []
        self.tools_success = []
        self.results       = {}

    def run_knip(self):
        try:
            raw, err, code = run_cmd("npx knip --reporter json", cwd=self.repo_path, timeout=180)
            self.tools_run.append("knip")
            if not raw or code != 0: return None
            data = json.loads(raw)
            self.tools_success.append("knip")
            return data
        except Exception:
            return None

    def run_depcheck(self):
        try:
            chk, _, _ = run_cmd("npx depcheck --version", cwd=self.repo_path, timeout=10)
            if not chk: return None
            raw, _, _ = run_cmd("npx depcheck --json", cwd=self.repo_path, timeout=60)
            self.tools_run.append("depcheck")
            if not raw: return None
            data = json.loads(raw)
            self.tools_success.append("depcheck")
            return data
        except Exception:
            return None

    def run_madge(self):
        try:
            chk, _, _ = run_cmd("npx madge --version", cwd=self.repo_path, timeout=10)
            if not chk: return None
            raw, _, _ = run_cmd(
                "npx madge --json src 2>/dev/null || npx madge --json . 2>/dev/null || echo '{}'",
                cwd=self.repo_path, timeout=60
            )
            self.tools_run.append("madge")
            if not raw: return None
            data = json.loads(raw)
            self.tools_success.append("madge")
            return data
        except Exception:
            return None

    def run_ts_prune(self):
        try:
            pkg_path = os.path.join(self.repo_path, "package.json")
            if not os.path.exists(pkg_path): return None
            with open(pkg_path, "r", encoding="utf-8") as f:
                pkg = json.load(f)
            all_deps = {**pkg.get("dependencies",{}), **pkg.get("devDependencies",{})}
            if "typescript" not in all_deps: return None
            chk, _, _ = run_cmd("npx ts-prune --version", cwd=self.repo_path, timeout=10)
            if not chk: return None
            raw, _, _ = run_cmd("npx ts-prune", cwd=self.repo_path, timeout=60)
            self.tools_run.append("ts-prune")
            if not raw: return None
            unused = []
            for line in raw.split("\n"):
                line = line.strip()
                if line and " - " in line:
                    parts = line.split(" - ", 1)
                    if len(parts) == 2 and ":" in parts[0]:
                        unused.append((parts[0].split(":")[0], parts[1].strip()))
            self.tools_success.append("ts-prune")
            return {"unused": unused} if unused else None
        except Exception:
            return None

    def run_all(self):
        if os.path.exists(os.path.join(self.repo_path, "package.json")):
            run_cmd("npm install --ignore-scripts --prefer-offline", cwd=self.repo_path, timeout=120)
        self.results["knip"]     = self.run_knip()
        self.results["depcheck"] = self.run_depcheck()
        self.results["madge"]    = self.run_madge()
        self.results["ts_prune"] = self.run_ts_prune()
        return self.results


# =============================================================================
# EVIDENCE AGGREGATION
# =============================================================================

class EvidenceAggregator:
    def __init__(self, tools_results, repo_path):
        self.tools_results = tools_results
        self.repo_path     = repo_path

    def aggregate_unused_symbols(self):
        exports    = defaultdict(set)
        tool_count = 0
        if self.tools_results.get("knip"):
            tool_count += 1
            for issue in self.tools_results["knip"].get("issues", []):
                for exp in issue.get("exports", []):
                    fp  = normalize(exp.get("file",""))
                    sym = exp.get("name") or exp.get("symbol","")
                    if fp and sym and not is_test_path(fp):
                        exports[(fp, sym)].add("knip")
        if self.tools_results.get("ts_prune"):
            tool_count += 1
            for fp, sym in self.tools_results["ts_prune"].get("unused",[]):
                fp = normalize(fp)
                if fp and sym and not is_test_path(fp):
                    exports[(fp, sym)].add("ts-prune")
        agreement = {k: len(v)/max(1,tool_count) for k,v in exports.items()}
        return dict(exports), agreement, tool_count > 0

    def aggregate_unused_files(self):
        files      = defaultdict(set)
        tool_count = 0
        if self.tools_results.get("knip"):
            tool_count += 1
            for issue in self.tools_results["knip"].get("issues",[]):
                if issue.get("type") == "unused-file":
                    fp = normalize(issue.get("file",""))
                    if fp and not is_test_path(fp):
                        files[fp].add("knip")
        if self.tools_results.get("madge"):
            tool_count += 1
            madge_data = self.tools_results["madge"]
            if isinstance(madge_data, dict):
                for module, deps in madge_data.items():
                    if not deps:
                        fp = normalize(module)
                        if fp and not is_test_path(fp):
                            files[fp].add("madge")
        agreement = {k: len(v)/max(1,tool_count) for k,v in files.items()}
        return dict(files), agreement, tool_count > 0

    def aggregate_unused_dependencies(self):
        deps       = defaultdict(set)
        tool_count = 0
        if self.tools_results.get("knip"):
            tool_count += 1
            for issue in self.tools_results["knip"].get("issues",[]):
                for d in issue.get("dependencies",[]) + issue.get("devDependencies",[]):
                    name = d.get("name") or d.get("symbol","")
                    if name: deps[name].add("knip")
        if self.tools_results.get("depcheck"):
            tool_count += 1
            for name in self.tools_results["depcheck"].get("dependencies",[]):
                if name: deps[name].add("depcheck")
        agreement = {k: len(v)/max(1,tool_count) for k,v in deps.items()}
        return dict(deps), agreement, tool_count > 0


# =============================================================================
# HIERARCHICAL CLASSIFICATION
# FIX 4: Rebalanced — library no longer gets unconditional score
# =============================================================================

REPO_TYPES = ["application","library","framework","cli","plugin"]

REPO_TYPE_MODIFIERS = {
    "library":     {"unusedExport":0.3,  "unusedFile":0.8,  "unusedDependency":1.0},
    "application": {"unusedExport":0.8,  "unusedFile":1.0,  "unusedDependency":1.0},
    "framework":   {"unusedExport":0.5,  "unusedFile":0.6,  "unusedDependency":0.9},
    "cli":         {"unusedExport":0.6,  "unusedFile":0.9,  "unusedDependency":1.0},
    "plugin":      {"unusedExport":0.4,  "unusedFile":0.7,  "unusedDependency":0.9},
}


def ensure_repo_probabilities(repo_probs):
    if not repo_probs:
        u = 1.0/len(REPO_TYPES)
        return {t: u for t in REPO_TYPES}
    cleaned = {}
    for t in REPO_TYPES:
        try:   v = float(repo_probs.get(t, 0.0))
        except: v = 0.0
        cleaned[t] = max(0.0, v)
    total = sum(cleaned.values())
    if total <= 0:
        u = 1.0/len(REPO_TYPES)
        return {t: u for t in REPO_TYPES}
    return {t: cleaned[t]/total for t in REPO_TYPES}


def classify_repo_type(strong_signals):
    scores = {t: 0.0 for t in REPO_TYPES}

    cli_s  = strong_signals.get("cli_entry",   0.0)
    plug_s = strong_signals.get("plugin",      0.0)
    fw_s   = strong_signals.get("framework",   0.0)
    lib_s  = strong_signals.get("library",     0.0)
    app_s  = strong_signals.get("application", 0.0)

    # CLI
    if cli_s >= 1.5:
        scores["cli"] += cli_s * 3.5
        scores["application"] *= 0.2
        scores["framework"]   *= 0.25

    # Plugin
    if plug_s >= 1.2 and cli_s < 1.5:
        scores["plugin"] += plug_s * 2.8
        scores["application"] *= 0.3

    # Framework
    if fw_s >= 0.5:
        scores["framework"] += fw_s * 3.2
        scores["application"] *= 0.3
        # FIX 4: meta-frameworks are also library-shaped, partial suppression only
        scores["library"] *= (0.5 if fw_s >= 2.5 else 0.75)

    # Library — only scores when genuinely independent of competing signals
    if lib_s >= 0.8:
        competing = max(cli_s, plug_s, fw_s, app_s)
        lib_effective = lib_s * (0.5 if competing > lib_s else 1.0)
        scores["library"] += lib_effective * 2.2

    # Application
    if app_s >= 0.8:
        competing = max(cli_s, plug_s, fw_s)
        scores["application"] += app_s * (2.0 if competing < 1.0 else 0.9)

    max_signal = max(cli_s, plug_s, fw_s, lib_s, app_s)
    if max_signal >= 4.0:   temperature = 0.5
    elif max_signal >= 2.0: temperature = 0.85
    elif max_signal >= 1.0: temperature = 1.3
    else:                   temperature = 2.0

    probs = robust_softmax(scores, temperature=temperature, epsilon=1e-6)
    probs = ensure_repo_probabilities(probs)
    return scores, probs


def make_repo_type_decision(probs, detection_reliability, analysis_state):
    probs = ensure_repo_probabilities(probs)

    if analysis_state.is_failed():
        return {
            "type":"unknown","confidence":0.0,
            "probabilities":{k:round(v,4) for k,v in probs.items()},
            "separation":0.0,"entropy":0.0,
            "reason":"Insufficient analysis signals"
        }

    entropy    = compute_normalized_entropy(probs)
    separation = compute_separation(probs)
    top_type   = max(probs, key=probs.get)
    top_prob   = probs[top_type]

    if analysis_state.is_partial():
        SEP_T=0.14; ENT_T=0.75; REL_T=0.30; CONF_T=0.28
    else:
        SEP_T=0.20; ENT_T=0.62; REL_T=0.45; CONF_T=0.40

    if detection_reliability < REL_T:
        return {"type":"uncertain","confidence":round(detection_reliability,4),
                "probabilities":{k:round(v,4) for k,v in probs.items()},
                "separation":round(separation,4),"entropy":round(entropy,4),
                "reason":"Detection reliability too low"}

    if top_prob < CONF_T:
        return {"type":"uncertain","confidence":round(top_prob,4),
                "probabilities":{k:round(v,4) for k,v in probs.items()},
                "separation":round(separation,4),"entropy":round(entropy,4),
                "reason":"No class achieves minimum confidence"}

    if entropy > ENT_T:
        return {"type":"uncertain","confidence":round(top_prob,4),
                "probabilities":{k:round(v,4) for k,v in probs.items()},
                "separation":round(separation,4),"entropy":round(entropy,4),
                "reason":"Distribution too flat"}

    if separation < SEP_T:
        return {"type":"uncertain","confidence":round(top_prob,4),
                "probabilities":{k:round(v,4) for k,v in probs.items()},
                "separation":round(separation,4),"entropy":round(entropy,4),
                "reason":"Insufficient separation between classes"}

    final_confidence = clamp(
        top_prob * (0.65 + 0.55*separation) * (1.0 - 0.85*entropy) *
        detection_reliability * 0.65,
        0, 0.88
    )

    return {
        "type":          top_type,
        "confidence":    round(final_confidence, 4),
        "probabilities": {k: round(v,4) for k,v in probs.items()},
        "separation":    round(separation, 4),
        "entropy":       round(entropy, 4),
        "reason":        None
    }


def expected_repo_modifier(repo_probs, item_type):
    rp = ensure_repo_probabilities(repo_probs)
    return sum(rp[t] * REPO_TYPE_MODIFIERS[t][item_type] for t in REPO_TYPES)


# =============================================================================
# CONFIDENCE & SCORING
# =============================================================================

WEIGHTS        = {"w1":3.0,"w2":2.0,"w3":3.5,"w4":4.0,"w5":4.5,"w6":2.5}
BASE_SEVERITY  = {"unusedFile":1.0,"unusedDependency":1.0,"unusedExport":0.7}
PENALTY_WEIGHT = {"unusedFile":2.0,"unusedDependency":2.0,"unusedExport":1.0}
DEPENDENCY_MODIFIERS = {"runtime":1.0,"optional":0.6,"tooling":0.5,"example":0.4}


def heuristic_feature_scores(item_type, path_or_name):
    x = normalize(path_or_name).lower()
    r=0.7; u=0.7; reach=0.7; dyn=0.1; ctx=0.1; eco=0.1
    if item_type == "unusedExport":
        if any(k in x for k in ["/index.","/lib/","/api/","/exports","/utils"]):
            ctx+=0.5; eco+=0.2
        if any(k in x for k in ["/internal/","/private/"]):
            r+=0.2; u+=0.2; ctx=max(0,ctx-0.1)
    if item_type == "unusedFile":
        if any(k in x for k in ["/core/","/src/core/","/server/","/runtime/"]):
            reach+=0.25
        if any(k in x for k in ["/utils/","/helpers/"]):
            u=max(0,u-0.15)
    if item_type == "unusedDependency":
        if any(k in x for k in ["babel","webpack","vite","eslint","prettier","jest","vitest"]):
            eco+=0.2
    return (clamp(r,0,1),clamp(u,0,1),clamp(reach,0,1),
            clamp(dyn,0,1),clamp(ctx,0,1),clamp(eco,0,1))


def classify_dependency_context(dep_name: str) -> str:
    d = (dep_name or "").lower()
    if d in {"eslint","prettier","jest","vitest","babel","webpack","vite","rollup","parcel"}:
        return "tooling"
    if d in {"morgan","ejs","hbs","express-session","connect-redis"}:
        return "optional"
    if "example" in d or "demo" in d:
        return "example"
    return "runtime"


def detect_usage_context(repo_path):
    paths = []
    for root, dirs, _ in os.walk(repo_path):
        for d in dirs:
            paths.append(os.path.join(root, d).lower())
    return {
        "has_examples":   any("example" in p or "demo" in p for p in paths),
        "has_docs":       any("doc" in p for p in paths),
        "has_playground": any("playground" in p for p in paths),
    }


def compute_evidence_factor(item_type, repo_probs, dependency_type=None, context=None):
    factor  = 1.0
    context = context or {}
    rp      = ensure_repo_probabilities(repo_probs)
    if rp.get("library",0) > 0.6:    factor *= 0.82
    if item_type == "unusedDependency": factor *= 0.85
    if dependency_type == "optional":   factor *= 0.75
    if context.get("has_examples") or context.get("has_docs"):
        if item_type == "unusedDependency": factor *= 0.80
    return clamp(factor, 0.5, 1.5)


def compute_detection_reliability(summary, repo_probs, tools_successful, analysis_state):
    total       = summary.get("total", 0)
    reliability = 1.0
    rp          = ensure_repo_probabilities(repo_probs)
    if total == 0:                          reliability *= 0.75
    if rp.get("library",  0) > 0.65:       reliability *= 0.92
    if rp.get("framework",0) > 0.50:       reliability *= 0.85
    if len(tools_successful) >= 3:          reliability *= 1.18
    elif len(tools_successful) >= 2:        reliability *= 1.08
    reliability *= analysis_state.get_reliability_multiplier()
    return clamp(reliability, 0.0, 1.0)


def base_confidence(item_type, path_or_name):
    r,u,reach,dyn,ctx,eco = heuristic_feature_scores(item_type, path_or_name)
    s = WEIGHTS["w1"]*r + WEIGHTS["w2"]*u + WEIGHTS["w3"]*reach \
      - WEIGHTS["w4"]*dyn - WEIGHTS["w5"]*ctx - WEIGHTS["w6"]*eco
    return sigmoid(s)


def classify_confidence(c):
    if c >= 0.75: return "high"
    if c >= 0.45: return "medium"
    return "low"


def item_score(confidence, item_type, impact=1.0, context_factor=1.0):
    return 100.0 * confidence * BASE_SEVERITY[item_type] * impact * context_factor


# =============================================================================
# MAIN SCAN
# =============================================================================

def scan_repo(repo_path):
    if not os.path.exists(repo_path):
        default_probs = {t: round(1.0/len(REPO_TYPES),4) for t in REPO_TYPES}
        return {
            "error": "repo path not found",
            "repoType": {"type":"unknown","confidence":0.0,
                         "probabilities":default_probs,
                         "separation":0.0,"entropy":0.0,
                         "reason":"Repository path does not exist"}
        }

    analysis_state = AnalysisState()

    try:
        signal_detector = HierarchicalSignalDetector(repo_path)
        strong_signals  = signal_detector.analyze_all()

        analyzer      = MultiToolAnalyzer(repo_path)
        tools_results = analyzer.run_all()

        aggregator = EvidenceAggregator(tools_results, repo_path)
        evidence_symbols, symbol_agreement, has_symbol_data = aggregator.aggregate_unused_symbols()
        evidence_files,   file_agreement,   has_file_data   = aggregator.aggregate_unused_files()
        evidence_deps,    dep_agreement,    has_dep_data    = aggregator.aggregate_unused_dependencies()

        if tools_results.get("knip"):
            analysis_state.add_signal_category("symbol_analysis")
        else:
            analysis_state.mark_missing_category("symbol_analysis")

        if has_symbol_data: analysis_state.add_signal_category("symbol_analysis")
        if has_file_data:   analysis_state.add_signal_category("file_analysis")
        if has_dep_data:    analysis_state.add_signal_category("dependency_analysis")
        analysis_state.add_signal_category("structure_analysis")
        analysis_state.add_signal_category("tool_coverage")

        has_findings = (len(evidence_files)+len(evidence_symbols)+len(evidence_deps)) > 0
        analysis_state.finalize(has_findings)

        if analysis_state.is_failed():
            default_probs = {t: round(1.0/len(REPO_TYPES),4) for t in REPO_TYPES}
            return {
                "status":"failed","error":"Insufficient analysis signals",
                "notes":analysis_state.notes,
                "repoType":{"type":"unknown","confidence":0.0,"probabilities":default_probs,
                            "separation":0.0,"entropy":0.0,"reason":"Insufficient analysis signals"},
                "toolsRun":analyzer.tools_run,"toolsSuccess":analyzer.tools_success,
            }

        repo_scores, repo_probs = classify_repo_type(strong_signals)
        repo_probs = ensure_repo_probabilities(repo_probs)

        summary = {
            "files":   len(evidence_files),
            "exports": len(evidence_symbols),
            "deps":    len(evidence_deps),
            "total":   len(evidence_files)+len(evidence_symbols)+len(evidence_deps),
        }

        detection_reliability = compute_detection_reliability(
            summary, repo_probs, analyzer.tools_success, analysis_state
        )
        decision = make_repo_type_decision(repo_probs, detection_reliability, analysis_state)

        if "probabilities" not in decision or not decision["probabilities"]:
            decision["probabilities"] = {k: round(v,4) for k,v in repo_probs.items()}

        usage_context         = detect_usage_context(repo_path)
        confidence_multiplier = analysis_state.get_confidence_multiplier()

        unusedFiles, unusedExports, unusedDeps, all_items = [], [], [], []

        for filepath in evidence_files:
            bc  = base_confidence("unusedFile", filepath)
            mod = expected_repo_modifier(repo_probs, "unusedFile")
            ag  = file_agreement.get(filepath, 0)
            ag_boost = 1.0 + (ag - 1.0/3)*0.2 if ag > 0 else 0.88
            fc  = clamp(bc*mod*ag_boost*confidence_multiplier, 0, 1)
            row = {"file":filepath,"type":"unusedFile",
                   "baseConfidence":round(bc,4),"repoTypeModifier":round(mod,4),
                   "toolAgreement":round(ag,4),"finalConfidence":round(fc,4),
                   "confidenceLabel":classify_confidence(fc),"score":round(item_score(fc,"unusedFile"),2)}
            unusedFiles.append(row); all_items.append(row)

        for (filepath, symbol), tools in evidence_symbols.items():
            bc  = base_confidence("unusedExport", f"{filepath}::{symbol}")
            mod = expected_repo_modifier(repo_probs, "unusedExport")
            ag  = symbol_agreement.get((filepath, symbol), 0)
            ag_boost = 1.0 + (ag-0.5)*0.2 if ag > 0 else 0.88
            fc  = clamp(bc*mod*ag_boost*confidence_multiplier, 0, 1)
            row = {"file":filepath,"name":symbol,"type":"unusedExport",
                   "baseConfidence":round(bc,4),"repoTypeModifier":round(mod,4),
                   "toolAgreement":round(ag,4),"finalConfidence":round(fc,4),
                   "confidenceLabel":classify_confidence(fc),"score":round(item_score(fc,"unusedExport"),2)}
            unusedExports.append(row); all_items.append(row)

        for dep_name in evidence_deps:
            bc       = base_confidence("unusedDependency", dep_name)
            mod      = expected_repo_modifier(repo_probs, "unusedDependency")
            dep_type = classify_dependency_context(dep_name)
            dep_mod  = DEPENDENCY_MODIFIERS[dep_type]
            ev       = compute_evidence_factor("unusedDependency", repo_probs, dep_type, usage_context)
            ag       = dep_agreement.get(dep_name, 0)
            ag_boost = 1.0 + (ag-0.5)*0.2 if ag > 0 else 0.88
            fc       = clamp(bc*mod*dep_mod*ev*ag_boost*confidence_multiplier, 0, 1)
            row = {"name":dep_name,"type":"unusedDependency",
                   "dependencyType":dep_type,"dependencyModifier":dep_mod,
                   "evidenceFactor":round(ev,4),"baseConfidence":round(bc,4),
                   "repoTypeModifier":round(mod,4),"toolAgreement":round(ag,4),
                   "finalConfidence":round(fc,4),"confidenceLabel":classify_confidence(fc),
                   "score":round(item_score(fc,"unusedDependency"),2)}
            unusedDeps.append(row); all_items.append(row)

        repo_penalty       = sum(PENALTY_WEIGHT[i["type"]]*i["finalConfidence"] for i in all_items)
        actionable_penalty = sum(PENALTY_WEIGHT[i["type"]]*i["finalConfidence"]
                                 for i in all_items if i["finalConfidence"] >= 0.45)
        overall    = round(max(0.0, 100.0-(repo_penalty+(1.0-detection_reliability)*10.0)), 2)
        actionable = round(max(0.0, 100.0-actionable_penalty), 2)

        counts = defaultdict(int)
        for i in all_items: counts[i["confidenceLabel"]] += 1

        if summary["total"] == 0:
            analysis = {
                "status":  "no_unused_code" if detection_reliability >= 0.5 else "low_reliability",
                "message": "No unused code detected" if detection_reliability >= 0.5
                           else "Unable to reliably detect unused code"
            }
        else:
            analysis = {"status":"unused_code_detected","message":"Unused code found with computed confidence"}

        return {
            "status":        analysis_state.state,
            "repoType":      decision,
            "repoTypeScores":{k: round(v,4) for k,v in repo_scores.items()},
            "unusedFiles":   unusedFiles,
            "unusedExports": unusedExports,
            "unusedDeps":    unusedDeps,
            "summary":       summary,
            "scores": {
                "repoPenalty":          round(repo_penalty, 4),
                "overall":              overall,
                "actionable":           actionable,
                "countsByConfidence":   {"high":counts["high"],"medium":counts["medium"],"low":counts["low"]},
                "detectionReliability": round(detection_reliability, 4),
            },
            "analysis": analysis,
            "debug": {
                "analysisState":  {"state":analysis_state.state,"notes":analysis_state.notes},
                "strongSignals":  {k: round(v,4) for k,v in strong_signals.items()},
                "distribution":   {
                    "entropy":    round(compute_normalized_entropy(decision["probabilities"]),4),
                    "separation": round(compute_separation(decision["probabilities"]),4),
                },
                "toolsRun":    analyzer.tools_run,
                "toolsSuccess":analyzer.tools_success,
            }
        }

    except Exception as e:
        import traceback
        default_probs = {t: round(1.0/len(REPO_TYPES),4) for t in REPO_TYPES}
        return {
            "status":"error","error":str(e),"trace":traceback.format_exc(),
            "repoType":{"type":"unknown","confidence":0.0,"probabilities":default_probs,
                        "separation":0.0,"entropy":0.0,"reason":"Error during analysis"}
        }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "repo path required"}))
        sys.exit(1)
    result = scan_repo(sys.argv[1])
    print(json.dumps(result, indent=2))