# SSG build benchmark — reproducible harness

Scripts and raw results behind
[*Hugo vs Eleventy vs Astro: I Benchmarked All Three on ARM*](https://horushermezzz-byte.github.io/devtool-digest/posts/hugo-eleventy-astro-arm-benchmark/).

## Files

| File | What it is |
|---|---|
| `gen_corpus.py` | Generates N identical markdown pages. **Fixed seed (1337)** — same corpus on every machine. |
| `benchmark.py` | Single-size benchmark, 7 cold + 7 warm runs, min/median/mean/max. |
| `scaling.py` | Multi-size benchmark across N = 100/300/1000/2500. The one the article's charts use. |
| `results.json` | Raw output of `benchmark.py` at 300 pages. |
| `scaling.json` | Raw output of `scaling.py` — every individual run time. |
| `fit.json` | Least-squares fit: fixed startup vs marginal per-page cost. |

## Reproducing

Requires Hugo extended, Node, and Python 3.11+.

```sh
# 1. build the three sites (see article for the minimal templates)
# 2. generate a corpus and benchmark across sizes
python3 gen_corpus.py 2500 ./content
RUNS=3 python3 scaling.py 100,300,1000,2500
```

`scaling.py` wipes each generator's output and cache before **every** timed run, and discards
one warm-up run per generator per size so the first measured run isn't penalised.

## Measured on

- 6-core `aarch64` QEMU VM (CPU implementer `0x61` = Apple Silicon host), 3.3 GB RAM
- Ubuntu 26.04.1 LTS, kernel 7.0.0
- Hugo `v0.166.0+extended`, Eleventy `3.1.6`, Astro `5.18.2`, Node `v26.9.0`

## Results differ on your machine?

Expected — especially on x86, where the gaps should narrow. Please
[open an issue](https://github.com/horushermezzz-byte/devtool-digest/issues) with your
`scaling.json` and CPU model. Collecting cross-architecture data is the point.
