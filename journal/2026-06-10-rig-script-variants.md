<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com> -->

# REAC-over-WDS rig — script variants (kept reference)

Three ways to stand up the REAC-over-WiFi L2 fabric on the two GL-MT6000
routers. **Variant 1 is what runs today (working).** Variant 2 is the
standard/declarative migration (designed + apk-built, **not yet deployed**).
Variant 3 (VXLAN) is ruled out, kept for the record.

Fingerprint-free: rig IPs are written here as `<LOCAL>` / `<PEER>` (the
`.1`↔`.2` WDS pair); real values live only on the devices.

Fabric in one line: `br-lan` (vlan_filtering) maps **lan1=VID11 (REAC-A),
lan2=VID12 (REAC-B), lan3=VID13 (REAC-C)**; a **gretap `reactap`** over the
5 GHz WDS carries those VLANs router↔router; an **nft bridge drop**
`reactap.X→lanX` removes the kernel return path so the **re-pacer** is the
sole de-jittered deliverer tunnel→stagebox.

---

## Variant 1 — CURRENT (imperative, working)

Set up by hand at boot. Four moving parts:

- **`/etc/rc.local`** — REAC bridge tune (`multicast_snooping=0`, `stp=0`,
  MTU 1700 on br-lan/wifi), then **creates the gretap** `reactap` +
  `reactap.11/12/13` 8021q subifs, adds them to `br-lan` with
  `bridge vlan add dev reactap.X vid X pvid untagged`, sets mcast/bcast flood.
- **`/root/reacN-restore.sh`** — (re)adds `reactap.X`+`lanX` to `br-lan` with
  the right VID, installs the **nft bridge table** dropping `reactap.X→lanX`,
  then launches the re-pacer:
  `reac-repacer --forward-only [--bcast-only on STA] --port reactap.11:lan1
  --port reactap.12:lan2 --pll --servo-clamp-ppm 0 --prefill-ms 20 --cpu 2`.
- **`/etc/init.d/reac-rig`** (S99) — waits for `reactap.11`, runs the restore
  script.
- **`/etc/hotplug.d/iface/99-rerun-rc-local`** — re-runs `rc.local` whenever
  `lan` comes up.

**Why the hotplug hack exists (the core fragility):** `service network
restart` rebuilds `br-lan` from UCI and **silently wipes** the manual
`bridge vlan add dev reactap.X` (a gretap subif as a bridge port is not
UCI-representable the way it's done here). Cross-router REAC then dies until
the hotplug re-runs `rc.local`. That wipe is the whole reason to move to
Variant 2.

**Status:** ✅ working. Re-pacer clock-locks (per≈125 µs @96k, +0 ppm). Known
rough edges: cold-boot buffer can balloon then drain; at `--prefill-ms 20` the
ring sits ~22–27 ms with **PLC underruns still firing in bursts** — the limiter
is **WDS burstiness**, not the clock (harden the 5 GHz link, don't just grow
the buffer).

---

## Variant 2 — MIGRATED, gretap-native (declarative; designed, apk-built, NOT deployed)

Move the whole fabric under **netifd + fw4** so a network reload rebuilds it
and nothing gets wiped. Shipped as a new **`reac-rig` apk** (the binary stays
in `reac-repacer`). Built artifact: `.build/out/reac-rig-0.1.0-r1.apk`.

**Load-bearing prerequisite:** the gretap *proto handler* `/lib/netifd/proto/gre.sh`
is absent by default — a bare `proto 'gretap'` UCI block no-ops until
**`apk add gre`** (confirmed installable from the 25.12.4 feed).

### `/etc/config/network` (modern DSA 25.12)
```uci
config interface 'reactap'            # gretap; ipaddr/peeraddr injected at install
        option proto 'gretap'
        option tunlink 'lan'
        option ttl '64'
        option mtu '1500'
        option defaultroute '0'
        option delegate '0'
config device                         # x3: reactap.11 / .12 / .13
        option type '8021q'
        option ifname 'reactap'
        option vid '11'
        option name 'reactap.11'
        option mtu '1500'
# EDIT br-lan device: + list ports 'reactap.11' '.12' '.13' ; option mtu '1700'
# EDIT bridge-vlan 11/12/13: + list ports 'reactap.NN:u*'  (the wiped bit, now declared)
```

### `/etc/nftables.d/10-reac.nft` (fw4-sourced, survives `network restart`)
```nft
table bridge reac {
        chain c {
                type filter hook forward priority 0; policy accept;
                iifname "reactap.11" oifname "lan1" drop
                iifname "reactap.12" oifname "lan2" drop
                iifname "reactap.13" oifname "lan3" drop
        }
}
```

### Re-pacer = pure procd service (no topology)
`/etc/init.d/reac-rig` waits for `reactap.11` then launches the daemon with the
same flags; **all `ip link`/`nomaster`/`bridge vlan` logic removed** — netifd/fw4
own the fabric. `/etc/config/reac-rig` holds the launch options; `--bcast-only`
is set only on the STA box. `reac-repacer.init` had its `handle_port`
topology block stripped.

### Packaging (`openwrt/reac-rig/`)
`DEPENDS := reac-repacer kmod-gre gre kmod-8021q nftables firewall4`.
Three `uci-defaults` shims keep it fingerprint-free, run once, self-delete:
`98-reac-network` (idempotent UCI merge of the fabric), `99-reac-gretap-peer`
(fills `ipaddr`/`peeraddr` from `network.lan.ipaddr`, `.1↔.2` flip),
`97-reac-role` (`bcast_only` from wireless mode sta/ap). conffiles:
`/etc/config/reac-rig`, `/etc/nftables.d/10-reac.nft`.

### ⚠ Deploy gap to handle (NOT in the auto-runbook)
Installing the apk does **not** remove the Variant-1 operator files. Before the
A3 `service network restart`, you MUST neutralize the old imperative fabric or
they fight over `reactap`:
1. comment out `rc.local` gretap/subif/bridge-vlan steps (keep the MTU/flood
   tune only if not already in UCI),
2. disable `/etc/hotplug.d/iface/99-rerun-rc-local`,
3. the orphaned `reacN-restore.sh` is no longer called (new init doesn't run it).

### Runbook (operator-supervised, ONE ROUTER AT A TIME — never both; reac2 STA first)
A0 backup → A1 `apk add gre && apk add reac-rig` (gate: `gre.sh` exists) →
A2 verify shims (`reactap.proto=gretap`, ipaddr/peeraddr, bcast_only) →
**neutralize Variant-1 (gap above)** → A3 **`service network restart`** (the
decisive reversible test: `reactap.11` stays `master br-lan` with VID 11, nft
drops present, REAC still flows) → **A3 GO/NO-GO** → A4 `reboot` (cold-boot
proof) → A5 verify tunnel+vlan+nft+re-pacer from cold boot, WDS intact on the
*other* router. **A-GATE** before reac1. Rollback = restore `/root/pre-native-bak`
+ `apk del reac-rig` + reboot.

**Status:** 🟡 designed, apks built, prerequisites validated (`gre` installable,
backups taken). NOT deployed — the deploy is the supervised step.

---

## Variant 3 — VXLAN (RULED OUT, kept for record)

Idea: one VXLAN per zone (VNI 11/12/13) = a clean `br-lan` VID-N access port,
avoiding the gretap-subif-of-a-shared-trunk. **Rejected:**
- **`kmod-vxlan` is not published** for this target/release (`apk add --simulate
  kmod-vxlan` → "no such package"; live probe `ip link add type vxlan` →
  "Unknown device type"). Would need an out-of-tree `.ko`/kernel rebuild — no.
- More encap overhead (~50 B vs gretap ~38 B), no MTU win (1496 B REAC fits
  under 1700 B WDS either way).
- **Doesn't retire the wipe special case** — bridge-VLAN membership is wiped for
  *any* manual bridge port regardless of tunnel type; the fix is declaring it in
  UCI (Variant 2), not changing the tunnel.

---

## Overnight findings (2026-06-10) — flagged for the operator

- **WDS master: KEEP reac1 AP.** "reac2 less loaded" was a measurement artifact;
  load is balanced (~24/26 % of one core, 3/4 cores idle), AP role ~0 CPU. No swap.
- **Audio not tight yet:** clock perfect, but ring 22–27 ms with bursty PLC
  underruns → chase **WDS burstiness** (link hardening), not the buffer.
- **⚠ Decoder layout conflict (top priority):** live M-5000 @96k decodes cleanly
  with the **obs-h8819 braid** (`main` branch); the current `feat/repacer-clock-tracker`
  **plain-LE** decoder (commit `e2e82ac`) **scrambles it**. Contradicts the
  documented "2026-06-06 plain-LE 0.999" validation. **Unresolved — do not change
  the decoder until reconciled** (different unit/mode? coherence artifact?). Real
  audio capture itself is confirmed (clean 360 Hz sine ch5→ch8 loop, ~0 % THD).
- **M-5000 MIDI console:** architecturally viable (firmware MIDI→SysEx→RUI→params,
  RUI is serial/MIDI-only never IP) but the plugged adapter is a **CH345**
  (7-bit-clean; RUI isn't) — needs a self-loopback byte-transparency test, else a
  raw UART/DIN MIDI interface. Meanwhile the real M-5000 access fix is the **lan5
  IP route** (telnet path, currently `no route to host`).
- **REAC→AES67:** already done (capture→decode→RTP L24→AES67+SAP/SDP + Dante
  profile), 48 k hardware-validated. Open: `cross_verify.py` lags the decoder
  (tie to the braid/plain-LE decision above), stale-96k docs, no 44.1k mode.
