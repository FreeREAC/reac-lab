# REAC → Dante bridge: design (AES67-interop profile)

**Date:** 2026-06-03
**Status:** DESIGN — approved-by-analogy ("same strategy as AES67"), implemented
the same night. Logic is unit-testable off-hardware; live PTP lock + Dante
Controller acceptance are rig-gated (see §9).
**Scope:** decode REAC (assumed correctly gathered) and re-emit it so a **Dante**
network receives it. Sibling of
[the AES67 bridge design](2026-05-30-reac-aes67-bridge-design.md); this profile
reuses its decode/clock/PLC/RTP core unchanged.

---

## 1. The headline question: can we use AES67 to speak with Dante?

**Yes — and AES67 is the *only* legitimate path.** This is the whole reason the
"Dante bridge" is built as a profile of the AES67 bridge, not a new protocol.

- **Native Dante is closed.** The Dante protocol (mDNS discovery, the `conmon`/
  CMCP control plane, flow setup, native audio transport) is **proprietary,
  undocumented, and patent-encumbered**, owned by Audinate. There is **no
  royalty-free path** to a native Dante endpoint — Audinate's only sanctioned
  implementations are paid, license-gated products (Brooklyn II/3 modules,
  Ultimo/Pro S1 chips, Dante Embedded Platform SDK, Dante IP Core FPGA netlist).
- **Clean-room native Dante is not an overnight job — and is legally risky.** The
  most advanced open effort, `teodly/inferno` (Rust, GPLv3), *can* appear in
  Dante Controller and exchange audio, but is "highly experimental" with material
  gaps (no multicast RX, clock stops when idle, no DDM). `jsharkey/wycliffe`
  (Python) is an incomplete experiment. **No C "act-as-Dante" project exists.**
  Both carry explicit warnings that Dante uses **Audinate patents** — clean-room
  reimplementation cures copyright but **not** patent exposure.
- **Audinate positions AES67 as THE sanctioned third-party interop path** —
  license-free, standards-based. So we take it.

**Therefore:** there is no `reac-dante` daemon and no reverse-engineered Dante
stack. There is a **`--profile dante`** mode of `reac-aes67` that makes the
already-working AES67 sender conform to the subset Dante's AES67 mode requires.

> AES67↔Dante is deliberately a **constrained subset**, not the native Dante
> experience: fixed **48 kHz**, **multicast only** (no unicast), **SAP**
> discovery, and Dante-to-Dante links always fall back to native Dante transport
> even with AES67 on. For a REAC→Dante audio bridge, that subset is sufficient.

---

## 2. Architecture — a profile, not a fork

```
            REAC 0x8819 frames (assumed correctly gathered)
                              │
        ┌─────────────────────┴─────────────────────┐
        │  EXISTING, UNCHANGED reac-aes67 core       │
        │  reac_decode → media_clock → PLC           │   per-REAC-frame
        │  (40 ch × 12 samp planar LE, 250 µs)       │   (12 samples)
        └─────────────────────┬─────────────────────┘
                              │ per-frame planar PCM + PTP-anchored rtp_ts
                              ▼
        ┌───────────────────────────────────────────┐
        │  NEW: packetizer (aggregate N frames)      │   Dante: N=4 → 48 samp = 1 ms
        │   accumulate N×12-sample frames into a      │   AES67 default: N=1 (250 µs)
        │   contiguous 40ch × (N·12)-samp planar block│
        └─────────────────────┬─────────────────────┘
                              │ one 40ch × 48-samp block per 1 ms
                              ▼
        ┌───────────────────────────────────────────┐
        │  NEW: flow splitter (40 ch → M flows ≤8 ch) │   Dante: 5 flows × 8 ch
        │   per flow: own channel slice, SSRC, PT,    │   each → own multicast addr,
        │   multicast dest, SDP, SAP announcement     │   own RTP packet per 1 ms
        └─────────────────────┬─────────────────────┘
                              ▼
             RTP L24 multicast  +  RFC 7273 SDP via SAP (239.255.255.255:9875)
                              │
                              ▼   (clock: bridge is a PTPv2 slave on domain 0)
                         DANTE network
```

The only new code is the **packetizer**, **flow splitter**, **PTP-anchored
timestamp**, **RFC 7273 SDP fields**, and the **Dante SAP address** — plus the
`--profile dante` plumbing. Decode, media clock, and PLC are reused verbatim.

The AES67-default path is the **N=1, single-flow, free-running** special case, so
the generalisation is backward-compatible (greenfield — but kept clean).

---

## 3. What Dante's AES67 mode requires (the constraints we must satisfy)

| Aspect | Dante AES67 requirement | Source (confidence: high unless noted) |
|---|---|---|
| **Clock** | PTPv2 (IEEE 1588-2008), **fixed domain 0**. One shared grandmaster. Dante runs PTPv1 natively + PTPv2 when AES67 enabled. | Audinate PTPv2-clocking FAQ; DDM "AES67 and SMPTE Domains" (domain 0, one domain at a time) |
| **Our clock role** | **PTPv2 slave** to that GM (or GM — but see §6, software-timestamping → **slave-only**). Dante can be the GM (Preferred Leader → boundary clock). | AES67 single-GM requirement; OpenWrt PTP findings |
| **Sample rate** | **48 kHz only**, L24 (24-bit). | Audinate RTP Config; AES67-2018 mandatory profile |
| **Packet time** | **1 ms = 48 samples/packet**, always (regardless of Dante latency setting). | Audinate sample SDP `a=ptime:1`; AES67 1 ms mandatory |
| **Transport** | **Multicast only** (no unicast), **≤8 channels per flow**. | Audinate "Create Multicast Flow… up to eight channels" |
| **Audio mcast range** | Default **239.69.0.0/16** (RX prefix MUST match Tx prefix or subscription silently has no audio). Default RTP port **5004**, media DSCP **AF41 (34)**. | Audinate AES67/RTP Config; AES67 default port/DSCP |
| **Discovery** | **SAP/SDP on 239.255.255.255:9875** (control address). Dante auto-discovers SAP senders; else manual "External AES67 Sessions". | SOUND4/Shure/aes67-monitor refs; AES67 SAP |
| **SDP clocking** | **RFC 7273**: `a=ts-refclk:ptp=IEEE1588-2008:<gmid>:<domain>` + `a=mediaclk:direct=0`. Domain present (not omitted). | Audinate sample SDP; RFC 7273 §4.8/§5; nmos-cpp #114 |

(Note: the existing AES67 default SAP address `224.0.0.56:9875` is **PipeWire's**
`module-rtp-sap` default — correct for the PipeWire receiver, wrong for Dante.
The Dante profile switches to `239.255.255.255:9875`.)

---

## 4. The RTP timestamp under RFC 7273 (`mediaclk:direct=0`)

This is the crux of Dante acceptance and the cleanest unit-testable piece.

- **Epoch:** the PTP/TAI epoch, **1970-01-01 00:00:00 TAI** (not the SMPTE video
  epoch). `CLOCK_TAI = CLOCK_REALTIME + 37 s` (current TAI−UTC offset).
- **Formula** (`mediaclk:direct=0`, offset 0):
  ```
  RTP_ts = ( floor(TAI_seconds · Fs) + round(TAI_nanoseconds · Fs / 1e9) ) mod 2^32
  ```
  with `Fs = 48000`. Advances by `ptime·Fs = 48` ticks per 1 ms packet.
- **`direct=0` ⇒** the RTP timestamp *is* the running media-clock sample count
  since the 1970 TAI epoch. Two senders locked to the same GM/domain are
  automatically sample-phase-aligned — which is what Dante relies on.

**Design choice — anchor once, then count.** Under the genlock requirement (§5),
the REAC audio rate *equals* the PTP rate, so a PTP-anchored sample counter stays
TAI-aligned forever. We therefore reuse the existing `media_clock` sample-counter,
but **initialise `rtp_ts` to the TAI-derived value** (instead of 0) at stream
start, then advance by `samples_per_pkt` per frame exactly as today. This keeps
the hardened dup/reorder/loss logic intact and confines the new math to one pure
function:

```c
uint32_t tai_to_rtp_ts(uint64_t tai_sec, uint32_t tai_nsec, int rate);
```

The runtime `clock_gettime(CLOCK_TAI)` read that feeds this is the rig-gated seam;
the function itself is fully tested with injected TAI values.

---

## 5. Clock-domain bridging — the part that is NOT code

REAC's word clock is the **V-mixer master**, recovered from packet-arrival
cadence. Dante is hard-locked to its **PTPv2 grandmaster** and **does NOT resample
inbound AES67**. If those two clocks are not the same physical reference, they
free-run at slightly different rates:

- `samples/hour drift = ppm · 172.8` at 48 kHz. Realistic uncorrected offsets are
  tens of ppm → thousands of samples/hour → the bridge's elastic buffer drifts to
  over/underrun → **periodic clicks/dropouts on a minutes timescale**, not
  continuous distortion.
- The existing `reac-aes67 → PipeWire` path *hid* this because PipeWire runs an
  **adaptive resampler** on every non-matching node (transparent ASRC). **Dante
  refuses to do that** to stay sample-accurate — so the drift PipeWire absorbed is
  exposed at the Dante ingress.

**Resolution:**
- **(a) Single house clock — HARD DEPLOYMENT REQUIREMENT (documented, not code).**
  Slave the V-mixer to a PTP-derived/word clock, *or* slave the PTP GM to the
  V-mixer (GM with word-clock-in, or a Dante device following external clock).
  Zero-cost, eliminates drift entirely. This is normal pro-install practice.
- **(b) ASRC in the bridge — opt-in fallback, OFF by default (seam only).** A
  drift estimator + elastic buffer + continuous resampler decouples the domains
  but costs CPU/latency/quality on a router SoC. We **design the seam** and
  **expose buffer-occupancy telemetry**, but do **not** implement ASRC tonight.
  When/if implemented it must be explicit and observable — never the silent
  default PipeWire was.

The bridge stamps timestamps *assuming* genlock (§4). Without genlock the
timestamps stay honest but the audio drifts — and the telemetry will show it.

---

## 6. PTP on OpenWrt — slave-only, software timestamping

- `linuxptp` (`ptp4l`/`phc2sys`/`pmc`) is in the OpenWrt feed (net/linuxptp v4.4),
  builds for both targets (ramips/mt7621 mipsel, mediatek/filogic aarch64).
- **No PTP hardware clock** on the mt7621 / MT7986 (filogic) MACs → **software
  timestamping only** (µs-class). That is **good enough for a FOLLOWER**, but a
  software clock must **never win BMCA** → **architect the bridge slave-only**
  (`slaveOnly 1`), never advertise a better clockClass than the Dante/house GM.
- `ptp4l` disciplines the system clock directly (no `phc2sys` without a PHC);
  the daemon reads `clock_gettime(CLOCK_TAI)` for the §4 anchor.
- Reference `ptp4l.conf`: `slaveOnly 1`, `domainNumber 0`, `time_stamping
  software`, `network_transport UDPv4`, `delay_mechanism E2E`, media/PTP DSCP.

The actual lock quality + BMCA behaviour against a real Dante GM is rig-gated.

---

## 7. New code (all unit-testable tonight)

1. **`tai_to_rtp_ts()`** + `media_clock` PTP-anchored init — §4. Pure; injected TAI.
2. **`rtp_l24_build_flow()`** — generalised builder: planar 40ch×Nsamp block,
   channel slice `[ch_start, ch_start+flow_nch)`, arbitrary sample count →
   interleaved-BE RTP L24. The existing `rtp_l24_build` becomes the
   `(0, all-ch, samples_per_pkt)` special case.
3. **`packetizer`** (`packetizer.{c,h}`) — accumulate `frames_per_packet` per-frame
   planar buffers into one contiguous 40ch×(N·12) planar block; on full, drive the
   flow splitter. Packet timestamp = first accumulated frame's `rtp_ts`. Concealed
   frames flow through transparently (the packetizer is loss-agnostic).
4. **Flow splitter** — `struct reac_flow { ch_start, n_ch, ssrc, pt, dest_ip,
   dest_port }`; split 40 → 5×8. One RTP packet per flow per 1 ms.
5. **SDP** — extend `sdp_params` with `ptime_ms`, `ts_refclk` (gmid+domain),
   `mediaclk_offset`; emit `a=ts-refclk:ptp=IEEE1588-2008:<gmid>:<domain>` +
   `a=mediaclk:direct=<n>`; `ptime` from `ptime_ms`; channel count per flow.
6. **SAP** — profile-selectable announce address (Dante `239.255.255.255:9875`).
7. **`--profile dante`** CLI → sets FPP=4, 40→8ch flow split, 48 kHz, ptime 1 ms,
   Dante SAP addr, RFC 7273 SDP, PTP-anchored timestamps, slave-only assumption;
   plus `--ptp-domain`, `--gmid`, `--aes67-base <239.69.x.x>` knobs.
8. **UCI/procd** — per-stream `profile`, `channels_start`/`channels_count` (or
   auto 8-wide split), `gmid`/`ptp_domain`, `aes67_base`. LuCI profile dropdown is
   a follow-up (UCI-driven for MVP).

## 8. Config surface (CLI / UCI)

```
reac-aes67 --listen lan1 --profile dante \
           --aes67-base 239.69.10.0 --rtp-port 5004 \
           --ptp-domain 0 --gmid 00-11-22-FF-FE-33-44-55
# → 5 multicast flows 239.69.10.0..4, 8 ch each, PT 96, ptime 1ms,
#   SAP to 239.255.255.255:9875, RFC7273 SDP, RTP ts from CLOCK_TAI.
```

## 9. Built tonight vs rig-gated

**Tonight (logic, TDD, host-verifiable):** packetizer aggregation, flow split,
`tai_to_rtp_ts` + PTP-anchored clock, `rtp_l24_build_flow`, RFC 7273 SDP, Dante
SAP address, `--profile dante`, UCI/procd. `make test`/`make verify` green.

**Rig-gated (documented, deferred):** live PTPv2 lock to a Dante GM (ptp4l on the
router, BMCA, SW-timestamp accuracy); Dante Controller AES67-enable + subscribe +
**audio acceptance**; genlock wiring (deployment); ASRC fallback (seam only); the
exact PT Dante expects; whether Dante hard-rejects SDP missing RFC 7273 (we emit
it unconditionally). 96 kHz/44.1 are **out of scope** — Dante AES67 interop is
48 kHz only.

## 10. Testing strategy

- **`tai_to_rtp_ts`**: known TAI → known RTP ts (incl. 2^32 wrap, sub-second
  rounding, the RFC 7273 90 kHz-style worked example adapted to 48 kHz).
- **packetizer**: 4×12-sample frames → one 48-sample packet; timestamp = first
  frame's ts; seq +1 per packet (not per frame); FPP=1 reproduces today's output.
- **flow split**: synthetic 40-ch ramp → 5 packets, each carrying the right 8-ch
  slice in interleaved-BE, distinct SSRC.
- **SDP**: golden-string match of a conformant Dante AES67 SDP (L24/48000/8,
  ptime:1, ts-refclk, mediaclk:direct=0, c= in 239.69/16).
- **cross_verify**: extend so the C flow-split decode matches the Python reference
  on the real fixture.

## 11. References

- Audinate: PTPv2-clocking FAQ; DDM "AES67 and SMPTE Domains" (domain 0); Dante
  Controller AES67 Config / RTP Config / Create Multicast Flow; sample SDP.
- AES67-2018 (48 kHz/L24/1 ms mandatory; ptime classes; 20× buffer).
- RFC 7273 §4.8 (`ts-refclk` ABNF, EUI-64 gmid), §5.2/§5.4 (`mediaclk:direct`,
  epoch, offset). RFC 4566 (SDP), RFC 3550 (RTP), RFC 3190 (L24).
- linuxptp / OpenWrt net/linuxptp; mtk_eth_soc (no PHC → SW timestamping).
- teodly/inferno, jsharkey/wycliffe (clean-room native Dante — why we don't).
- Sibling: [REAC→AES67 bridge design](2026-05-30-reac-aes67-bridge-design.md);
  [REAC protocol](../../REAC-PROTOCOL.md).

## 12. Rig acceptance checklist (from the 2026-06-03 adversarial review)

The review found **no blockers** and applied the safe quick-wins (media DSCP
AF41 now set; periodic SAP re-announce; input guards). These items are
**deliberately deferred to the rig** because only a real Dante device + PTP
grandmaster can settle them:

- [ ] **PTPv2 lock.** Run `ptp4l -f /etc/ptp4l-dante.conf` on the bridge; confirm
      `pmc -u -b 0 'GET TIME_STATUS_NP'` shows `gmPresent=1` and a small offset,
      and that the bridge never wins BMCA (software timestamping → must stay
      follower). Read the grandmaster `clockId` (`pmc … GET CLOCK_DESCRIPTION`)
      and set it as the stream's `gmid`.
- [ ] **SDP direction.** We emit `a=recvonly` (the AES67/Audinate-sample
      convention for an announced source). Confirm Dante Controller subscribes;
      if it rejects, the one-line flip to `a=sendonly` is the fallback (kept out
      of the code on purpose — the review's two reviewers disagreed and the cited
      sample SDP uses `recvonly`).
- [ ] **Payload type.** We default to PT 96; confirm the target Dante device
      accepts it (some expect 98). `--pt` overrides.
- [ ] **RFC 7273 strictness.** We always emit `ts-refclk` + `mediaclk:direct=0`
      at media level; confirm Dante doesn't require session-level placement.
- [ ] **Genlock soak.** Lock the V-mixer and the PTP GM to one house clock, then
      run for hours and confirm zero buffer resets (§5). Without genlock, expect
      periodic glitches — that's the deployment requirement, not a code bug.
- [ ] **Dup/reorder drift follow-up.** A duplicate/reordered REAC frame advances
      the TAI-anchored RTP timestamp by one packet with no new media time
      (`media_clock.c`, deliberate per §4). If the rig shows this matters under
      Dante buffering, add the `[n,n,n+1]` test + a re-stamp path. Dominated by
      the §5 clock-domain drift, so almost certainly moot under genlock.
