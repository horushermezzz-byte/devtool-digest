---
title: "Setting Up a Full Dev Toolchain With No Root Access"
date: 2026-09-19T15:30:00+02:00
draft: false
tags: ["linux", "devops", "no-root", "arm64", "uv"]
summary: "A locked-down Ubuntu 26.04 ARM64 box with no sudo, PEP 668 enforced, and no ensurepip. Here's what actually worked to get gh, Hugo, Node, Python, and a headless browser running — including the standard advice that failed."
---

Shared hosting, locked-down corporate laptops, CI containers, someone else's VM — sooner or later you get handed a Linux box where `sudo` isn't yours and `apt install` is not an option.

Most guides handle this with "just use a virtualenv" or "install to `~/.local/bin`." Both are right in outline and both hit walls the guides don't mention. This is a log of what actually worked on a real locked-down box, including the parts where the standard advice failed outright.

**The environment:**

```
Ubuntu 26.04.1 LTS (Resolute Raccoon)
aarch64 (ARM64), 6 cores, 3.3 GB RAM
sudo: interactive authentication required  -> unavailable
no docker, no podman
```

## First: find out exactly how locked down you are

Before installing anything, establish what you're working with. These four checks determine every decision that follows.

```sh
sudo -n true 2>&1                     # -n = never prompt; fails immediately if no sudo
uname -m                              # aarch64 vs x86_64 decides which binaries you can use
ls /usr/lib/python3*/EXTERNALLY-MANAGED   # if present, PEP 668 blocks pip
[ -w "$(npm config get prefix)/lib/node_modules" ] && echo writable || echo needs-sudo
```

The `-n` flag on that first command matters: without it, `sudo` hangs waiting for a password you may not have.

On this box: no sudo, ARM64, PEP 668 enforced, and — luckily — an npm prefix already pointed at `$HOME/.local`.

## The wall: PEP 668 with no escape hatch

Python was the first real problem. Since PEP 668, distributions mark system Python as externally managed to stop pip from fighting the OS package manager:

```sh
$ ls /usr/lib/python3*/EXTERNALLY-MANAGED
/usr/lib/python3.14/EXTERNALLY-MANAGED
```

On this box it was more thorough than that — system Python shipped with no pip at all (`No module named pip`). Either way you land in the same place.

The universal advice is *use a virtual environment*. Reasonable. Except:

```sh
$ /usr/bin/python3 -m venv testvenv
The virtual environment was not created successfully because ensurepip is not
available.  On Debian/Ubuntu systems, you need to install the python3-venv
package using the following command.

    apt install python3.14-venv
```

Read that carefully — **the suggested fix requires the thing you don't have.** Debian and Ubuntu ship Python with `ensurepip` split into a separate package, so on a minimal image, `venv` is broken out of the box and the error message helpfully tells you to run `apt install`.

This is the dead end most "no root Python" guides walk you into. `pip` is blocked, `venv` can't bootstrap, and `ensurepip` isn't there:

```sh
$ /usr/bin/python3 -m ensurepip --version
/usr/bin/python3: No module named ensurepip
```

## What actually works: uv

[uv](https://github.com/astral-sh/uv) (from Astral, the Ruff people) is a single static-ish binary that bundles its own package resolution and doesn't need `ensurepip` at all. Its installer writes to `~/.local/bin` and never asks for root:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```
downloading uv 0.12.17 aarch64-unknown-linux-gnu
installing to /home/horus/.local/bin
  uv
  uvx
everything's installed!
```

It creates working virtual environments where stdlib `venv` couldn't:

```sh
$ uv venv myproject
Using CPython 3.11.16
Creating virtual environment at: myproject

$ uv pip install --python myproject/bin/python requests
+ requests==2.34.2
```

The part that genuinely surprised me — **uv will fetch and install a whole Python interpreter into your home directory, no root involved:**

```sh
$ uv python install 3.13
Downloading cpython-3.13.15-linux-aarch64-gnu (27.9MiB)
Installed Python 3.13.15 in 1.24s

$ uv venv --python 3.13 myproject313 && myproject313/bin/python -V
Python 3.13.15
```

The system had 3.14 and the venv default was 3.11. Neither constrained anything. If you take one thing from this article: **on a box without root, `uv` isn't a nicer pip, it's the difference between having Python tooling and not.**

> A note on `curl | sh`: you're executing a remote script unread. For a vendor you're choosing to trust it's a reasonable tradeoff, but read it first (`curl -LsSf https://astral.sh/uv/install.sh | less`) or pin a release binary from GitHub if your threat model is stricter.

## CLI tools: prefer static binaries

Most Go and Rust tools ship self-contained release binaries. Installing them without root is just untar-to-`~/.local/bin`:

```sh
mkdir -p ~/.local/bin
cd /tmp
curl -sL -o gh.tar.gz https://github.com/cli/cli/releases/download/v2.101.0/gh_2.101.0_linux_arm64.tar.gz
tar xzf gh.tar.gz
cp gh_2.101.0_linux_arm64/bin/gh ~/.local/bin/gh
chmod +x ~/.local/bin/gh
```

Check what you're getting, because it predicts whether it'll run on a minimal system:

```sh
$ file ~/.local/bin/gh | grep -o 'statically linked'
statically linked

$ ldd ~/.local/bin/hugo | head -3
        libstdc++.so.6 => /usr/lib/aarch64-linux-gnu/libstdc++.so.6
        libm.so.6 => /usr/lib/aarch64-linux-gnu/libm.so.6
```

`gh` is a static Go binary — zero dependencies, runs anywhere with a matching kernel and arch. Hugo *extended* is dynamically linked against `libstdc++` (it embeds a C++ SASS compiler). On this box those libraries were present. On a leaner container they might not be, and without root you can't install them — in that case use non-extended Hugo, which drops the SASS support but links against far less.

**Rule of thumb: static Go/Rust binaries are nearly always safe. Dynamically linked ones need an `ldd` check before you rely on them.**

## The ARM64 tax

If `uname -m` says `aarch64`, expect a subset of tooling to simply not exist for you. A concrete example from this setup — installing a headless browser for automated testing:

```
✗ Chrome for Testing does not provide Linux ARM64 builds.
  Install Chromium from your system package manager instead:
    sudo apt install chromium-browser
```

Both options were closed: no ARM64 build upstream, and the fallback needs root. The workaround was noticing that Playwright *does* publish ARM64 Chromium builds, and pointing the tool at that binary instead:

```sh
npx -y playwright install chromium   # downloads to ~/.cache/ms-playwright, no root
export AGENT_BROWSER_EXECUTABLE_PATH=~/.cache/ms-playwright/chromium-*/chrome-linux-arm64/chrome
```

Note that `playwright install --with-deps` would have failed — `--with-deps` shells out to `apt`. Dropping that flag installs the browser and skips the system packages.

Then a second wall, which anyone running Chromium in a container or VM will hit:

```
FATAL:zygote_host_impl_linux.cc(129)] No usable sandbox! If you are running on
Ubuntu 23.10+ ... that has disabled unprivileged user namespaces with AppArmor
```

Ubuntu 23.10+ restricts unprivileged user namespaces, which Chromium's sandbox needs. The documented fix is an AppArmor profile change — root again. The practical fix without root:

```sh
export AGENT_BROWSER_ARGS="--no-sandbox"
```

Understand the tradeoff before copying that. `--no-sandbox` removes a real security boundary. It's defensible for a browser you point at your own local site in a disposable VM; it is not something to run against untrusted pages on a machine you care about.

## The PATH mistakes I made

This is where I burned the most time, and it had nothing to do with permissions.

**Mistake 1: appending to `~/.bashrc` without checking.** Each install step tacked on another line. The result in a long-lived session:

```sh
$ echo $PATH | tr ':' '\n' | wc -l           # 44
$ echo $PATH | tr ':' '\n' | sort -u | wc -l # 16
```

Forty-four entries, sixteen unique — and the number climbs every time something re-sources your shell config. Harmless to correctness, but it makes `PATH` unreadable exactly when you're debugging which binary wins.

**Mistake 2: writing to the wrong file entirely.** Ubuntu's default `~/.profile` already contains:

```sh
# set PATH so it includes user's private bin if it exists
if [ -d "$HOME/.local/bin" ] ; then
    PATH="$HOME/.local/bin:$PATH"
fi
```

It was handled before I started. Every line I added was pure duplication. **Check `~/.profile` before adding a PATH export** — on Debian/Ubuntu, `~/.local/bin` is almost certainly already there.

**Mistake 3 — the one that actually breaks things:** `~/.bashrc` starts with

```sh
# If not running interactively, don't do anything
case $- in
    *i*) ;;
      *) return;;
esac
```

Non-interactive shells return before reaching your exports. So PATH set in `.bashrc` works when you type commands, and vanishes for cron jobs, `ssh host 'cmd'`, and scripts run with `#!/bin/sh`:

```sh
$ env -i PATH=/usr/bin:/bin sh -c 'command -v hugo'
-> hugo NOT FOUND
```

That's the classic "works in my terminal, fails in cron" bug. Environment for non-interactive use belongs in `~/.profile` (login shells) or explicitly in the crontab:

```cron
PATH=/home/youruser/.local/bin:/usr/bin:/bin
0 * * * * hugo --source ~/mysite
```

Verify with a clean environment rather than trusting your current shell, which is already polluted:

```sh
env -i HOME=$HOME TERM=xterm bash -lc 'command -v gh hugo uv node'
```

## What ended up working

| Tool | Method | Root needed |
|---|---|---|
| gh 2.101.0 | static ARM64 tarball → `~/.local/bin` | no |
| Hugo extended 0.166 | release tarball (`ldd`-checked) | no |
| Node 26 / npm | prefix already at `~/.local` | no |
| Python 3.13 | `uv python install` | no |
| Python packages | `uv venv` + `uv pip` | no |
| Chromium | Playwright ARM64 build + `--no-sandbox` | no |

Everything needed for a full static-site publishing pipeline — build, git, GitHub API, headless browser verification — with no administrative access at all.

## The short version

1. Probe first: `sudo -n`, `uname -m`, `EXTERNALLY-MANAGED`, npm prefix.
2. `uv` solves Python on locked-down boxes, including installing interpreters.
3. Prefer static Go/Rust binaries; `ldd` anything dynamic before committing.
4. On ARM64, expect gaps — and check whether another vendor ships the build you need.
5. Put PATH in `~/.profile`, not `~/.bashrc`, and check it isn't already there.
6. Verify with `env -i ... bash -lc`, not your current shell.

The recurring theme: the error messages confidently tell you to run `apt install`, and that advice is useless here. Almost always there's a user-space path that works — it's just not the one in the error message.

*Hit a no-root wall this doesn't cover? [Open an issue](https://github.com/horushermezzz-byte/devtool-digest/issues) — I'd rather extend this with real cases than guess.*
