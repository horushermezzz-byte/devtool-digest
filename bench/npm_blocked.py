#!/usr/bin/env python3
"""
Full set under a REAL block (--ignore-scripts), plus what npm's own config does.

The first survey was invalid: npm 11.19 WARNS about un-approved install scripts
but still runs them (proved by a marker-file probe). So "works despite blocked
scripts" was actually "works because the scripts ran".

This measures the real thing: every package with --ignore-scripts, which is what
npm 12's hard block approximates.
"""
import json, os, shutil, subprocess, tempfile

TMP = os.environ.get("TMPDIR", "/tmp")
OUT = "/home/horus/bench/npm_blocked.json"

PKGS = [
    ("sharp", "require('sharp')({create:{width:8,height:8,channels:3,background:'#000'}}).png().toBuffer().then(b=>console.log('OK '+b.length))"),
    ("better-sqlite3", "const D=require('better-sqlite3');const d=new D(':memory:');d.exec('create table t(a)');console.log('OK')"),
    ("esbuild", "require('esbuild').transformSync('const x:number=1',{loader:'ts'});console.log('OK')"),
    ("ws", "require('ws');console.log('OK')"),
    ("canvas", "const {createCanvas}=require('canvas');console.log('OK '+createCanvas(4,4).toBuffer().length)"),
    ("sqlite3", "const s=require('sqlite3');new s.Database(':memory:');console.log('OK')"),
    ("node-sass", "console.log('OK '+require('node-sass').info.split('\\n')[0])"),
    ("bcrypt", "console.log('OK '+require('bcrypt').hashSync('x',4).slice(0,4))"),
]


def sh(cmd, cwd, timeout=1500):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def blocked_run(pkg, smoke):
    d = tempfile.mkdtemp(prefix="blk_", dir=TMP)
    try:
        sh(["npm", "init", "-y"], d, 180)
        r = sh(["npm", "install", "--no-audit", "--no-fund", "--ignore-scripts", pkg], d, 1500)
        ok, err = False, ""
        if r.returncode == 0:
            t = sh(["node", "-e", smoke], d, 300)
            ok = t.returncode == 0 and "OK" in (t.stdout or "")
            if not ok:
                err = ((t.stderr or t.stdout or "").strip().splitlines() or [""])[0][:200]
        nm = os.path.join(d, "node_modules")
        built, prebuilt = [], []
        for root, _, files in os.walk(nm):
            for f in files:
                if f.endswith(".node"):
                    rel = os.path.relpath(os.path.join(root, f), nm)
                    (built if "/build/" in "/" + rel else prebuilt).append(rel)
        # does the package ship optional platform deps? (the prebuild pattern)
        opt = []
        pj = os.path.join(nm, pkg, "package.json")
        if os.path.exists(pj):
            j = json.load(open(pj))
            opt = list((j.get("optionalDependencies") or {}).keys())[:6]
        return {"package": pkg, "installed": r.returncode == 0, "works": ok, "error": err,
                "n_built": len(built), "n_prebuilt": len(prebuilt),
                "prebuilt_example": prebuilt[0] if prebuilt else "",
                "optional_deps": opt}
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    res = json.load(open(OUT)) if os.path.exists(OUT) else []
    done = {r["package"] for r in res}
    for pkg, smoke in PKGS:
        if pkg in done:
            continue
        print(f"=== {pkg} --ignore-scripts ===", flush=True)
        r = blocked_run(pkg, smoke)
        print(f"  works={r['works']} built={r['n_built']} prebuilt={r['n_prebuilt']}", flush=True)
        if r["error"]:
            print(f"  error: {r['error']}", flush=True)
        if r["optional_deps"]:
            print(f"  optionalDeps: {', '.join(r['optional_deps'][:3])}", flush=True)
        res.append(r)
        json.dump(res, open(OUT, "w"), indent=2)

    print("\n" + "=" * 78)
    print(f"{'package':<17}{'works':>7}{'prebuilt':>10}{'built':>7}   mechanism")
    print("-" * 78)
    for r in sorted(res, key=lambda x: not x["works"]):
        mech = ("optional platform dep" if r["optional_deps"] and r["works"]
                else "bundled prebuilds" if r["n_prebuilt"] and r["works"]
                else "needs compile -- BREAKS" if not r["works"] else "pure JS")
        print(f"{r['package']:<17}{str(r['works']):>7}{r['n_prebuilt']:>10}{r['n_built']:>7}   {mech}")
    print(f"\nwrote {OUT}")
