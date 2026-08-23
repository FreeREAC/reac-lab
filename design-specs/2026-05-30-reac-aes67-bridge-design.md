# REAC → AES67 Bridge — Design

> **SUPERSEDED IN PART — two central claims below are refuted by measurement.**
> This document is kept as the record of what was believed on 2026-05-30. The
> live answer is in [FreeREAC/reac-protocol](https://github.com/FreeREAC/reac-protocol).
>
> 1. **"96 kHz halves the channel count to 20 and doubles the samples per frame
>    to 24" — REFUTED.** 96 kHz doubles the PACKET RATE. The frame stays 40
>    channel slots × 12 samples at every rate; the geometry is `52 + n × 36`
>    bytes and is rate-invariant. Packet rate is 3675/s at 44.1 kHz, 4000/s at
>    48 kHz, 8000/s at 96 kHz. The mode descriptor `{96000, 20, 24}` and every
>    "20 ch @ 96 k" figure below are wrong. (The R-1000 manual's "24 tracks at
>    96 kHz" that seeded this is a recorder storage limit, not a REAC width —
>    already suspected in the 2026-05-31 capture-campaign spec, and settled by
>    the rig: `runbooks/rig-parked-state.md` §4 reads 8000 fps at 96 kHz on a
>    40-slot stream.)
> 2. **"Rate is NOT distinguishable from packet rate … it must come from config"
>    — REFUTED.** Rate is not a wire FIELD, but it is a wire OBSERVABLE:
>    `rate = pps × 12`. Every rate has its own packet rate, so a capture alone
>    settles it. The re-pacer does this continuously and follows a live rate
>    change without configuration (see `2026-06-03-reac-repacer-design.md` §11).

**Date:** 2026-05-30
**Status:** Implemented (M1+M2) — decode/clock/PLC/RTP/capture/send done, 33
tests + cross-verify green; apk built for aarch64. On-device smoke pending.
OpenWrt packaging + LuCI: see the
[packaging design](2026-05-31-openwrt-luci-packaging-design.md).
**Repo:** `FreeREAC/reac-aes67` (lives under the `FreeREAC` org alongside
`reac-protocol`, `reac-tools` and `reac-docs`, NOT the signage platform).

## Goal

Make all REAC audio channels available on the LAN as standard network audio,
so any Linux host can record / monitor / route them in PipeWire (Ardour,
Reaper, OBS, `pw-record`, …). One direction only for now: **REAC → Linux**.

The bridge runs **on the GL-MT6000 router** that already carries the REAC
traffic — no dedicated capture NIC, no extra host. The router decodes REAC
and re-emits it as **AES67** (RTP L24 multicast), which stock PipeWire
receives natively (`module-rtp-source` / AES67), so receivers need no bespoke
software and multiple machines can subscribe at once.

## Background / context

- The reference rig: a Roland digital mixer/console + up to **3 REAC
  modules/stageboxes**, carried over a 30 m 5 GHz WDS link between two GL-MT6000
  (Flint 2, OpenWrt 25.12) routers via gretap. Three VLAN zones exist: **11/12/13
  on lan1/lan2/lan3** (REAC zone A/B/C). Each REAC connection carries up to **40
  channels**.
- REAC framing (verified on-site 2026-05-30 + cross-checked against
  `per-gron/reacdriver` and `norihiro/obs-h8819-source`):
  - EtherType `0x8819`; playback streams are **broadcast** (`ff:ff:ff:ff:ff:ff`).
  - L2 header = 50 bytes: 14 (eth) + 2 (`l2_counter`, uint16 **LE**) + 2
    (`l2_type`) + 32 (unknown).
  - Audio region = **1440 B**, partitioned by sample rate (the frame size and
    packet rate stay the SAME; the partition of the 1440 B changes):
    - **48 kHz: 12 samples × 40 ch × 3 B** (VERIFIED on-site + obs-h8819).
    - **96 kHz: 24 samples × 20 ch × 3 B** — channel count **halves**. VERIFIED
      from the Roland **R-1000 Owner's Manual** (e02): *"At 44.1 kHz or 48 kHz,
      you can record up to 48 tracks. At 96 kHz, recording on up to 24 tracks is
      possible"* + spec table `44.1kHz(48Tr)/48kHz(48Tr)/96kHz(24Tr)`, and
      *"REAC … up to 40 channels"*. So per REAC connection: 40 ch @ ≤48 k → **20
      ch @ 96 k**. ("Twice the data per channel, half the channels.")
  - 2-byte end marker **`0xC2 0xEA`**. Total 1492 B.
  - **Rate is NOT distinguishable from packet rate** (both 48 k and 96 k run at
    the same ~4000 pps, same 1492 B frame). It must come from **config** (or, if
    ever needed, detecting the channel-packing) — *not* a pps measurement. This
    corrects an earlier draft assumption.
  - **40 channels is the hard cap per REAC connection** regardless of stagebox
    capacity (a 48-ch stagebox still exposes only 40). More channels ⇒ more REAC
    connections (more zones), never a fatter stream.
  - 24-bit PCM, interleaved with an even/odd-channel byte shuffle and a stride of
    `n_channels × 3 B` (120 B @ 48 k / 40 ch). Decode lifted from
    `convert_to_pcm24lep` in obs-h8819-source `capdev-proc.c` and generalized to
    a mode descriptor `{rate, n_channels, samples_per_pkt}`. The byte shuffle is
    reverse-engineered and not guessable. **48 k is verified against the
    reac-tools pcap fixture; the 96 k de-interleave stride is structurally
    implemented but UNVERIFIED — it needs a real 96 k capture to confirm the
    byte order before its audio output is trusted.**
- **Clock:** REAC always has exactly **one clock master** (the mixer by
  default, configurable to a stagebox). VERIFIED from the R-1000 manual: *"REAC
  is set to be the clock source"* by default; role table **V-Mixer = Master,
  Digital snake = Slave**; and *"the sampling rate of the REAC master device.
  Mis-matched sampling rates will result in a failure of audio transmission."*
  Therefore all REAC streams on the fabric are **mutually phase-locked at the
  source** — the bridge only ever *observes* this clock; it never masters it.

## Non-goals

- Sending audio back onto REAC (Linux → REAC). One direction only.
- Channel-count autodetection (channel count is set by the mode: 40 @ 48 k, 20
  @ 96 k; idle channels are silent).
- PTP / sample-accurate cross-device sync in phase 1 (see Clocking).
- Running PipeWire on the router.

## Architecture

```
 REAC zone A (lan1/vlan11) ─┐
 REAC zone B (lan2/vlan12) ─┤  AF_PACKET(0x8819, BPF) per source
 REAC zone C (lan3/vlan13) ─┘
        │  (one capture+decode+sender per active REAC stream, ≤3)
        ▼
 ┌──────────────────────────────────────────┐
 │  reac-aes67 daemon (router, aarch64 C)     │
 │   reac_decode  (mode-parameterized)        │
 │   media_clock  (sample counter + gap fill) │
 │   aes67_send   (RTP L24 multicast + SDP)   │
 └──────────────────────────────────────────┘
        │  ~5 Mbit/s per stream (decoded PCM), LAN multicast
        ▼
 Linux receivers: stock PipeWire module-rtp-source / AES67
        → each REAC stream appears as its own node
        → patch REAC-A:ch1..40 (48 k) or ch1..20 (96 k), per zone
```

### Units (each independently testable)

1. **`reac_decode`** (done, unit-tested) — pure function parameterized by a
   `reac_mode {rate, n_channels, samples_per_pkt}`: one 1492 B REAC frame →
   planar 24-bit PCM + `l2_counter` + `0xC2 0xEA` end-marker validity. Lifted
   from obs-h8819 `convert_to_pcm24lep`. **No I/O.** 48 k verified against the
   `reac-tools` pcap fixture (known frame: ch4/samp0 = `0xFFFFFF`); 96 k mode
   structurally present, byte order pending a real 96 k capture.
2. **`media_clock`** (done, unit-tested) — per-stream running **sample count** as
   the RTP media clock. On a `l2_counter` gap of N packets, advances the
   timeline by N×`samples_per_pkt` and reports N silence packets to emit, so the
   count and all channels stay aligned (loss = brief mute, never a slip).
   Handles 16-bit counter wrap.
3. **`pcap_source`** (done, unit-tested) — reads the shared reac-tools pcap fixture
   (classic libpcap, either endianness) → full ethernet frames. The off-site
   dev/replay source; same `reac_decode` path as live capture.
4. **`reac_capture`** (TODO) — owns the `AF_PACKET` socket + BPF
   `ether proto 0x8819` bound to a given iface/source; capture loop →
   `reac_decode` → media clock. **Source-swappable** with `pcap_source` so the
   pipeline runs identically off-site.
5. **`aes67_send`** (TODO) — RTP L24 multicast sender; RTP timestamp = the media
   clock's sample count; advertises each stream via SDP/SAP. One sender per
   active REAC stream.
6. **config** (TODO) — list of REAC sources
   `[{iface, src_mac, name, mode, multicast_addr}]`, ≤3 entries. The **mode**
   (48 k/96 k) is configured here, since it is not detectable from the wire.
   Each → one independent capture→decode→send pipeline.

## Channel / stream mapping

- **One AES67 stream per REAC zone** (A/B/C), each ≤40 channels (40 @ 48 k,
  20 @ 96 k) → each its own PipeWire node on the receiver. Mirrors the physical
  REAC topology, isolates faults per zone, keeps each stream's clock/seq
  integrity separate. "More channels" = "more zones" (40 is the per-connection
  cap), never a fatter stream.
- Up to 3 streams. Max decoded load ≈ 3 × 40 ch × 48000 × 3 B ≈ **17 Mbit/s**
  (48 k); 96 k is fewer channels at double rate ≈ the same. Trivial on the LAN.
  (Raw REAC is ~48–95 Mbit/s/stream; decoding on the router is a large
  bandwidth win.)

## Clocking

Because the REAC fabric has a single clock master, all streams are mutually
locked at the source. The bridge observes that clock via packet cadence.

### Loss concealment (PLC)

Chosen after evaluating four PLC families for the hard per-slot deadline. **Primary = repeat-last-packet + short linear in-splice
crossfade** (`plc.{c,h}`), integer Q15, per-channel, **search-free** — so a
whole-frame loss (up to 3 streams × 40 ch in one 250 µs slot, all phase-locked
to one REAC master) cannot miss the egress deadline. Pitch-similarity/WSOLA was
**rejected as primary**: its per-slot 120-channel search ≈ 1.8 ms ≫ 250 µs, and
its squared-NCC metric overflows int64 — it remains a documented future upgrade
(SAD/AMDF, gated on on-site evidence). The crossfade is **linear, not
equal-power** (substitute is coherent with the signal → gains must sum to 1.0;
equal-power would swell +3 dB).

Fallback ladder (operator mandate — hold-last is the FLOOR, silence last):
`TIER 0` repeat+crossfade (first lost packet) → `TIER 1` scaled-repeat with
decaying burst gain (fades to silence over ~50 ms) → `TIER 2` hold-last DC
(history underfilled) → `TIER 3` silence (cold start only). Strip the crossfade
+ gain and Tier 0 degenerates to bare hold-last — the floor is structural.

**Phase 1 (ship): sample-counting media clock, no PTP.**
- RTP timestamp = running sample count (per stream), incremented per decoded
  packet (+`samples_per_pkt`: 12 @ 48 k, 24 @ 96 k). This is the standard AES67
  sender behaviour and is **robust to Wi-Fi arrival jitter** (we stamp by sample
  count, not by jittery arrival time).
- Because the router emits exactly as many samples as REAC delivers, it
  introduces **no rate mismatch**; the only residual drift is receiver-side
  (PipeWire clock vs media clock), absorbed by PipeWire's **adaptive
  resampler** — the normal AES67 receive path.
- Seq-gap → insert N×12 samples of silence (keeps the media clock honest).
- All ≤3 streams inherit the same master cadence, so they stay mutually
  co-timed for free; no cross-stream lock logic needed.

**Phase 2 (seam left open): PTP, router as grandmaster disciplined to REAC
cadence.**
- Run `ptp4l` on the router as PTP grandmaster, **slaved to the observed REAC
  packet cadence** (i.e. expressing the mixer's real word clock as LAN PTP
  time) — *not* a free-running router clock.
- Yields standards-correct AES67, sample-accurate cross-stream/-device lock,
  pro-gear interop (Dante-AES67 bridges etc.).
- The phase-1 sample counter is the natural input to the PTP discipline loop,
  so this extends rather than replaces phase 1.

## Capture on the router — constraints & risks

- Needs raw L2 (`AF_PACKET`/`CAP_NET_RAW`); the REAC zones are already
  isolated on their own VLANs/ports, so the BPF `0x8819` filter sees only REAC.
- **Risk to validate on-site:** capture must not perturb the live REAC
  bridging (interaction with flow-offload / the gretap path). Measure REAC
  loss/jitter with `reac-tools` before and during capture to confirm no
  regression. This is the single most important on-site check.
- aarch64 (MT7986, quad-A53 @ 2 GHz) easily handles 3×8000 pps capture +
  byte-shuffle decode + RTP packetize.

## Testing strategy

- **Off-site (laptop, no rig):** replay the `reac-tools`
  `real_reac_stream.pcap` fixture → daemon (pcap-replay source) → AES67 →
  local PipeWire `module-rtp-source` → confirm 40 ports appear and carry the
  known samples. The decoder is unit-tested against the same fixture that
  `reac-tools` already validates (seqs `0xfd7e..0x81`, 0 loss).
- **On-site (live REAC):** the flow-offload-perturbation check above;
  end-to-end record of live channels; loss/jitter correlation with
  `reac-tools`.

## Build / packaging

- C, cross-compiled for OpenWrt aarch64 (MT7986). Dependencies kept minimal
  (libpcap or raw `AF_PACKET`; a small RTP/SDP sender — no heavyweight AES67
  stack in phase 1).
- Decode logic is a **C re-implementation** of the same byte layout that
  `reac-tools` (Python) and obs-h8819 (C) implement. The two repos don't share
  a library (different languages); they share the **pcap fixture**
  (`reac-tools/tests/fixtures/real_reac_stream.pcap`) as the common
  byte-layout source of truth, so the C decoder is tested against the exact
  same known frames (`0xfd7e..0x81`).

## Phased delivery

1. **M1 (done)** — `reac_decode` (mode-parameterized) + `media_clock` +
   `pcap_source`, unit-tested against the pcap fixture (11 tests).
2. **M2** — single-stream pcap-replay → AES67 → PipeWire on the laptop; ports
   visible and correct (off-site, no rig). = `reac_capture` (pcap mode) +
   `aes67_send`.
3. **M3** — live single-stream on the router (`reac_capture` AF_PACKET mode);
   on-site flow-offload check.
4. **M4** — all ≤3 streams; per-zone SDP naming + config.
5. **M5 (later)** — PTP grandmaster disciplined to REAC cadence.

## Open questions (defer to implementation)

- Exact RTP/SDP/SAP library vs hand-rolled minimal sender on OpenWrt.
- Multicast address allocation per stream + IGMP behaviour on the LAN.
- **The 96 k de-interleave byte order** — channel-halving is confirmed (R-1000
  manual), but the exact 24-sample × 20-channel byte layout is structurally
  implemented from the 48 k pattern and UNVERIFIED. Confirm with a real 96 k
  capture before trusting 96 k audio. Mode is set by config (not pps), so 48 k
  is unaffected.
