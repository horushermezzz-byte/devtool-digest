#!/usr/bin/env python3
"""
Link integrity audit for DevTool Digest.

The affiliate layer is only trustworthy if it cannot be bypassed. This script
enforces that, and is meant to run before every commit.

Checks, in order of how badly they'd damage the site:

  1. UNDISCLOSED EARNINGS  — a partner domain linked with a tracking parameter
     via raw markdown, skipping the {{< aff >}} shortcode and therefore the
     automatic disclosure. This is the one that gets a site penalised by the
     FTC and de-indexed by Google. Hard failure.

  2. BARE PARTNER LINK     — a partner domain linked raw without tracking.
     Not dishonest, but it's unpaid traffic to a partner. Warning.

  3. STALE REGISTRY        — link_template still contains {{ID}} placeholders
     that never got substituted, or an id set with a template that has no
     {{ID}} slot. Hard failure: means links would be silently broken.

  4. ORPHAN DISCLOSURE     — the disclosure page promises a partner list; if a
     partner is enrolled it MUST appear there. Handled by shared registry, so
     this just verifies the registry parses.

Exit code 0 = clean, 1 = failure. Warnings never fail the build.
"""

import re
import sys
import glob
import os

try:
    import tomllib
except ModuleNotFoundError:  # py<3.11
    import tomli as tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = os.path.join(ROOT, "data", "partners.toml")
CONTENT = os.path.join(ROOT, "content")

# Params that signal "this link is monetised"
TRACKING = re.compile(r"[?&](id|kaid|refcode|ref|aff|affiliate|partner|utm_)", re.I)
# Markdown links + bare autolinks, but NOT ones already inside a shortcode call
MD_LINK = re.compile(r"\]\((https?://[^)\s]+)\)|<(https?://[^>\s]+)>")

failures, warnings = [], []


def load_registry():
    if not os.path.exists(REGISTRY):
        failures.append(f"registry missing: {REGISTRY}")
        return {}
    with open(REGISTRY, "rb") as fh:
        try:
            return tomllib.load(fh)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"registry does not parse: {exc}")
            return {}


def domain_of(url):
    m = re.match(r"https?://(?:www\.)?([^/?#]+)", url)
    return m.group(1).lower() if m else ""


def check_registry(reg):
    for key, p in reg.items():
        tpl = p.get("link_template", "")
        pid = (p.get("id") or "").strip()
        if pid and "{{ID}}" not in tpl:
            failures.append(
                f"[registry] {key}: id is set but link_template has no {{{{ID}}}} slot "
                f"— the affiliate id would never reach the URL"
            )
        if pid and "{{ID}}" in tpl and not p.get("url"):
            failures.append(f"[registry] {key}: missing fallback `url`")
        for field in ("name", "category", "url", "program", "incentive"):
            if not p.get(field):
                failures.append(f"[registry] {key}: missing required field `{field}`")


def check_content(reg):
    partner_domains = {domain_of(p.get("url", "")): k for k, p in reg.items() if p.get("url")}
    partner_domains.pop("", None)

    for path in glob.glob(os.path.join(CONTENT, "**", "*.md"), recursive=True):
        rel = os.path.relpath(path, ROOT)
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()

        in_fence = False
        for n, line in enumerate(lines, 1):
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue  # code samples are illustrative, not live links

            for m in MD_LINK.finditer(line):
                url = m.group(1) or m.group(2)
                dom = domain_of(url)
                key = partner_domains.get(dom)
                if not key:
                    continue
                if TRACKING.search(url):
                    failures.append(
                        f"[{rel}:{n}] raw tracking link to {key} bypasses the disclosure "
                        f"shortcode:\n      {url}\n      -> use: {{{{< aff {key} >}}}}text{{{{< /aff >}}}}"
                    )
                else:
                    warnings.append(
                        f"[{rel}:{n}] bare link to partner {key} earns nothing "
                        f"— consider {{{{< aff {key} >}}}}"
                    )


def main():
    reg = load_registry()
    check_registry(reg)
    check_content(reg)

    enrolled = [k for k, p in reg.items() if (p.get("id") or "").strip()]
    print(f"partners in registry : {len(reg)}")
    print(f"enrolled (id set)    : {len(enrolled) or 'none — all links render as plain links'}")
    if enrolled:
        print(f"                       {', '.join(sorted(enrolled))}")

    for w in warnings:
        print(f"WARN  {w}")
    for f in failures:
        print(f"FAIL  {f}")

    if failures:
        print(f"\n{len(failures)} failure(s) — commit blocked.")
        return 1
    print(f"\nclean{f' ({len(warnings)} warning(s))' if warnings else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
