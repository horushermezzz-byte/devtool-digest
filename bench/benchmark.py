#!/usr/bin/env python3
"""
Cross-SSG build benchmark: Hugo vs Eleventy vs Astro on identical input.

Method (stated so it can be criticised):
  * Same 300 markdown files, byte-identical, in all three sites.
  * Equivalent minimal layouts producing the same HTML shape.
  * Each generator's own cache/output dir is wiped before every COLD run,
    so no run benefits from a previous one.
  * N timed runs each, plus warm runs (cache left in place) where the tool has
    a cache. Reported: min / median / mean / max. Median is the headline —
    it's robust to the one slow run a shared VM will always produce.
  * Wall-clock via time.perf_counter around subprocess completion, which is
    what a developer actually waits for (includes node startup).

Deliberately NOT measured: dev-server HMR, incremental rebuilds, asset
pipelines. Those matter but aren't comparable across these configs.
"""
import json
import os
import shutil
import statistics
import subprocess
import sys
import time

BENCH = "/home/horus/bench"
RUNS = int(os.environ.get("RUNS", "7"))

SITES = [
    {
        "name": "Hugo",
        "version_cmd": ["hugo", "version"],
        "cwd": f"{BENCH}/hugo-site",
        "cmd": ["hugo", "--quiet"],
        "clean": [f"{BENCH}/hugo-site/public", f"{BENCH}/hugo-site/resources"],
        "out": f"{BENCH}/hugo-site/public",
    },
    {
        "name": "Eleventy",
        "version_cmd": ["npx", "@11ty/eleventy", "--version"],
        "cwd": f"{BENCH}/11ty-site",
        "cmd": ["npx", "@11ty/eleventy", "--quiet"],
        "clean": [f"{BENCH}/11ty-site/_site", f"{BENCH}/11ty-site/.cache"],
        "out": f"{BENCH}/11ty-site/_site",
    },
    {
        "name": "Astro",
        "version_cmd": ["npx", "astro", "--version"],
        "cwd": f"{BENCH}/astro-site",
        "cmd": ["npx", "astro", "build", "--silent"],
        "clean": [f"{BENCH}/astro-site/dist", f"{BENCH}/astro-site/node_modules/.astro",
                  f"{BENCH}/astro-site/node_modules/.vite"],
        "out": f"{BENCH}/astro-site/dist",
    },
]


def wipe(paths):
    for p in paths:
        shutil.rmtree(p, ignore_errors=True)


def count_html(root):
    return sum(1 for d, _, fs in os.walk(root) for f in fs if f.endswith(".html"))


def dir_bytes(root):
    return sum(os.path.getsize(os.path.join(d, f))
               for d, _, fs in os.walk(root) for f in fs)


def timed(cmd, cwd):
    t0 = time.perf_counter()
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    dt = time.perf_counter() - t0
    return dt, r.returncode, (r.stderr or "")[-400:]


def main():
    results = {}
    for s in SITES:
        print(f"\n=== {s['name']} ===", flush=True)
        try:
            v = subprocess.run(s["version_cmd"], cwd=s["cwd"], capture_output=True,
                               text=True, timeout=120).stdout.strip().splitlines()
            version = v[-1] if v else "?"
        except Exception as e:  # noqa: BLE001
            version = f"unknown ({e})"
        print(f"version: {version}", flush=True)

        cold, warm = [], []

        # sacrificial run: warms OS page cache + node module resolution so the
        # first *measured* run isn't penalised for being first overall.
        wipe(s["clean"])
        timed(s["cmd"], s["cwd"])

        for i in range(RUNS):
            wipe(s["clean"])
            dt, rc, err = timed(s["cmd"], s["cwd"])
            if rc != 0:
                print(f"  FAILED rc={rc}\n{err}")
                sys.exit(1)
            cold.append(dt)
            print(f"  cold run {i+1}/{RUNS}: {dt:.3f}s", flush=True)

        for i in range(RUNS):
            dt, rc, _ = timed(s["cmd"], s["cwd"])  # no wipe = warm
            if rc == 0:
                warm.append(dt)

        html = count_html(s["out"])
        size = dir_bytes(s["out"])
        results[s["name"]] = {
            "version": version,
            "cold": {"min": min(cold), "median": statistics.median(cold),
                     "mean": statistics.fmean(cold), "max": max(cold),
                     "stdev": statistics.pstdev(cold), "runs": cold},
            "warm": {"min": min(warm), "median": statistics.median(warm),
                     "mean": statistics.fmean(warm), "max": max(warm)} if warm else None,
            "html_files": html,
            "output_bytes": size,
        }
        print(f"  -> {html} html, {size:,} bytes output", flush=True)

    with open(f"{BENCH}/results.json", "w") as fh:
        json.dump(results, fh, indent=2)

    print("\n" + "=" * 72)
    print(f"{'Generator':<12}{'Version':<12}{'cold med':>10}{'cold min':>10}"
          f"{'warm med':>10}{'pages':>8}{'output':>12}")
    print("-" * 72)
    base = min(r["cold"]["median"] for r in results.values())
    for name, r in sorted(results.items(), key=lambda kv: kv[1]["cold"]["median"]):
        warm_med = f"{r['warm']['median']:.2f}s" if r["warm"] else "-"
        print(f"{name:<12}{r['version'][:11]:<12}{r['cold']['median']:>9.2f}s"
              f"{r['cold']['min']:>9.2f}s{warm_med:>10}"
              f"{r['html_files']:>8}{r['output_bytes']:>11,}B")
    print("-" * 72)
    for name, r in sorted(results.items(), key=lambda kv: kv[1]["cold"]["median"]):
        print(f"  {name:<10} {r['cold']['median']/base:>6.1f}x   "
              f"(sd {r['cold']['stdev']:.3f}s over {RUNS} runs)")
    print(f"\nwrote {BENCH}/results.json")


if __name__ == "__main__":
    main()
