<!-- SPDX-License-Identifier: GPL-3.0-or-later
     Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com> -->

# REAC → AES67 → PipeWire monitor nodes (per REAC zone)

**Date:** 2026-06-13 · **Author:** Pau Aliagas <linuxnow@gmail.com>

## Status: pipeline VALIDATED end-to-end (synthetic), rig launch pending

`reac-aes67 --gen-tone` → SAP/SDP → PipeWire produced a live **`REAC-A (40ch AES67)`**
`Audio/Source` node on the laptop (all on loopback, zero rig impact). The receiver +
naming work; only the live-REAC daemon launch remains.

## What ships vs the goal

- **Achievable:** one named PipeWire node **per REAC zone** (REAC-A/B/C), name set from
  `reac-aes67 --name` (derive it from the console).
- **NOT in the binary:** per-channel labels. `reac-aes67` has **no `--labels`/`--labels-file`**;
  the SDP carries a single `s=<name>` per stream. The 40 channels inside a node stay as
  positional ports. Per-channel console names (Kick/Snare/…) would need either a daemon
  feature-add or a WirePlumber `node.rules` port-rename script keyed to a slot→name table.

## Receiver config (laptop) — IN PLACE

The production receiver is **`~/.config/pipewire/pipewire.conf.d/reac-aes67-sap.conf`**
(module-rtp-sap on **`enp3s0`**, the wired NIC; `sap.ip=224.0.0.56`; catch-all
`rtp.session = "~.*"` → `media.class=Audio/Source`, `sess.latency.msec=100`). It is
**fully dynamic** — rate / channels / format come straight from each announced SDP, so it
follows the sender automatically (L24 / 96000 / 40ch, nothing hardcoded) and names each
node by the SDP session name (REAC-A/B/C from `reac-aes67 --name`). Plus
`99-aes67-rate.conf` (`allowed-rates=[48000 96000]`) so PipeWire can clock the graph at
96k natively. Verify: `wpctl status | grep -i reac`.

> **`aes67-rx.conf` was only a loopback test scaffold** (bound to `lo`, hardcoded
> REAC-A/B/C rules) to validate the chain with `--gen-tone` on `lo`. It is now parked as
> `aes67-rx.conf.disabled`; re-enable it only for another loopback test. For the live rig
> the `enp3s0` `reac-aes67-sap.conf` above is the correct, sufficient one (it even catches
> a `lo` gen-tone via multicast host-loopback). **An earlier draft of this doc had these
> two reversed — disabling the `sap.conf` would have removed the real receiver.**

## Launching the live streams (rig)

```bash
# per zone — REAC capture iface --listen, AES67 egress --iface, distinct SSRC
reac-aes67 --listen <reac-iface> --udp 239.69.0.1:5004 --name REAC-A --rate <RATE> --pt 97 --ssrc 11223344 --ttl 1 --iface <egress>
reac-aes67 --listen <reac-iface> --udp 239.69.0.2:5006 --name REAC-B --rate <RATE> --pt 97 --ssrc 11223345 --ttl 1 --iface <egress>
reac-aes67 --listen <reac-iface> --udp 239.69.0.3:5008 --name REAC-C --rate <RATE> --pt 97 --ssrc 11223346 --ttl 1 --iface <egress>
```

### Critical rig decisions (verify on-site)
- **WHERE to run it — run on reac2 (stage), egress on the LAN5 wire to the laptop.** Each
  zone is ~11.5 MB/s (40ch L24 @96k); 3 zones ≈ 34 MB/s. If reac-aes67 runs on **reac1** and
  the AES67 multicast crosses the **WDS** to reach the laptop, it adds ~275 Mbit/s onto the
  already-loaded WDS and **will degrade the re-pace audio**. Running on reac2 with `--iface`
  = the wired LAN5 keeps it off the WDS.
- **RATE:** REAC here is **96 kHz** → use `--rate 96000`. The daemon does NOT resample, so a
  wrong `--rate` makes the SDP lie → silence / wrong pitch. `--rate` is a PIN, not the only
  way to learn the rate: measure it off the wire first with
  `python3 -m reac.characterize <pcap>` — `rate = pps × 12`, so 8000 pps is 96 kHz — and pin
  what you measured. The `allowed-rates=[48000 96000]` drop-in lets PipeWire clock-switch.
  40 channel slots at every rate; 96 kHz doubles the packet rate, it does not halve the width.
- **PTP:** not needed for monitoring (`sess.ts-direct=false` free-runs + resamples; may click
  on corrections, can't keep A/B/C sample-aligned). Spec-correct multi-stream alignment would
  need `ptp4l` (not installed) + a PTP grandmaster — which this REAC chain may not have.
- **SAP group is 224.0.0.56** (AES67 default profile), NOT Dante's 239.255.255.255.

### Fastest single-node test (no hardware)
`reac-aes67 --gen-tone --iface lo --udp 239.69.0.1:5004 --name REAC-A --rate 48000 --pt 97 --ttl 1`
→ PipeWire node `REAC-A (40ch AES67)` (this is exactly what was validated tonight).

## Console names (M-5000 @ 192.168.10.182:8023)
`python3 m5000_query.py --host 192.168.10.182 --model m5000 dump-patch` (read-only; close any
RCS/iPad session first — single control client). Default patch: REAC-A IN 1–24 → CH 1–24,
REAC-B IN 1–24 → CH 25–48. PIQ is dead on M-5000 so the live patch isn't network-readable —
if re-patched, fall back to positional names. Feed the chosen zone label into `--name`.

Full research + caveats: workflow `aes67-pipewire-plan` (2026-06-13).
