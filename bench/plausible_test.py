#!/usr/bin/env python3
"""
Does Plausible CE actually OOM on a ~1 GB box?

Community guidance says "at least 2 GB of RAM recommended for running ClickHouse
and Plausible without fear of OOMs". This box has ~1 GB free. That's a testable
prediction, so test it rather than repeating it.

Brings up the real 3-container stack (Postgres + ClickHouse + Plausible) and
records what actually happens: ready, OOM-killed, or restart-looping.
"""
import json
import os
import subprocess
import time

ENV = dict(os.environ)
ENV["PATH"] = f"{os.path.expanduser('~')}/bin:" + ENV.get("PATH", "")
ENV["DOCKER_HOST"] = f"unix:///run/user/{os.getuid()}/docker.sock"
NET = "plausible_net"
OUT = "/home/horus/bench/plausible.json"


def d(*a, timeout=900):
    return subprocess.run(["docker", *a], env=ENV, capture_output=True,
                          text=True, timeout=timeout)


def free_mb():
    with open("/proc/meminfo") as fh:
        m = {l.split(":")[0]: int(l.split()[1]) for l in fh}
    return m["MemAvailable"] // 1024


def state(name):
    r = d("inspect", name, "--format",
          "{{.State.Status}}|{{.State.OOMKilled}}|{{.RestartCount}}|{{.State.ExitCode}}")
    return r.stdout.strip()


def cleanup():
    d("rm", "-f", "pl_db", "pl_ch", "pl_app", timeout=300)
    d("network", "rm", NET, timeout=120)


print(f"MemAvailable before: {free_mb()} MB")
cleanup()
d("network", "create", NET, timeout=120)

result = {"free_before_mb": free_mb(), "events": []}


def log(msg):
    print(f"  {msg}", flush=True)
    result["events"].append(msg)


# --- Postgres ---
r = d("run", "-d", "--name", "pl_db", "--network", NET,
      "-e", "POSTGRES_PASSWORD=postgres", "-e", "POSTGRES_DB=plausible_db",
      "postgres:16-alpine", timeout=900)
log(f"postgres start rc={r.returncode} {r.stderr.strip()[:120]}")

# --- ClickHouse (the memory hog) ---
r = d("run", "-d", "--name", "pl_ch", "--network", NET,
      "-e", "CLICKHOUSE_SKIP_USER_SETUP=1",
      "--ulimit", "nofile=262144:262144",
      "clickhouse/clickhouse-server:24-alpine", timeout=900)
log(f"clickhouse start rc={r.returncode} {r.stderr.strip()[:120]}")

time.sleep(45)
log(f"after DBs: MemAvailable {free_mb()} MB")
log(f"pg    state: {state('pl_db')}")
log(f"ch    state: {state('pl_ch')}")

# --- Plausible app ---
r = d("run", "-d", "--name", "pl_app", "--network", NET, "-p", "8105:8000",
      "-e", "BASE_URL=http://localhost:8105",
      "-e", "SECRET_KEY_BASE=" + "x" * 64,
      "-e", "DATABASE_URL=postgres://postgres:postgres@pl_db:5432/plausible_db",
      "-e", "CLICKHOUSE_DATABASE_URL=http://pl_ch:8123/plausible_events_db",
      "ghcr.io/plausible/community-edition:v3", timeout=900)
log(f"plausible start rc={r.returncode} {r.stderr.strip()[:160]}")

ready = None
t0 = time.time()
while time.time() - t0 < 420:
    p = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                        "--max-time", "5", "http://127.0.0.1:8105/"],
                       capture_output=True, text=True)
    if p.stdout.strip() in ("200", "302", "301"):
        ready = time.time() - t0
        break
    time.sleep(4)

result["ready_s"] = round(ready, 1) if ready else None
result["free_low_mb"] = free_mb()
for n in ("pl_db", "pl_ch", "pl_app"):
    result[n] = state(n)
    log(f"{n:6} final: {state(n)}")

if ready:
    log(f"PLAUSIBLE READY in {ready:.0f}s")
else:
    log("PLAUSIBLE NEVER BECAME READY")
    lg = d("logs", "--tail", "15", "pl_app", timeout=120)
    result["app_log_tail"] = (lg.stdout + lg.stderr)[-1200:]
    log("app log tail:\n" + result["app_log_tail"][-600:])

log(f"MemAvailable at end: {free_mb()} MB")

# dmesg OOM evidence
dm = subprocess.run(["grep", "-iE", "out of memory|oom-kill|killed process",
                     "/var/log/kern.log"], capture_output=True, text=True)
tail = "\n".join(dm.stdout.strip().splitlines()[-6:])
result["oom_log"] = tail
if tail:
    log("KERNEL OOM EVIDENCE:\n" + tail)

json.dump(result, open(OUT, "w"), indent=2)
print(f"\nwrote {OUT}")
cleanup()
