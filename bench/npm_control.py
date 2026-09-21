#!/usr/bin/env python3
"""
CONTROL: is npm 11.19's warning an actual block, or just a warning?

The survey found packages working "despite blocked scripts" -- but canvas,
sqlite3 and node-sass shipped build/Release/*.node, which is where node-gyp puts
COMPILED output. If those scripts really ran, the finding is worthless.

Three arms per package:
  A. default        -- npm's own behaviour, what the survey measured
  B. --ignore-scripts -- unambiguous block
  C. probe          -- a package whose install script writes a marker file;
                       marker present == scripts executed

Arm C is the ground truth for whether "warned" means "ran".
"""
import json, os, shutil, subprocess, tempfile

TMP = os.environ.get("TMPDIR", "/tmp")
PKGS = [
    ("canvas", "const {createCanvas}=require('canvas');console.log('OK '+createCanvas(4,4).toBuffer().length)"),
    ("sqlite3", "const s=require('sqlite3');new s.Database(':memory:');console.log('OK')"),
    ("node-sass", "console.log('OK '+require('node-sass').info.split('\\n')[0])"),
    ("bcrypt", "console.log('OK '+require('bcrypt').hashSync('x',4).slice(0,4))"),
]


def sh(cmd, cwd, timeout=1500):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def arm(pkg, smoke, ignore_scripts):
    d = tempfile.mkdtemp(prefix="ctl_", dir=TMP)
    try:
        sh(["npm", "init", "-y"], d, 180)
        cmd = ["npm", "install", "--no-audit", "--no-fund"]
        if ignore_scripts:
            cmd.append("--ignore-scripts")
        cmd.append(pkg)
        r = sh(cmd, d, 1500)
        out = (r.stdout or "") + (r.stderr or "")
        ok = False
        if r.returncode == 0:
            t = sh(["node", "-e", smoke], d, 300)
            ok = t.returncode == 0 and "OK" in (t.stdout or "")
        # where did the .node come from?
        nm = os.path.join(d, "node_modules")
        built, prebuilt = [], []
        for root, _, files in os.walk(nm):
            for f in files:
                if f.endswith(".node"):
                    rel = os.path.relpath(os.path.join(root, f), nm)
                    (built if "/build/" in "/" + rel else prebuilt).append(rel)
        return {"installed": r.returncode == 0, "works": ok,
                "warned": "install scripts not yet covered" in out,
                "built_from_source": built[:3], "prebuilt": prebuilt[:3],
                "n_built": len(built), "n_prebuilt": len(prebuilt)}
    finally:
        shutil.rmtree(d, ignore_errors=True)


def probe_scripts_actually_run():
    """Ground truth: does a postinstall script execute under npm's default?"""
    res = {}
    for ignore in (False, True):
        d = tempfile.mkdtemp(prefix="probe_", dir=TMP)
        try:
            sh(["npm", "init", "-y"], d, 180)
            dep = os.path.join(d, "marker-pkg")
            os.makedirs(dep)
            json.dump({"name": "marker-pkg", "version": "1.0.0",
                       "scripts": {"postinstall":
                                   "node -e \"require('fs').writeFileSync(require('path').join(__dirname,'RAN'),'1')\""}},
                      open(os.path.join(dep, "package.json"), "w"))
            cmd = ["npm", "install", "--no-audit", "--no-fund"]
            if ignore:
                cmd.append("--ignore-scripts")
            cmd.append("./marker-pkg")
            r = sh(cmd, d, 600)
            out = (r.stdout or "") + (r.stderr or "")
            ran = os.path.exists(os.path.join(d, "node_modules", "marker-pkg", "RAN"))
            res["ignore_scripts" if ignore else "default"] = {
                "script_executed": ran,
                "warned": "install scripts not yet covered" in out,
                "rc": r.returncode}
        finally:
            shutil.rmtree(d, ignore_errors=True)
    return res


if __name__ == "__main__":
    print("=== GROUND TRUTH: does a postinstall script actually execute? ===",
          flush=True)
    probe = probe_scripts_actually_run()
    for k, v in probe.items():
        print(f"  {k:<16} script_executed={v['script_executed']}  warned={v['warned']}",
              flush=True)

    print("\n=== PER-PACKAGE: default vs --ignore-scripts ===", flush=True)
    out = {"probe": probe, "packages": {}}
    for pkg, smoke in PKGS:
        print(f"\n{pkg}", flush=True)
        a = arm(pkg, smoke, ignore_scripts=False)
        b = arm(pkg, smoke, ignore_scripts=True)
        out["packages"][pkg] = {"default": a, "ignore_scripts": b}
        for label, r in (("default", a), ("--ignore-scripts", b)):
            src = (f"built:{r['n_built']}" if r["n_built"] else "") + \
                  (f" prebuilt:{r['n_prebuilt']}" if r["n_prebuilt"] else "")
            print(f"  {label:<17} installs={str(r['installed']):<5} works={str(r['works']):<5} "
                  f"warned={str(r['warned']):<5} {src}", flush=True)
        json.dump(out, open("/home/horus/bench/npm_control.json", "w"), indent=2)
    print("\nwrote /home/horus/bench/npm_control.json")
