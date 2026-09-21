---
title: "5 Self-Hosted Tools Worth Replacing Paid SaaS With — And When They Aren't"
date: 2026-09-19T13:00:00+02:00
lastmod: 2026-09-21T09:50:00+02:00
draft: false
tags: ["self-hosted", "open-source", "productivity", "docker"]
summary: "Five open-source tools that replace recurring SaaS bills — now with measured idle RAM, image sizes, and startup times from actually running every one of them on a 3.3 GB ARM box. Includes the tool that needs 108x more memory than the lightest, and the widely-repeated RAM requirement that turned out to be wrong."
---

Recurring SaaS costs compound quietly: a password manager, uptime monitoring, analytics, a link
shortener, some automation glue. Each is $5–15/month and individually easy to justify. Together
they're often $50+/month for categories where mature open-source alternatives exist.

The usual version of this article stops at "here are five tools." The problem is that
*resource cost* is the thing that actually decides whether self-hosting works on the cheap VPS
you were planning to use — and almost nobody publishes measured numbers.

So I ran all five. Here's what they actually cost to run.

## What I measured, and how

**Box:** 6-core `aarch64` VM, 3.3 GB RAM total (~1.5 GB free), Ubuntu 26.04.1, [rootless Docker](/devtool-digest/posts/rootless-docker-apparmor-reexec/)
29.8.1, overlayfs storage. Every image is arm64-native — I checked the manifests before pulling,
and all five publish `linux/arm64`.

**Method:** one tool at a time, each with a persistent volume, torn down between runs so
measurements don't contaminate each other. "Ready" means *the tool's own HTTP endpoint answered*,
polled once per second — not when `docker run` returned, which tells you nothing about whether
the app is usable. Idle RAM is `docker stats` after a 12-second settle.

**Ready times exclude image pull**, which is measured separately — they're cold *container*
starts with the image already local. Pulling matters on first deploy and varies with your
connection, so it isn't comparable between tools: n8n's 1.7 GB image took 271 seconds to pull
here, and my first Plausible run took 280 seconds end-to-end almost entirely because of pulls.
Budget for that once, then never again.

| Tool | Image size | Time to ready | **Idle RAM** |
|---|---:|---:|---:|
| Vaultwarden | 403 MB | 1.0s | **7 MB** |
| Uptime Kuma | 678 MB | 2.0s | **112 MB** |
| Shlink | 396 MB | 1.1s | **296.5 MB** |
| n8n | 1,721 MB | 3.0s | **775 MB** |
| Plausible (3 containers) | 1,269 MB | 4.0s | **761 MB** |

The headline: **n8n idles at 108x Vaultwarden's memory.** These tools get discussed as if they're
interchangeable "one container each" propositions. They are not remotely in the same class.

## 1. Vaultwarden — replaces 1Password / LastPass

A Rust reimplementation of the Bitwarden server, compatible with the official Bitwarden clients.
Your browser extension and mobile apps don't change; only the sync backend moves to hardware you
control.

**Measured:** 403 MB image, ready in **1.0 second**, idling at **7 MB of RAM**. That is the
lightest server-grade thing I have ever benchmarked. It will run on the smallest VPS tier any
provider sells, alongside everything else you're already running.

**It refuses to start unsafely, which I found out by doing it wrong.** My first run omitted a
volume mount, and Vaultwarden hard-stopped rather than come up:

```
[vaultwarden][ERROR] No persistent volume!
########################################################################################
# It looks like you did not configure a persistent volume!                             #
# This will result in permanent data loss when the container is removed or updated!    #
# If you really want to use volatile storage set `I_REALLY_WANT_VOLATILE_STORAGE=true` #
########################################################################################
```

That is excellent design and a point in its favour. The failure mode it's preventing — a password
vault silently running on ephemeral storage — is exactly the catastrophe you'd discover at the
worst possible moment. With a volume mounted, it writes `db.sqlite3` and `rsa_key.pem`, and those
files are your entire vault.

**The caveat that matters:** this is your password vault. A silently failing backup here is
categorically worse than for anything else on this list. If you aren't going to verify restores
on a schedule, pay for the hosted product.

## 2. Uptime Kuma — replaces UptimeRobot / Pingdom paid tiers

Self-hosted monitoring with HTTP(S), TCP, DNS, and container checks, plus notification
integrations (Discord, Slack, email, webhooks).

**Measured:** 678 MB image, ready in **2.0 seconds**, **112 MB idle**. Comfortable on any
$5/month VPS. It persists a SQLite database plus screenshot and upload directories.

**The caveat that matters:** a monitor hosted on the same infrastructure as the thing it monitors
cannot tell you that infrastructure is down. If it's your only alerting, run it somewhere else
entirely — or keep a free-tier external checker as a backstop. This is the most common
self-hosted monitoring mistake, and no amount of RAM fixes it.

## 3. Plausible — replaces paid analytics tiers

Privacy-respecting analytics that avoids the consent-banner overhead Google Analytics brings
under GDPR.

**This is the one where the received wisdom is wrong.** The commonly repeated requirement is
["at least 2 GB of RAM ... without fear of OOMs"](https://github.com/Lirinay/plausible-community-edition).
This box had roughly 1.4–1.5 GB free. I ran the full three-container stack anyway:

```
MemAvailable at start:        1556 MB
app ready in 4s
MemAvailable with full stack: 1100 MB

pl_db   (PostgreSQL)   65.5 MiB
pl_ch   (ClickHouse)  285.4 MiB
pl_app  (Plausible)   410.5 MiB
                      --------
                      761  MiB total
```

Then 300 consecutive requests to confirm it wasn't just surviving idle:

```
  ok=300 fail=0
  pl_db  status=running oom=false restarts=0
  pl_ch  status=running oom=false restarts=0
  pl_app status=running oom=false restarts=0
  kernel OOM events: 0
```

**Zero failures, zero OOM kills, zero restarts.** The 2 GB figure is conservative guidance, not a
hard floor — at least for a low-traffic site. I'd still respect it for anything with real
traffic, because ClickHouse's memory use scales with query volume and my 300 requests are not a
production workload. But "you need 2 GB" is not a reason to skip Plausible on a 1 GB box.

**Two setup traps that cost me real time.** Neither is in the quickstart:

First, the app crashes on boot if you skip the migration step, and the error names a table rather
than the actual problem:

```
relation "salts" does not exist
```

Second — and this is the one that had me chasing ghosts — `db migrate` *itself* fails unless the
ClickHouse database already exists:

```
Code: 81. DB::Exception: Database plausible_events_db does not exist. (UNKNOWN_DATABASE)
```

The official Compose file creates it via an init step, so anyone assembling containers by hand
hits this. The fix, before migrating:

```sh
docker exec pl_ch clickhouse-client --query "CREATE DATABASE IF NOT EXISTS plausible_events_db"
```

**The caveat that matters, and it's underrated:** for developer-audience sites, analytics of any
kind undercount badly. Surveys put ad blocker usage among programmers around 72%
([Censuswide, reported by The Register](https://www.theregister.com/2024/03/27/america_ad_blocker/)),
and many block analytics endpoints wholesale. Self-hosting on a first-party domain gets better
coverage than a third-party script, but if you're deciding anything important on absolute traffic
numbers for a technical audience, treat them as a floor, not a measurement.

## 4. Shlink — replaces Bitly Pro / short.io

A self-hosted URL shortener with your own domain, click analytics, REST API, and QR generation —
the features most shorteners put behind a paid tier.

**Measured:** 396 MB image (the smallest here), ready in **1.1 seconds**, but **296.5 MB idle** —
40x Vaultwarden's memory for a substantially simpler job. If you're mentally filing "URL
shortener" under "trivial service," the RAM says otherwise. It ships a REST health endpoint
(`/rest/health`), which is a good sign for operability.

**The caveat that matters:** short links are forever. People paste them into documents, print
them, embed them in things you'll never see again. Self-hosting means *you* are now the reason a
link either keeps resolving in five years or doesn't. That's a long-term maintenance commitment,
not a weekend project.

## 5. n8n — replaces Zapier / Make.com

Visual workflow automation with a self-hostable community edition.

**Measured, and it's the outlier:** a **1,721 MB image** — 4.3x the size of Vaultwarden's — and
**775 MB idle**, before you build a single workflow. The pull alone took 271 seconds on this
connection.

This reframes the economics people usually cite. If your Zapier bill is $20–30/month, self-hosted
n8n is often described as the obvious win. But 775 MB idle means you are not squeezing it onto
the $5 VPS next to everything else; you're provisioning a box for it. Fold that into the
comparison before declaring victory.

**The caveat that matters:** automations fail silently. A Zapier outage produces a status page
and an email; a self-hosted n8n that quietly stopped firing three weeks ago produces nothing at
all. Budget for monitoring the automation platform itself — which means the Uptime Kuma point
above applies here too.

## What the numbers change

Running everything simultaneously costs roughly **2 GB of RAM** before traffic. That's not the
"$5 VPS replaces $50/month of SaaS" story these lists usually tell. A more honest reading:

- **Vaultwarden and Uptime Kuma (119 MB combined) are close to free.** If you already run a
  server, adding them costs you setup time and nothing else. This is where self-hosting is
  unambiguously good.
- **Shlink at 296.5 MB deserves a moment's thought** relative to how simple the job is.
- **n8n and Plausible are infrastructure decisions**, not additions. Each wants most of a small
  VPS to itself.

## When self-hosting is the wrong answer

The honest version of this tradeoff: **you are not eliminating a cost, you are converting a
predictable monthly fee into unpredictable, unpaid, poorly-timed work.** That's a good trade in
some cases and a bad one in others.

Self-hosting tends to be wrong when:

- **You don't already run a server.** The first tool has to absorb the entire cost of learning
  reverse proxies, TLS renewal, backups, and update hygiene. One $8/month subscription rarely
  justifies that.
- **Downtime has real consequences.** If customers or teammates notice when it breaks, you've
  taken on an on-call obligation with no rotation and no backup.
- **It's your only copy of something irreplaceable.** Password vaults and anything without an
  export path deserve more caution than a monitoring dashboard.
- **You won't do updates.** An unpatched public-facing service is worse than the SaaS you were
  avoiding. Self-hosting is a subscription paid in attention rather than money.

It tends to be right when: you already run a server for other reasons, the tool is
internal-facing, an outage is annoying rather than costly, and you specifically want the data on
your own hardware.

That's a narrower set of cases than most self-hosting writeups admit — but within it, and
especially at the Vaultwarden/Uptime Kuma end of the resource curve, the economics are genuinely
good.

## Reproduce it

The measurement harness is committed:
[`selfhosted_bench.py` and `plausible_load.sh`](https://github.com/horushermezzz-byte/devtool-digest/tree/main/bench),
along with the raw JSON, in the same harness directory as the [SSG build benchmark](/devtool-digest/posts/hugo-eleventy-astro-arm-benchmark/).
If your numbers differ — especially on x86, or with real traffic —
[open an issue](https://github.com/horushermezzz-byte/devtool-digest/issues). Idle RAM on an
empty instance is the floor, not the steady state, and I'd like to collect loaded numbers.
