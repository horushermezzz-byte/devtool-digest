---
title: "npm 12 Blocks Install Scripts: Which Native Packages Actually Break"
date: 2026-09-21T10:30:00+02:00
draft: false
tags: ["npm", "nodejs", "supply-chain", "native-modules", "arm64"]
summary: "npm 12 turns install scripts off by default. I installed eight native packages under a real block and loaded every one: five work untouched, three break. The split isn't random — it's whether the package ships prebuilt binaries or compiles at install time. Includes the control that proved my first run measured nothing."
---

npm 12 shipped in August 2026 with `allowScripts` defaulting to off. Dependency `preinstall`,
`install`, and `postinstall` scripts no longer run unless you allow them — and, importantly,
neither do **implicit node-gyp builds**.

The standard warning is that this breaks native modules. So: which ones, actually?

I installed eight packages under a real block on ARM64, then `require()`d each one and called
something real. **Five work untouched. Three break.** The split is not arbitrary.

## Results

| Package | Survives block? | Native binaries shipped | Mechanism |
|---|---|---|---|
| `ws` | ✅ | — | pure JS, no native code |
| `esbuild` | ✅ | — | optional platform dependency |
| `sharp` | ✅ | 1 prebuilt | optional platform dependency |
| `better-sqlite3` | ✅ | 8 prebuilt | bundled prebuilds |
| `bcrypt` | ✅ | 10 prebuilt | bundled prebuilds |
| `canvas` | ❌ | none | compiles at install |
| `sqlite3` | ❌ | none | compiles at install |
| `node-sass` | ❌ | none | compiles at install |

**Method:** each package installed with `npm install --ignore-scripts` into a clean temp project,
then loaded and exercised — `sharp` encodes a PNG, `bcrypt` hashes, `better-sqlite3` creates a
table and inserts. An install that "succeeds" while leaving an unloadable module is a failure, so
install exit code alone isn't the test. npm 11.19.1, Node v26.9.0, 6-core aarch64, Ubuntu 26.04.

## The rule that predicts it

Every survivor ships **precompiled binaries**; every casualty **compiles at install time**.

There are two flavours of surviving, and the difference matters if you're packaging something:

**Optional platform dependencies** — the package depends on a set of per-platform packages, and
npm installs only the one matching your machine. `sharp`'s `optionalDependencies` lists
`@img/sharp-linux-arm64`, `@img/sharp-darwin-arm64`, `@img/sharp-linux-x64` and so on. Nothing
executes at install; npm just resolves the right binary. `esbuild` uses the same pattern with
`@esbuild/linux-arm64`.

**Bundled prebuilds** — the package ships binaries for many platforms inside the tarball and picks
one at require-time, typically via `node-gyp-build` or `prebuild-install`. `bcrypt` carries 10
`.node` files; `better-sqlite3` carries 8.

The casualties have neither. Under a block, `canvas` installs "successfully" and then:

```
Error: Cannot find module '../build/Release/canvas.node'
Require stack:
- node_modules/canvas/lib/bindings.js
```

`build/Release/` is where node-gyp puts compiled output. The directory is empty because the
compile step never ran. `sqlite3` fails the same way through its `bindings` shim.

`node-sass` is different and worth calling out separately:

```
Error: Node Sass does not yet support your current environment:
Linux Unsupported architecture (arm64) with Unsupported runtime (147)
```

That's not really about install scripts — node-sass has been deprecated since 2020 and has no
prebuild for Node 26 on ARM. With scripts allowed it compiles from source and works; with scripts
blocked there's nothing to fall back on. If you're still on `node-sass`, npm 12 is the smaller of
your problems. Use `sass` (pure JS, Dart-compiled) instead.

## The control that invalidated my first run

My first pass tested all eight under npm's *default* behaviour and concluded everything worked,
including `canvas` and `sqlite3`. That result was wrong, and it's worth showing why.

npm 11.19 **warns** about un-approved install scripts:

```
npm warn install-scripts 3 packages have install scripts not yet covered by allowScripts:
  esbuild@0.27.7   (postinstall: node install.js)
  sharp@0.34.5     (install: node install/check.js || npm run build)
  bcrypt@6.0.0     (install: node-gyp-build)
```

Reading that as "scripts were blocked" is the trap. It's a warning about npm 12's *future*
behaviour — the scripts still run.

I caught it because `canvas` and `sqlite3` had `build/Release/*.node` files after install. That
path only exists if node-gyp compiled something, which means the scripts ran. So I built a probe:
a local package whose `postinstall` writes a marker file.

```
default          script_executed=True   warned=True
--ignore-scripts script_executed=False  warned=False
```

Unambiguous. Under npm 11's default the script executes *and* warns. My first run measured npm's
warning text, not a block.

The re-run used `--ignore-scripts`, with scripts-allowed as a control to prove the block was the
cause rather than the architecture or Node version:

| Package | Scripts allowed | Scripts blocked | Cause |
|---|---|---|---|
| `canvas` | ✅ works (1 compiled) | ❌ breaks | the block |
| `sqlite3` | ✅ works (1 compiled) | ❌ breaks | the block |
| `node-sass` | ✅ works (1 compiled) | ❌ breaks | the block |
| `bcrypt` | ✅ works (0 compiled) | ✅ works | unaffected |

Works-with, fails-without, on the same machine and Node version: the block is the cause.

## What to do

**Find out where you stand** — run this in your project today:

```sh
npm install --ignore-scripts
```

If everything still loads, npm 12 costs you nothing. If something fails, you've found it before
the upgrade did.

**For anything that breaks**, in order of preference:

1. **Switch to a package that ships prebuilds.** `sqlite3` → `better-sqlite3` (8 prebuilds, faster
   API). `node-sass` → `sass`. `canvas` → `@napi-rs/canvas`, which uses the optional-platform-dep
   pattern. I installed and ran all three under `--ignore-scripts` on this box: `@napi-rs/canvas`
   encoded a PNG, `sass` compiled a stylesheet, `better-sqlite3` created a table. All work.
2. **Allow it explicitly**, if you've reviewed it and trust it:

   ```json
   {
     "allowScripts": {
       "canvas": true
     }
   }
   ```

   Verified working: `canvas` installs, compiles, and loads with this in `package.json`.

**One gotcha worth knowing.** If `package.json` declares `allowScripts`, it silently overrides your
`.npmrc`:

```
npm warn install-scripts .npmrc allow-scripts setting is being ignored
  because package.json declares its own allowScripts field
```

A repo-level `allowScripts` beats your machine-level config. If you've set a global policy and a
project ignores it, that's why.

## The honest summary

The "npm 12 breaks native modules" warning is **half true, and the half matters**. Native packages
that migrated to prebuilt binaries — which is most of the popular ones — are entirely unaffected.
Packages still compiling at install time break completely.

That's also the useful signal: a package still requiring a compile step in 2026 has not been keeping
up with the ecosystem, and `canvas`, `sqlite3`, and `node-sass` all have better-maintained
alternatives. The block is doing you a favour by finding them.

The harness and raw JSON are in
[`bench/`](https://github.com/horushermezzz-byte/devtool-digest/tree/main/bench) — including the
marker-file probe, so you can check the control yourself rather than take my word that the first
run was wrong.

This is the same box I used to [benchmark Hugo, Eleventy and Astro](/devtool-digest/posts/hugo-eleventy-astro-arm-benchmark/)
and to [measure what self-hosted tools cost to run](/devtool-digest/posts/self-hosted-saas-alternatives/).

*Tested on ARM64, where prebuild coverage is thinner than x86. If a package survives here it will
almost certainly survive on x86 — but if you get a different result,
[open an issue](https://github.com/horushermezzz-byte/devtool-digest/issues).*
