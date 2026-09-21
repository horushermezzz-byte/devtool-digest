#!/usr/bin/env python3
"""
Scaling benchmark: does the Hugo/Eleventy/Astro gap hold as the corpus grows?

Most SSG benchmarks publish ONE number at ONE corpus size, which tells you
nothing about the shape of the curve. Per-page cost is what actually decides
whether a generator still works at 5,000 posts.

For each N: regenerate the corpus, sync it into all three sites, run each
build COLD 3 times, take the median. Also records per-page marginal cost.
"""
import json
import os
import shutil
import statistics
import subprocess
import sys
import time

BENCH = "/home/horus/bench"
SIZES = [int(x) for x in (sys.argv[1].split(",") if len(sys.argv) > 1
                          else ["100", "300", "1000", "2500"])]
RUNS = int(os.environ.get("RUNS", "3"))

SITES = {
    "Hugo": {
        "cwd": f"{BENCH}/hugo-site", "cmd": ["hugo", "--quiet"],
        "content": f"{BENCH}/hugo-site/content",
        "clean": [f"{BENCH}/hugo-site/public", f"{BENCH}/hugo-site/resources"],
        "out": f"{BENCH}/hugo-site/public", "inject_layout": False,
    },
    "Eleventy": {
        "cwd": f"{BENCH}/11ty-site", "cmd": ["npx", "@11ty/eleventy", "--quiet"],
        "content": f"{BENCH}/11ty-site/content",
        "clean": [f"{BENCH}/11ty-site/_site", f"{BENCH}/11ty-site/.cache"],
        "out": f"{BENCH}/11ty-site/_site", "inject_layout": False,
    },
    "Astro": {
        "cwd": f"{BENCH}/astro-site", "cmd": ["npx", "astro", "build", "--silent"],
        "content": f"{BENCH}/astro-site/src/pages/posts",
        "clean": [f"{BENCH}/astro-site/dist", f"{BENCH}/astro-site/node_modules/.astro",
                  f"{BENCH}/astro-site/node_modules/.vite"],
        "out": f"{BENCH}/astro-site/dist", "inject_layout": True,
    },
}


def wipe(paths):
    for p in paths:
        shutil.rmtree(p, ignore_errors=True)


def sync_corpus(n):
    """Regenerate corpus at size n and copy into each site (preserving each
    site's own required frontmatter)."""
    subprocess.run([sys.executable, f"{BENCH}/gen_corpus.py", str(n),
                    f"{BENCH}/content"], check=True, capture_output=True)
    src = f"{BENCH}/content"
    files = sorted(f for f in os.listdir(src) if f.endswith(".md"))
    for name, s in SITES.items():
        # keep non-.md files (11ty dir-data json) intact
        for f in os.listdir(s["content"]):
            if f.endswith(".md"):
                os.remove(os.path.join(s["content"], f))
        for f in files:
            text = open(os.path.join(src, f)).read()
            if s["inject_layout"]:
                text = text.replace("---\n", "---\nlayout: ../../layouts/Base.astro\n", 1)
            open(os.path.join(s["content"], f), "w").write(text)


def timed(cmd, cwd):
    t0 = time.perf_counter()
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return time.perf_counter() - t0, r.returncode, (r.stderr or "")[-300:]


def main():
    results = {}
    for n in SIZES:
        print(f"\n########## N = {n} pages ##########", flush=True)
        sync_corpus(n)
        results[n] = {}
        for name, s in SITES.items():
            wipe(s["clean"])
            timed(s["cmd"], s["cwd"])           # discard warm-up
            times = []
            for i in range(RUNS):
                wipe(s["clean"])
                dt, rc, err = timed(s["cmd"], s["cwd"])
                if rc != 0:
                    print(f"  {name} FAILED rc={rc}: {err}")
                    sys.exit(1)
                times.append(dt)
            med = statistics.median(times)
            html = sum(1 for d, _, fs in os.walk(s["out"]) for f in fs
                       if f.endswith(".html"))
            results[n][name] = {"median": med, "runs": times, "html": html,
                                "ms_per_page": med * 1000 / n}
            print(f"  {name:<10} {med:>7.3f}s   {med*1000/n:>6.2f} ms/page   "
                  f"({html} html)", flush=True)

    with open(f"{BENCH}/scaling.json", "w") as fh:
        json.dump(results, fh, indent=2)

    print("\n" + "=" * 70)
    print("BUILD TIME (median, cold)")
    print(f"{'pages':>7}" + "".join(f"{k:>14}" for k in SITES))
    for n in SIZES:
        print(f"{n:>7}" + "".join(f"{results[n][k]['median']:>13.3f}s" for k in SITES))
    print("\nMARGINAL COST (ms per page)")
    print(f"{'pages':>7}" + "".join(f"{k:>14}" for k in SITES))
    for n in SIZES:
        print(f"{n:>7}" + "".join(f"{results[n][k]['ms_per_page']:>13.2f} " for k in SITES))
    print("\nRELATIVE TO HUGO")
    print(f"{'pages':>7}" + "".join(f"{k:>14}" for k in SITES))
    for n in SIZES:
        base = results[n]["Hugo"]["median"]
        print(f"{n:>7}" + "".join(f"{results[n][k]['median']/base:>13.1f}x" for k in SITES))
    print(f"\nwrote {BENCH}/scaling.json")


if __name__ == "__main__":
    main()
