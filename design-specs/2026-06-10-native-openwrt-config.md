<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com> -->

# Native OpenWrt config for the REAC re-pacer rig

- **Date:** 2026-06-10
- **Status:** draft / proposed
- **Component:** router fabric (`reac1`/`reac2` GL-MT6000) + `reac-repacer` packaging

## Problem

The working rig is set up **imperatively** by `/root/reacN-restore.sh`, run at boot by
`/etc/init.d/reac-rig` (S99) and re-run by an `/etc/hotplug.d/iface/99-rerun-rc-local`
hack. That script does four jobs by hand:

1. ensures the `reactap` gretap tunnel + `reactap.11/12` sub-interfaces exist;
2. adds `reactap.11/12` and `lan1/2` to `br-lan` with `bridge vlan add … pvid untagged`;
3. installs an nftables **bridge** drop `reactap.X → lanX`;
4. launches the re-pacer (`--forward-only --port reactap.11:lan1 --port reactap.12:lan2 …`).

Why this is fragile:

- `bridge vlan add dev reactap.X vid X pvid untagged` on a **gretap sub-interface** is **not
  UCI-representable**, so `service network restart` rebuilds `br-lan` from UCI and silently
  **wipes** it — hence the hotplug-rerun hack (documented in `REAC-VERIFIED.md`).
- An OpenWrt apk **procd service** for the re-pacer was tried and **broke the rig**: its init
  ran `ip link set <port> nomaster`, pulling `reactap.X`/`lanX` out of `br-lan` and killing the
  raw relay. The daemon must **not** own topology.

## How the rig actually works (reference)

```
br-lan (vlan_filtering=1)
  VID 11 = REAC-A : lan1 (untagged/PVID access)   <-> reactap (carries VID 11 to peer)
  VID 12 = REAC-B : lan2                            <-> reactap (VID 12)
  VID 13 = REAC-C : lan3                            <-> reactap (VID 13)   [planned]
gretap "reactap" : point-to-point over the 5 GHz WDS underlay (192.168.10.1 <-> .2)

bridge  = raw L2 relay for EVERY direction over the tunnel
nft drop = removes ONLY the tunnel->stagebox direction (reactap.X -> lanX) at the bridge
re-pacer = re-delivers EXACTLY that dropped direction, de-jittered (--forward-only)
```

The split is the elegant part: the bridge does the cheap raw relay; the re-pacer replaces the
single latency-critical direction with a clock-paced one.

## Target: declarative, native

Rule of ownership: **the OS config owns the fabric; the procd daemon owns only the daemon.**

| Piece | Native mechanism |
|---|---|
| VLAN-filtering bridge + VID 11/12/13 | **already** `/etc/config/network` `device` + `bridge-vlan` — keep |
| `reactap` gretap tunnel | `config interface 'reactap'` `option proto 'gretap'` `option tunlink 'lan'` `option peeraddr …` `option mtu '1500'` |
| REAC VLANs onto the tunnel | `reactap` as a **tagged trunk member** of `br-lan`: add to the bridge `ports`, and each `bridge-vlan` lists `reactap:t` (tagged) alongside `lanX:u*` |
| `reactap.X -> lanX` drop | declarative `/etc/nftables.d/10-reac.nft` (fw4 includes `*.nft`) — survives `service network restart` |
| the re-pacer | a **procd service** (UCI + init) that reads/writes the already-set-up ifaces and does **no** `nomaster`, no `ip link`, no `bridge vlan` |

Net result: delete `reacN-restore.sh`, `reac-rig`, and `99-rerun-rc-local`; survive
`service network restart`; ship it all as a small **`reac-rig` package** (network UCI snippet +
`/etc/nftables.d` file + the no-topology re-pacer procd service).

## The one genuine wrinkle (decide + TEST first)

Today the re-pacer reads `reactap.11` (a standalone gretap subif). In the **trunk model** the
VID-11 traffic lives inside `br-lan`; the natural per-VLAN handle is **`br-lan.11`**, not
`reactap.11`. So the open design decision:

- **Option A — trunk + `br-lan.X` input:** `reactap` tagged trunk in `br-lan`; re-pacer reads
  `br-lan.11`, writes `lan1`; nft drops the bridge's VID-11 `reactap→lan1` path. Fully native, but
  the re-pacer's **input interface changes** and must be validated.
- **Option B — keep `reactap.X` subifs, make them UCI bridge ports:** declare `reactap.11/12/13`
  as explicit bridge member devices with per-port PVID. Closer to today, but this is exactly the
  combination netifd does **not** round-trip cleanly — needs verification it isn't wiped on reload.

**Recommended:** prototype **Option A** on one router and confirm, byte-for-byte, that the
re-pacer behaves identically reading `br-lan.11` vs `reactap.11` (lock, occupancy, de-jittered TX
onto a `br-lan` VID access port — which already works today). This is the single thing that must
be proven before committing.

## Migration plan

1. **Spike (one router, off-show):** add the native gretap + trunk + `nftables.d` drop + the
   no-topology procd service alongside the existing script; stop the script; verify REAC links
   `2/2`, clean de-jittered audio, and **survives `service network restart`** (the old failure).
2. **Reconcile the re-pacer init:** drop the `nomaster`/`tc` block entirely (set the topology in
   config, not the daemon); keep the validated flags (`--pll --forward-only --servo-clamp-ppm 0
   --prefill-ms 70`, per-port cpu/bcast_only) + the new fast-detect/transition-mute defaults.
3. **Roll to both**, then **delete** `reacN-restore.sh`, `/etc/init.d/reac-rig`,
   `/etc/hotplug.d/iface/99-rerun-rc-local`.
4. **Package** as `reac-rig` (conffiles: the network snippet, the nft file) depending on
   `reac-repacer`; both installable via apk so a fresh router is one `apk add` away.

## Rollback

Keep `reacN-restore.sh` in place (just not auto-run) until step 1 is signed off by ear on the
rig. Reverting is: re-enable `reac-rig`, `service network restart`, done.

## Open questions / risks

- **Re-pacer input iface** (`br-lan.11` vs `reactap.11`) — the gating test above.
- **nft drop in the trunk model** must match the right direction *with VLAN tag* on the bridge
  forward hook (`iifname "reactap" oifname "lan1" vlan id 11 drop` or equivalent) — confirm it
  drops exactly one direction and nothing else.
- **MTU** must stay 1700 on `br-lan`/WDS and 1500 on `reactap` (gretap inner = 1496-byte REAC
  broadcast) — carry into the native config.
- **3rd port (REAC-C, VID 13/lan3)** is included from the start in the native config (the nft
  already drops `reactap.13→lan3`; only the bridge-vlan member + the re-pacer `--port` were
  missing in the script).
- **Raw TX on a `br-lan` access port** already works on this rig (verified) despite the generic
  "DSA drops raw TX on a bridge slave" caution — keep that assumption under test in the spike.
