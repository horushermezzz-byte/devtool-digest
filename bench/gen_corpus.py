#!/usr/bin/env python3
"""Generate N identical markdown pages for a cross-SSG build benchmark.

Identical INPUT is the whole point: any build-time difference must come from the
generator, not from content drift. Same frontmatter keys, same body, same
deterministic pseudo-random text (fixed seed), written once and copied verbatim
into each SSG's content directory.
"""
import os, random, sys, shutil

N = int(sys.argv[1]) if len(sys.argv) > 1 else 300
OUT = sys.argv[2] if len(sys.argv) > 2 else "/home/horus/bench/content"

WORDS = ("deploy pipeline latency cache render static markup build artifact "
         "container runtime kernel throughput payload compile bundle module "
         "dependency resolver manifest checksum registry rollback").split()

random.seed(1337)  # deterministic: same corpus every run, on every machine

shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(OUT, exist_ok=True)

def para(n):
    return " ".join(random.choice(WORDS) for _ in range(n)).capitalize() + "."

total = 0
for i in range(N):
    body = []
    body.append(f"# Post {i}\n")
    body.append(para(45) + "\n")
    body.append("## Background\n")
    body.append(para(60) + "\n")
    body.append("```js\nconst x = " + str(i) + ";\nexport default function () { return x * 2; }\n```\n")
    body.append("## Detail\n")
    body.append(para(55) + "\n")
    body.append("| key | value |\n|---|---|\n| id | " + str(i) + " |\n| kind | bench |\n")
    body.append(para(40) + "\n")
    text = "\n".join(body)

    fm = (
        "---\n"
        f'title: "Benchmark Post {i}"\n'
        f"date: 2026-01-{(i % 28) + 1:02d}\n"
        f'tags: ["bench", "group{i % 10}"]\n'
        f'summary: "Synthetic post {i} for cross-generator build benchmarking."\n'
        "---\n\n"
    )
    doc = fm + text
    total += len(doc)
    with open(os.path.join(OUT, f"post-{i:04d}.md"), "w") as fh:
        fh.write(doc)

print(f"{N} pages -> {OUT}")
print(f"corpus: {total:,} bytes ({total/N:,.0f} bytes/page avg)")
