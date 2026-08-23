# Source-fetching recipe for upstream feeds (keep the repo-based local build)

**Date:** 2026-05-31
**Status:** PLANNED — not yet implemented. Implement + verify with a real
OpenWrt SDK build next session, after the test suite passes. The tag `v0.1.0`
ships the current vendoring recipe; this lands afterward on `main`.
**Repo:** `FreeREAC/reac-aes67`
**Related:** [OpenWrt packaging + LuCI app design](2026-05-31-openwrt-luci-packaging-design.md)

## Goal

Make `openwrt/reac-aes67/Makefile` a **source-fetching** recipe (so it can be
submitted to the official OpenWrt `packages` feed, which downloads source from a
canonical URL + verifies a hash — it never vendors source), **without losing**
the current repo-based container build (`.build/build-apk.sh`).

The key is to use **one** recipe for both and switch only where the source comes
from, via OpenWrt's `USE_SOURCE_DIR` override. This also means the local build
exercises the *exact* recipe submitted upstream — no local/upstream drift.

## How it works

- Upstream feed / buildbot: the recipe fetches the source from the git tag
  (`PKG_SOURCE_VERSION`) and verifies `PKG_MIRROR_HASH`.
- Local container build: `make package/reac-aes67/compile USE_SOURCE_DIR=$REPO`
  rsyncs the working tree into `PKG_BUILD_DIR`, skipping the fetch + hash check.
  Picks up uncommitted changes; needs no network.

| | Local (`build-apk.sh`) | Upstream feed (buildbot) |
| --- | --- | --- |
| Source | working tree via `USE_SOURCE_DIR=$REPO` | git tag + `PKG_MIRROR_HASH` |
| Recipe | the same `Makefile` | the same `Makefile` |
| Network | none (uses the mount) | fetches the tag |

Note: inside `Build/*` and `install`, `./` is the **package directory** (where
the Makefile sits), not `PKG_BUILD_DIR`. Today `./src` and `./files` only exist
there because `build-apk.sh` copies them in. Once the source is fetched/rsynced,
everything must be referenced via `$(PKG_BUILD_DIR)/…`.

## Recipe changes (`openwrt/reac-aes67/Makefile`)

Add the source coordinates:

```make
PKG_SOURCE_PROTO:=git
PKG_SOURCE_URL:=https://github.com/FreeREAC/reac-aes67.git
PKG_SOURCE_VERSION:=<pinned commit SHA for the release>   # tag v$(PKG_VERSION) also works; SHA is more reproducible
PKG_MIRROR_HASH:=<sha256 of the mirrored tarball>
PKG_SOURCE:=$(PKG_NAME)-$(PKG_VERSION).tar.xz
```

- **Delete** the custom `Build/Prepare` — the default checkout (or the
  `USE_SOURCE_DIR` rsync) populates `PKG_BUILD_DIR` with the whole repo, so the
  existing `$(PKG_BUILD_DIR)/src/*.c` paths in `Build/Compile` already resolve.
- **Repoint `install`** from package-relative to source-relative:
  `./files/reac-aes67.config` → `$(PKG_BUILD_DIR)/openwrt/files/reac-aes67.config`
  (likewise the `.init` and the capabilities JSON).
- `Build/Compile` is otherwise unchanged (already uses `$(PKG_BUILD_DIR)/src`).

## `build-apk.sh` changes

- In "drop in our packages", copy **only** `openwrt/reac-aes67/Makefile` into
  `package/reac-aes67/` — no longer stage `src/` or `openwrt/files/`.
- Compile with the local-source override:
  `make package/reac-aes67/compile V=s -j"$(nproc)" USE_SOURCE_DIR="$REPO"`.

## LuCI app — no change

LuCI apps in the `luci` feed are packaged **in-tree** (their JS / menu / ACL
ship with the recipe, not fetched), so `build-apk.sh` keeps copying the whole
`openwrt/luci-app-reac-aes67/` directory as it does today. Only the C daemon
becomes source-fetching.

## Caveats

- `USE_SOURCE_DIR` skips the hash check — fine, it only matters on the real
  fetch path.
- `PKG_SOURCE_VERSION` / `PKG_MIRROR_HASH` must be refreshed on every release
  (a pinned commit SHA is the most reproducible choice for the upstream PR).
- The fetch path requires the **repo to be public** — a prerequisite for any
  official-feed submission anyway.

## Verification plan (do this before committing the change)

1. Run `.build/build-apk.sh` with `USE_SOURCE_DIR` against the working tree for
   both targets (`mediatek/filogic`, `ramips/mt7621`); confirm both apks build.
2. Confirm the daemon ELF + the UCI/init/capabilities files land correctly in
   the package (inspect with the SDK `apk` tool / `.pkgdir`).
3. Once the repo is public, compute `PKG_MIRROR_HASH` from the real fetch and
   confirm a clean (no-`USE_SOURCE_DIR`) build also succeeds.

## Then: upstream submission (separate follow-up)

With the source-fetching recipe verified and the repo public, submit:
- the daemon recipe → `openwrt/packages` under `sound/reac-aes67/`;
- the LuCI app → `openwrt/luci` under `applications/luci-app-reac-aes67/`.
