#!/usr/bin/env python3
"""
Measure what self-hosted tools ACTUALLY cost to run: idle RAM, image size,
and time-to-first-usable-response. One tool at a time (this box has ~1 GB
free), torn down between runs so measurements don't contaminate each other.

Time-to-ready is measured by polling the tool's own HTTP endpoint until it
returns an acceptable status — not by waiting for `docker run` to return,
which says nothing about whether the app is usable.
"""
import json
import os
import subprocess
import sys
import time

ENV = dict(os.environ)
ENV["PATH"] = f"{os.path.expanduser('~')}/bin:" + ENV.get("PATH", "")
ENV["DOCKER_HOST"] = f"unix:///run/user/{os.getuid()}/docker.sock"

OUT = "/home/horus/bench/selfhosted.json"


def d(*args, timeout=600, check=False):
    return subprocess.run(["docker", *args], env=ENV, capture_output=True,
                          text=True, timeout=timeout, check=check)


def image_size_mb(image):
    r = d("image", "inspect", image, "--format", "{{.Size}}")
    try:
        return int(r.stdout.strip()) / 1024 / 1024
    except ValueError:
        return None


def container_mem_mb(name):
    """Sum RSS of the container's processes via docker stats (no --no-trunc noise)."""
    r = d("stats", "--no-stream", "--format", "{{.MemUsage}}", name, timeout=120)
    raw = r.stdout.strip().split("/")[0].strip()
    if not raw:
        return None
    val = raw.rstrip("BKMGi")
    try:
        num = float(val)
    except ValueError:
        return None
    if "GiB" in raw or "GB" in raw:
        return num * 1024
    if "KiB" in raw or "kB" in raw:
        return num / 1024
    return num


def wait_http(url, accept=(200, 302, 301, 401, 403), timeout=300):
    """Poll until the app answers. Returns seconds, or None on timeout."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             "--max-time", "5", url],
            capture_output=True, text=True)
        try:
            if int(r.stdout.strip()) in accept:
                return time.time() - t0
        except ValueError:
            pass
        time.sleep(1)
    return None


def run_case(case):
    name = case["name"]
    print(f"\n=== {name} ===", flush=True)
    d("rm", "-f", case["cname"], timeout=120)

    t0 = time.time()
    pull = d("pull", case["image"], timeout=1200)
    pull_s = time.time() - t0
    if pull.returncode != 0:
        print(f"  PULL FAILED: {pull.stderr.strip()[:200]}")
        return {"name": name, "error": "pull failed"}
    size = image_size_mb(case["image"])
    print(f"  image: {size:.0f} MB (pull {pull_s:.0f}s)", flush=True)

    r = d("run", "-d", "--name", case["cname"], *case["args"], case["image"],
          *case.get("cmd", []), timeout=300)
    if r.returncode != 0:
        print(f"  START FAILED: {r.stderr.strip()[:300]}")
        return {"name": name, "image_mb": size, "error": "start failed"}

    ready = wait_http(case["url"], timeout=case.get("ready_timeout", 300))
    if ready is None:
        logs = d("logs", "--tail", "8", case["cname"], timeout=60)
        print(f"  NEVER became ready. logs:\n{logs.stdout[-500:]}{logs.stderr[-500:]}")
    else:
        print(f"  ready in {ready:.1f}s", flush=True)

    time.sleep(12)  # let it settle before measuring idle
    mem = container_mem_mb(case["cname"])
    print(f"  idle RAM: {mem:.0f} MB" if mem else "  idle RAM: n/a", flush=True)

    d("rm", "-f", case["cname"], timeout=180)
    return {"name": name, "image_mb": round(size, 1) if size else None,
            "pull_s": round(pull_s, 1),
            "ready_s": round(ready, 1) if ready else None,
            "idle_mb": round(mem, 1) if mem else None}


CASES = [
    {
        "name": "Vaultwarden", "cname": "sh_vw",
        "image": "vaultwarden/server:latest",
        "args": ["-p", "8101:80", "-e", "ROCKET_PORT=80",
                 "-v", "/home/horus/bench/vol/vw:/data"],
        "url": "http://127.0.0.1:8101/",
    },
    {
        "name": "Uptime Kuma", "cname": "sh_uk",
        "image": "louislam/uptime-kuma:1",
        "args": ["-p", "8102:3001",
                 "-v", "/home/horus/bench/vol/uk:/app/data"],
        "url": "http://127.0.0.1:8102/",
    },
    {
        "name": "Shlink", "cname": "sh_sl",
        "image": "shlinkio/shlink:stable",
        "args": ["-p", "8103:8080", "-e", "DEFAULT_DOMAIN=localhost:8103",
                 "-e", "IS_HTTPS_ENABLED=false"],
        "url": "http://127.0.0.1:8103/rest/health",
    },
    {
        "name": "n8n", "cname": "sh_n8",
        "image": "docker.n8n.io/n8nio/n8n:latest",
        "args": ["-p", "8104:5678", "-e", "N8N_SECURE_COOKIE=false",
                 "-v", "/home/horus/bench/vol/n8n:/home/node/.n8n"],
        "url": "http://127.0.0.1:8104/",
        "ready_timeout": 420,
    },
]

if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else None
    results = []
    if os.path.exists(OUT):
        results = json.load(open(OUT))
    done = {r["name"] for r in results}
    for c in CASES:
        if only and only.lower() not in c["name"].lower():
            continue
        if c["name"] in done:
            print(f"skip {c['name']} (already measured)")
            continue
        results.append(run_case(c))
        json.dump(results, open(OUT, "w"), indent=2)
    print(f"\nwrote {OUT}")
    for r in results:
        print(f"  {r['name']:<14} {str(r.get('image_mb','-')):>7} MB  "
              f"ready {str(r.get('ready_s','-')):>6}s  idle {str(r.get('idle_mb','-')):>6} MB")
