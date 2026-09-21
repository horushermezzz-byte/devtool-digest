---
title: "Rootless Docker Fails on Ubuntu with \"failed to reexec\" — Diagnosing It Properly"
date: 2026-09-21T09:00:00+02:00
draft: false
tags: ["docker", "rootless", "apparmor", "ubuntu", "containers", "linux"]
summary: "Rootless Docker and Podman both die with a re-exec error on Ubuntu 24.04+ — while user namespaces demonstrably work. Here's the kernel log line that identifies the real cause, a two-command test that tells you whether namespaces or exec is blocked, and why the popular sysctl fix is the wrong one."
---

Installing rootless Docker on Ubuntu 26.04 gets you this:

```
[rootlesskit:parent] error: failed to start the child: fork/exec /proc/self/exe: permission denied
[ERROR] RootlessKit failed, see the error messages and https://rootlesscontaine.rs/getting-started/common/
```

Podman, on the same box, fails differently but for the same reason:

```
Error: fatal error, invalid internal status, unable to create a new pause process:
cannot re-exec process
```

Both messages point at process execution. Both are misleading — and the internet's most common
answer to them turns off a security feature you probably want to keep.

## The trap: user namespaces are working fine

The natural first assumption is that unprivileged user namespaces are blocked. Ubuntu 23.10
introduced a restriction on exactly that, so it fits.

It's wrong, and you can prove it in one command:

```sh
$ unshare --user --map-auto echo OK
OK
```

That creates an unprivileged user namespace and maps UIDs into it. It works. Namespaces are not
the problem.

Here's the part that makes this confusing, though — the *other* form fails:

```sh
$ unshare --user -r echo OK
unshare: write failed /proc/self/uid_map: Operation not permitted

$ unshare --user --map-root-user echo OK
unshare: write failed /proc/self/uid_map: Operation not permitted
```

Same flag family, opposite results. The difference:

- `-r` / `--map-root-user` writes `/proc/self/uid_map` **directly** — blocked.
- `--map-auto` shells out to the **setuid helpers** `newuidmap`/`newgidmap`, which hold
  `CAP_SETUID` and write the map on your behalf — allowed.

So if you test with `unshare -r`, you conclude namespaces are blocked and start disabling
security settings. If you test with `--map-auto`, you learn namespaces are fine and the real
problem is elsewhere. **Which command you happen to type determines which conclusion you reach.**

I confirmed the mapping path independently with a small fork/`newuidmap` probe — parent maps the
child from `/etc/subuid`, child reports its identity:

```
child: inside userns uid=0 gid=0
newuidmap rc=0
newgidmap rc=0
RESULT: userns + newuidmap/newgidmap mapping both work
```

Namespaces: working. Mapping: working. Docker: still broken.

## The actual cause, from the kernel log

Tool-level error messages were a dead end. The kernel knows exactly what it denied:

```sh
sudo grep -i "apparmor.*DENIED" /var/log/kern.log | tail -3
```

```
apparmor="DENIED" operation="exec" class="file"
  info="Failed name lookup - disconnected path" error=-13
  profile="unprivileged_userns" name="/proc/self/exe"
  comm="rootlesskit" requested_mask="x" denied_mask="x"
```

And for Podman, the identical denial:

```
apparmor="DENIED" operation="exec" class="file"
  info="Failed name lookup - disconnected path" error=-13
  profile="unprivileged_userns" name="/proc/self/exe"
  comm="podman" requested_mask="x" denied_mask="x"
```

Everything is in there:

- **`profile="unprivileged_userns"`** — Ubuntu confines processes that create unprivileged user
  namespaces into a restrictive AppArmor profile. Creating the namespace is permitted; what you
  may do *inside* it is not unrestricted.
- **`operation="exec"`, `name="/proc/self/exe"`** — the denied action is re-executing the
  process's own binary.
- **`info="Failed name lookup - disconnected path"`** — the profile can't resolve `/proc/self/exe`
  to a path it's willing to authorise, so it refuses.

Both RootlessKit and Podman set up their namespace by re-executing themselves via
`/proc/self/exe`. That single pattern is what's blocked — which is why two different tools produce
two different error strings for one root cause.

## The fix that's wrong, and the fix that's right

Search the error and the top result is usually:

```sh
# DON'T
sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
```

That works. It also **disables the restriction for every process on the system**, permanently if
you persist it to `/etc/sysctl.d/`. You've removed a hardening feature that exists because
unprivileged user namespaces have a long history of local privilege escalation CVEs — to run one
container runtime.

The [official Docker troubleshooting docs](https://docs.docker.com/engine/security/rootless/troubleshoot/)
give the narrow version: an AppArmor profile that unconfines **one binary**, nothing else.

```sh
cat <<EOT | sudo tee /etc/apparmor.d/home.horus.bin.rootlesskit
abi <abi/4.0>,
include <tunables/global>

/home/horus/bin/rootlesskit flags=(unconfined) {
  userns,
  include if exists <local/home.horus.bin.rootlesskit>
}
EOT
sudo systemctl restart apparmor.service
```

Two things to adjust: the **path must match your actual binary** (`$HOME/bin/rootlesskit` for the
install-script route, `/usr/bin/rootlesskit` for the `.deb`), and the **filename is the path with
`/` replaced by `.`, minus the leading slash**. Docker's docs derive it mechanically:

```sh
filename=$(echo $HOME/bin/rootlesskit | sed -e 's@^/@@' -e 's@/@.@g')
```

Get the filename wrong and AppArmor silently doesn't apply it — same error, no clue why.

This is the entire difference between the two approaches: **one unconfines a single binary you
chose, the other unconfines everything.**

## It works immediately afterward

No reboot. Straight after `systemctl restart apparmor.service`:

```
$ rootlesskit true && echo "rootlesskit userns: WORKS"
rootlesskit userns: WORKS

$ dockerd-rootless-setuptool.sh install --skip-iptables
[INFO] Installed docker.service successfully.
[INFO] To control docker.service, run: `systemctl --user (start|stop|restart) docker.service`

$ docker run --rm hello-world
Hello from Docker!
```

Verified properties on this box afterwards — a 6-core aarch64 VM, 3.3 GB RAM, Ubuntu 26.04.1:

| Property | Result |
|---|---|
| Docker version | 29.8.1 (client and server) |
| Daemon user | `horus` — **not root** |
| Storage driver | `overlayfs` (native, not fuse) |
| Port publishing | `-p 8080:80` → **HTTP 200** |
| Volume mounts | host ↔ container round-trip verified |
| Container identity | uid 0 inside, mapped to unprivileged user outside |

The daemon runs as your user. That's the whole point of rootless — a container escape lands on an
unprivileged account, not root.

With it working, I used this box to [measure what self-hosted tools actually cost to run](/devtool-digest/posts/self-hosted-saas-alternatives/)
— idle RAM, image sizes, and the widely-repeated Plausible RAM requirement that turned out to be wrong.

## If you use the .deb, none of this happens

Worth knowing before you follow a guide: `docker-ce-rootless-extras` installed via apt **ships the
AppArmor profile already**. The manual profile step exists only for the
`https://get.docker.com/rootless` script path, because a script writing into `/etc/apparmor.d/`
would need root — which the rootless installer deliberately doesn't take.

If you have the choice and you're on Ubuntu, the `.deb` skips this entire article.

## Dead ends, so you can skip them

I tried these. They don't work:

**Pre-creating the namespace so Podman doesn't have to.** The idea is sound — enter a userns with
`unshare --map-auto`, then tell Podman it's already configured:

```sh
unshare --user --map-auto --mount --propagation unchanged \
  env _CONTAINERS_USERNS_CONFIGURED=done podman info
```

Podman segfaults:

```
panic: runtime error: invalid memory address or nil pointer dereference
[signal SIGSEGV: segmentation violation]
go.podman.io/podman/v6/libpod.(*Runtime).hostInfo(...)
```

The env var makes it skip setup it still depends on — there's no pause process, and it
dereferences nil. Don't chase this.

**`unshare -r podman ...`** fails at the `uid_map` write before Podman even starts, for the
reasons in the first section.

**Podman has no equivalent quick fix here.** Docker's problem is one binary (`rootlesskit`) with
a documented profile. Podman re-execs `podman` itself, and there's no packaged profile for it on
this system. If you need containers today on Ubuntu 24.04+, rootless Docker is the shorter path.

## The general lesson

The tool's error message told me *what failed* (`fork/exec`). The kernel log told me *why*
(`profile="unprivileged_userns"`, `operation="exec"`). Those are different questions, and on
Linux the second one usually has a better answer source than the first.

When a container runtime, sandbox, or browser fails with a permission error that makes no sense
given your file permissions, check `kern.log` for AppArmor or SELinux denials **before** you
start changing sysctls. (For the wider problem of working on a box you don't own, see
[building a dev toolchain without root](/devtool-digest/posts/dev-toolchain-without-root/).) The denial names the profile, the operation, and the target — which is
usually enough to write a fix scoped to one binary rather than one that disables a subsystem.

*Hit this on a different distro or with a different runtime?
[Open an issue](https://github.com/horushermezzz-byte/devtool-digest/issues) — particularly if
you've found a working narrow profile for rootless Podman, which I couldn't.*
