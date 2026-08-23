<!-- SPDX-License-Identifier: GPL-3.0-or-later
     Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com> -->

# Deploying the standard reac-rig config (apk build + gretap cutover)

**Date:** 2026-06-13 · **Author:** Pau Aliagas <linuxnow@gmail.com>

> **NOTE (2026-06-13):** this apk/gretap cutover was **deliberately not deployed**.
> The rig runs the hand-tuned `reacN-restore.sh` scripts instead — see
> [`rig-parked-state.md`](rig-parked-state.md) for the actual,
> ear-validated parked configuration. This doc is retained for the future
> clean-room apk build (the apks remain staged on reac1 at `/root/reac-apks/`).

## 1. Building the apks

Built with the in-repo harness (OpenWrt 25.12.4 mediatek/filogic cross-SDK inside
a Fedora container). On a Fedora host with podman:

```sh
cd reac-aes67
podman run --rm --security-opt label=disable \
  -v "$PWD/.build":/work -v "$PWD":/repo:ro fedora:42 bash /work/build-apk.sh
# artefacts -> .build/out/*.apk
```

> The `--security-opt label=disable` is required on SELinux hosts (else the bind
> mount is unreadable: `bash: /work/build-apk.sh: Permission denied`).

Produces: `reac-repacer` (daemon + procd init), `reac-rig` (declarative gretap
fabric + ETF qdisc + role/peer uci-defaults), `luci-app-reac-repacer` (UI), plus
`reac-aes67` + its LuCI app (the separate AES67 bridge, not part of the re-pace rig).

Staged on reac1 at **`/root/reac-apks/`** this session (NOT installed — see §3).

## 2. What reac-rig does

Moves the fabric from the ad-hoc direct-WDS-bridge setup (the `/root/reac1-restore.sh`
runtime script) to a **declarative gretap tunnel**: `network.reactap` (gretap, .1↔.2
peer), 8021q VLANs `reactap.11/12/13`, merged idempotently into the live br-lan; the
L2 return-path drop in `nftables.d`; and an **ETF qdisc on every REAC OUT port** so the
daemon's `--etf` actually times egress (tries HW offload = the i226 fix, falls back to
software). Fingerprint-free: role (`bcast_only`) and gretap peer are filled on-device
at install from the wifi AP/STA mode and `network.lan.ipaddr`.

## 3. Why it was STAGED, not auto-installed

reac-rig is a **2-node** migration (both reac1=.1 and reac2=.2 must run it; a
`network reload` activates the gretap). Installing on reac1 **alone, live**, would
(a) leave a half-formed gretap with no peer and (b) start a second re-pacer that
collides with the running `reac-repacer-clk`. So it is a **deliberate cutover**, done
off show-prep — not an in-place live upgrade.

## 4. Cutover procedure (both routers, when ready)

On **reac1 and reac2**:

```sh
apk add /root/reac-apks/reac-repacer-0.2.2-r1.apk \
        /root/reac-apks/reac-rig-0.1.0-r1.apk \
        /root/reac-apks/luci-app-reac-repacer-0.2.1-r1.apk
# postinst uci-defaults: 97 fills bcast_only from wifi mode (ap=0 / sta=1);
# 98 merges gretap + reactap.11/12/13 + br-lan members (idempotent);
# 99 fills gretap .1/.2 peer from network.lan.ipaddr.

pkill reac-repacer-clk            # stop the ad-hoc daemon (keep restore.sh as fallback)
/etc/init.d/network reload        # activate the gretap fabric
/etc/init.d/reac-rig restart      # launch /usr/bin/reac-repacer + setup_etf (ETF qdisc per lanN)
```

Verify: `logread | grep reac`, `tc qdisc show dev lan1` (etf present), the boxes link.
If a box stays unlinked after the daemon is steady, **replug the stagebox** once to reset
its link FSM.

## 5. Notes / gotchas

- **Version**: `reac-repacer-0.2.2-r1` is already installed at the same version (older
  binary). Use `apk add --reinstall` to force this fresh build, or bump `PKG_RELEASE`/
  `PKG_VERSION` to 0.2.3 before a real release so apk upgrades cleanly.
- **ETF is software-only on the GL-MT6000** (mt7531/mtk GMAC: no offload, no PTP — see
  `REAC-REPACE-MASTER-CLOCK-LIMIT.md`). It is the correct, forward-ready config (it
  hardware-offloads on an i226 box) but does NOT cure the master-side granularity;
  keep the M-5000 leg wired until the i226 hardware.
- The current live rig still runs the ad-hoc `reac-repacer-clk` + `/root/reac1-restore.sh`
  (now etf-on-all-lanN). It works (B box transport flows); a stuck box link FSM after
  heavy testing is cleared by a single stagebox replug.
