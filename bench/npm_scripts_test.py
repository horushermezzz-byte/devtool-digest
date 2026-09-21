#!/usr/bin/env python3
"""
Do native npm packages actually break when install scripts are blocked?

npm 11.19 warns about un-approved install scripts; npm 12 (July 2026) makes it a
hard block. The received wisdom is that blocking postinstall breaks native
modules. That was true when native modules compiled from source at install time.
It may no longer be, because most have migrated to prebuilt platform binaries
shipped as optional dependencies.

For each package: install into a clean temp project with scripts blocked, then
actually REQUIRE it and call something real. Loading is the test -- an install
that "succeeds" while leaving a broken module is still a failure.

Records, per package: whether npm reported blocked scripts, whether require()
worked, and whether a real call worked. ARM64 matters here: prebuild coverage is
thinner than x86, so this is where the wisdom is most likely to still hold.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

# (package, import name, smoke-test JS that must run)
PKGS = [
    ("sharp", "sharp",
     "const s=require('sharp'); s({create:{width:8,height:8,channels:3,background:'#000'}})"
     ".png().toBuffer().then(b=>console.log('OK bytes='+b.length))"),
    ("bcrypt", "bcrypt",
     "const b=require('bcrypt'); console.log('OK hash='+b.hashSync('x',4).slice(0,7))"),
    ("better-sqlite3", "better-sqlite3",
     "const D=require('better-sqlite3'); const d=new D(':memory:');"
     "d.exec('create table t(a)'); d.prepare('insert into t values (1)').run();"
     "console.log('OK rows='+d.prepare('select count(*) c from t').get().c)"),
    ("esbuild", "esbuild",
     "require('esbuild').transformSync('const x:number=1',{loader:'ts'});"
     "console.log('OK transformed')"),
    ("canvas", "canvas",
     "const {createCanvas}=require('canvas'); const c=createCanvas(10,10);"
     "console.log('OK png='+c.toBuffer().length)"),
    ("sqlite3", "sqlite3",
     "const s=require('sqlite3'); const d=new s.Database(':memory:');"
     "d.serialize(()=>{d.run('create table t(a)');"
     "d.get('select count(*) c from t',(e,r)=>console.log('OK rows='+r.c))})"),
    ("node-sass", "node-sass",
     "const s=require('node-sass'); console.log('OK '+s.info.split('\\n')[0])"),
    ("ws", "ws",
     "const W=require('ws'); console.log('OK ws loaded')"),
]

OUT = "/home/horus/bench/npm_scripts.json"


def run(cmd, cwd, timeout=900, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout, env=e)


def test_pkg(pkg, imp, smoke, allow_scripts):
    d = tempfile.mkdtemp(prefix=f"npmtest_{pkg.replace('/','_')}_",
                         dir=os.environ.get("TMPDIR", "/tmp"))
    try:
        run(["npm", "init", "-y"], d, timeout=180)
        args = ["npm", "install", "--no-audit", "--no-fund", pkg]
        if allow_scripts:
            args.insert(2, "--foreground-scripts")
        r = run(args, d, timeout=1500)
        out = (r.stdout or "") + (r.stderr or "")
        blocked = "install scripts not yet covered" in out or "allowScripts" in out
        installed = r.returncode == 0

        loaded = called = False
        err = ""
        if installed:
            t = run(["node", "-e", smoke], d, timeout=300)
            called = t.returncode == 0 and "OK" in (t.stdout or "")
            loaded = called or "Cannot find module" not in (t.stderr or "")
            if not called:
                err = ((t.stderr or t.stdout or "").strip().splitlines() or [""])[0][:180]

        # what shipped: prebuilt .node binaries vs compiled
        nodes = []
        nm = os.path.join(d, "node_modules")
        for root, _, files in os.walk(nm):
            for f in files:
                if f.endswith(".node"):
                    nodes.append(os.path.relpath(os.path.join(root, f), nm))
        return {"package": pkg, "installed": installed, "scripts_blocked": blocked,
                "loaded": loaded, "works": called, "error": err,
                "native_binaries": nodes[:4], "n_native": len(nodes),
                "install_log_tail": out.strip()[-300:] if not installed else ""}
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else None
    results = json.load(open(OUT)) if os.path.exists(OUT) else []
    done = {r["package"] for r in results}
    for pkg, imp, smoke in PKGS:
        if only and only != pkg:
            continue
        if pkg in done:
            print(f"skip {pkg} (done)")
            continue
        print(f"\n=== {pkg} (scripts blocked) ===", flush=True)
        r = test_pkg(pkg, imp, smoke, allow_scripts=False)
        verdict = ("WORKS" if r["works"] else
                   "INSTALL FAILED" if not r["installed"] else "BROKEN")
        print(f"  installed={r['installed']} blocked={r['scripts_blocked']} "
              f"works={r['works']}  -> {verdict}", flush=True)
        if r["error"]:
            print(f"  error: {r['error']}", flush=True)
        if r["native_binaries"]:
            print(f"  native: {r['n_native']} .node file(s), e.g. {r['native_binaries'][0]}",
                  flush=True)
        results.append(r)
        json.dump(results, open(OUT, "w"), indent=2)

    print("\n" + "=" * 74)
    print(f"{'package':<18}{'installs':>9}{'blocked':>9}{'works':>8}   verdict")
    print("-" * 74)
    for r in results:
        v = "works despite block" if (r["works"] and r["scripts_blocked"]) else \
            "works (no scripts)" if r["works"] else \
            "INSTALL FAILED" if not r["installed"] else "BROKEN"
        print(f"{r['package']:<18}{str(r['installed']):>9}{str(r['scripts_blocked']):>9}"
              f"{str(r['works']):>8}   {v}")
    print(f"\nwrote {OUT}")
