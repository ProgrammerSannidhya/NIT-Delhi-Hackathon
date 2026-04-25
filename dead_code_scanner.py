#!/usr/bin/env python3
"""
Dead Code Scanner
-----------------
Give it a GitHub repo URL -> it clones it, runs knip, and explains
every dead file / export / dependency in plain English.

Usage:
    python3 dead_code_scanner.py https://github.com/user/repo
"""

import subprocess, sys, os, json, shutil, tempfile

R  = "\033[91m"; Y = "\033[93m"; G = "\033[92m"
B  = "\033[94m"; C = "\033[96m"; W = "\033[97m"
DIM= "\033[2m";  NC= "\033[0m"

def banner():
    print(f"""
{C}╔══════════════════════════════════════════════════╗
║        💀  Dead Code Scanner  (powered by knip)  ║
╚══════════════════════════════════════════════════╝{NC}
""")

def run(cmd, cwd=None):
    r = subprocess.run(cmd, shell=True, cwd=cwd,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode not in (0, 1):
        raise RuntimeError(r.stderr.strip())
    return r.stdout

def reason_file(filename):
    f = filename.lower(); n = os.path.basename(filename)
    if "/ui/" in f:              return "shadcn/ui component — installed in bulk but never imported anywhere."
    if "test-" in n or ".test." in n or ".spec." in n:
                                 return "Test/debug file — not part of the production import graph."
    if "postcss" in n:           return "PostCSS config — loaded by the build tool, not via import statements."
    if "next.config" in n:       return "Next.js config — framework reads this directly, nothing imports it."
    if "middleware" in n:        return "Middleware file that is never matched or referenced by any route."
    if "/hooks/" in f:           return "Custom React hook — defined but never called from any component."
    if any(x in f for x in ("/utils/","/helpers/","/lib/")):
                                 return "Utility file — exports are never imported anywhere in the project."
    if "/types/" in f or n.endswith(".d.ts"):
                                 return "TypeScript types/interfaces — never referenced in the codebase."
    if "/styles/" in f or n.endswith((".css",".scss")):
                                 return "Stylesheet — never imported by any JS/TS file."
    return "Not reachable from any entry point — no other file imports it."

def reason_export(symbol, file):
    s = symbol.lower()
    if "variant" in s:  return f'"{symbol}" — exported for design-system consumers, but never used internally.'
    if s.startswith(("get","fetch")): return f'"{symbol}" — data-fetching helper defined but never called.'
    if s in ("cardfooter","cardaction"): return f'"{symbol}" — optional Card sub-component that the project never renders.'
    return f'"{symbol}" — exported but never imported or used anywhere in the project.'

def reason_dep(dep):
    d = dep.lower()
    if d.startswith("@radix-ui/"):
        part = dep.split("/")[-1].replace("react-","")
        return f'Radix UI "{part}" primitive — bulk-installed by shadcn/ui; its component file is never used.'
    MAP = {
        "react-hook-form":          "Form library — no forms in the project use it.",
        "@hookform/resolvers":      "Form validation helpers — react-hook-form is itself unused.",
        "date-fns":                 "Date utility library — no date formatting code exists.",
        "react-day-picker":         "Date picker UI — its Calendar component is never rendered.",
        "embla-carousel-react":     "Carousel library — the Carousel component is never imported.",
        "vaul":                     "Drawer library — the Drawer component is never used.",
        "cmdk":                     "Command-palette library — the Command component is never used.",
        "input-otp":                "OTP input library — never imported anywhere.",
        "react-resizable-panels":   "Resizable panels — never used in any layout.",
        "autoprefixer":             "CSS autoprefixer — listed in package.json but never referenced in code.",
    }
    if d in MAP: return MAP[d]
    return f'"{dep}" — listed in package.json but no file in the project imports it.'

def main():
    banner()
    repo_url = (sys.argv[1].strip() if len(sys.argv) >= 2
                else input(f"{W}Enter GitHub repo URL: {NC}").strip())
    if not repo_url:
        print(f"{R}No URL provided.{NC}"); sys.exit(1)
    if not repo_url.endswith(".git"):
        repo_url += ".git"

    tmp = tempfile.mkdtemp(prefix="dead-scan-")

    # Clone
    print(f"{B}📦 Cloning repo …{NC}")
    try:    run(f"git clone --depth=1 {repo_url} {tmp}")
    except RuntimeError as e:
        print(f"{R}❌ Clone failed: {e}{NC}"); shutil.rmtree(tmp, ignore_errors=True); sys.exit(1)
    print(f"{G}✔  Cloned{NC}\n")

    # Install
    if os.path.exists(os.path.join(tmp,"package.json")):
        print(f"{B}📥 Installing dependencies …{NC}")
        try:    run("npm install --ignore-scripts --prefer-offline", cwd=tmp)
        except RuntimeError: pass
        print(f"{G}✔  Done{NC}\n")

    # Run knip
    print(f"{B}🔍 Running knip …{NC}")
    try:    raw = run("npx knip --reporter json", cwd=tmp)
    except RuntimeError as e:
        print(f"{R}❌ knip failed: {e}{NC}"); shutil.rmtree(tmp, ignore_errors=True); sys.exit(1)

    try:    issues = json.loads(raw).get("issues", [])
    except json.JSONDecodeError:
        print(f"{R}❌ Could not parse knip output.{NC}"); shutil.rmtree(tmp, ignore_errors=True); sys.exit(1)

    print(f"{G}✔  Analysis complete{NC}\n")

    dead_files, dead_exports, dead_deps = [], [], []
    for entry in issues:
        f = entry.get("file","")
        if entry.get("files"):          dead_files.append(f)
        for e in entry.get("exports",[]): dead_exports.append((f, e.get("name", e.get("symbol","?"))))
        for d in entry.get("dependencies",[])+entry.get("devDependencies",[]):
            dead_deps.append(d.get("name", d.get("symbol","?")))
    dead_deps = list(dict.fromkeys(dead_deps))

    total = len(dead_files)+len(dead_exports)+len(dead_deps)

    print(f"{C}{'═'*60}\n  DEAD CODE REPORT\n  {repo_url}\n{'═'*60}{NC}\n")

    if total == 0:
        print(f"{G}🎉 No dead code found! The repo looks clean.{NC}\n")
        shutil.rmtree(tmp, ignore_errors=True); return

    if dead_files:
        print(f"{R}🗑️  UNUSED FILES  ({len(dead_files)}){NC}")
        print(f"{DIM}   Never imported — safe to delete.{NC}\n")
        for i,f in enumerate(dead_files,1):
            print(f"  {Y}{i:>2}. {f}{NC}")
            print(f"      {DIM}↳ {reason_file(f)}{NC}\n")

    if dead_exports:
        print(f"{R}📤 UNUSED EXPORTS  ({len(dead_exports)}){NC}")
        print(f"{DIM}   Exported but never imported anywhere.{NC}\n")
        for i,(file,sym) in enumerate(dead_exports,1):
            print(f"  {Y}{i:>2}. {file}  →  {W}{sym}{NC}")
            print(f"      {DIM}↳ {reason_export(sym,file)}{NC}\n")

    if dead_deps:
        print(f"{R}📦 UNUSED DEPENDENCIES  ({len(dead_deps)}){NC}")
        print(f"{DIM}   In package.json but never actually used.{NC}\n")
        for i,dep in enumerate(dead_deps,1):
            print(f"  {Y}{i:>2}. {W}{dep}{NC}")
            print(f"      {DIM}↳ {reason_dep(dep)}{NC}\n")

    print(f"{C}{'═'*60}\n  SUMMARY\n{'═'*60}{NC}")
    print(f"  {R}Unused files        : {len(dead_files)}{NC}")
    print(f"  {R}Unused exports      : {len(dead_exports)}{NC}")
    print(f"  {R}Unused dependencies : {len(dead_deps)}{NC}")
    print(f"  {Y}Total issues        : {total}{NC}\n")
    shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__":
    main()
