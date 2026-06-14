# REAC re-pacer (Wi-Fi de-jitter relay): design

**Date:** 2026-06-03
**Status:** DESIGN — for review. Motivated by the on-rig finding that the 5 GHz
WDS delivers REAC in A-MPDU bursts (clock-slave stageboxes can't track it).
**Goal:** make a *wireless* REAC stagebox sound clean by smoothing the master's
packet cadence on the far router, without touching REAC's content or its
handshake.

---

## 1. The problem (measured, 2026-06-03 on-rig)

REAC is a quasi-isochronous L2 stream: the master (M-300) broadcasts one ~1492 B
frame every **250 µs** (4000 pps @ 48 kHz), and every slave (stagebox) recovers
its word clock straight from that arrival cadence — **no jitter buffer**.

The 5 GHz Wi-Fi WDS delivers every frame intact (0 loss, 0 reorder, content
verified pristine, link −33 dBm / 2.4 Gbit) **but destroys the timing**:

| metric | wired (pre-WDS) | Wi-Fi (post-WDS) |
|---|---|---|
| inter-arrival variance | 5,311 µs² | **158,608 µs²** (~30×) |
| frames per delivery "burst" | 1.0 (max 5) | **1.9 avg, up to 18** |
| gap after a burst | ~258 µs | up to **8,833 µs** |
| distribution | unimodal ~250 µs | **bimodal**: 47% at 0–50 µs, tail to 8.8 ms |

Root cause (not fixable by Wi-Fi config — all tested): REAC is ~16,000 tiny
packets/s (bidirectional × 2 zones); Wi-Fi's per-packet airtime overhead forces
**A-MPDU aggregation** (link is ~78% airtime, ~96% ours, channel clean) → frames
are clumped and released in bursts. Disabling aggregation would exhaust airtime;
a clean channel does nothing (we are the load). Bursts + ms gaps wreck the
stagebox's clock recovery → continuous "saturated/metallic" audio with perfect
packet counters.

**Therefore: insert a buffer the stagebox lacks.** Receive the bursty-but-correct
master stream, hold a few ms, and re-emit a clean 250 µs cadence to the local
stagebox — the "de-jitter layer" a wired link gave for free.

---

## 2. What the re-pacer is (and is NOT)

- **IS** a *transparent L2 timing smoother*: it relays the **real** master frames
  (src/dst MACs, payload, type, counter all unchanged) onto the stagebox's REAC
  segment, only changing *when* each frame is delivered.
- **IS NOT** a REAC master/TX synthesizer. It does **not** generate REAC, does
  **not** participate in the handshake, does **not** guess the cdea control state
  machine. The mixer remains the one true master; the stagebox stays
  handshake-connected to the mixer's MAC. This sidesteps the hard, unverified
  part of the master-TX work (#28) — we forward genuine frames, just re-timed.

`★ One clock, not two.` Unlike the Dante/AES67 clock-domain problem, there is a
single clock here — the mixer's. The re-pacer *recovers* it (the long-term
average arrival rate equals the mixer's word clock, since no frames are lost) and
re-emits at exactly that rate. The stagebox locks to the re-paced cadence = the
recovered mixer clock. No drift between domains, only added latency.

---

## 2.5 Approach spectrum — who owns the clock

There are two ways to give each device a clean cadence; they differ in **where
the word clock is generated**:

**A — Proxy the clock (transparent re-pace, both sides) — RECOMMENDED first.**
Relay the *real* master/slave frames and smooth the cadence at each router's
ingress: master→stagebox re-paced at `.2`, stagebox→mixer re-paced at `.1`. There
is **one clock — the mixer's** — *recovered* from the (jittery) stream and re-emit
locally; the buffer + rate servo absorb the jitter. The M-300 stays master, the
stageboxes stay slaves, we're invisible per-side timing buffers. **No master
synthesis, no handshake — avoids the #28 blocker.** This is "proxy the proper time
on every side"; §3–§7 detail it. Lower risk, almost certainly sufficient.

**B — Be the master clock (fallback, only if A is inadequate).** The bridge
*becomes* the REAC master at **each** router; the M-300 and the stageboxes are set
to **slave** and lock to our locally-generated clean clock. Decisive advantage:
the word clock is generated **locally at each side**, so Wi-Fi jitter **never
touches the clock at all** — only audio *samples* cross the link (buffered). Most
robust against jitter. But it costs: (1) a full REAC **master-TX synthesizer**
(master-announce + control/handshake state machine — the unverified #28 work), and
(2) **frequency-locking the two local masters** to each other (PTP over the link,
a word-clock cable, or one master servo'd to the other's recovered rate — PTP is
jitter-tolerant, unlike raw REAC). Heavier and riskier; pursue only if A's
stream-recovered clock proves inadequate (e.g. the buffer can't hold, or a device
won't lock to the re-paced cadence).

**The trade in one line:** A recovers *one* clock from the jittery stream (simple,
buffer-absorbed); B generates the clock *locally* on each side so jitter never
reaches the clock — at the price of master synthesis + an inter-router frequency
lock. **Plan: ship A, keep B as the escape hatch.** Both reuse the same RT-TX +
jitter-buffer machinery built below — A just doesn't synthesize a master.

## 3. Architecture

```
   .1 mixer ──REAC──┐
                    │ gretap / 5 GHz WDS (bursty)
   .2 router        ▼
     reactap.11 ──► [ CAPTURE ]                         AF_PACKET RX, ETH_P_REAC
                       │  master broadcast frames (bursty), + control/handshake
                       ▼
                    [ JITTER BUFFER ]  ring of frames, depth ≥ max gap + margin
                       │  + rate servo (keep buffer ~half full)
                       ▼
                    [ RT PACER ]  clock_nanosleep(TIMER_ABSTIME) @ recovered rate
                       │  SCHED_FIFO, isolated core, PREEMPT_RT preferred
                       ▼
     lan1 (stagebox) ◄─ [ TX ]   AF_PACKET TX, frame bytes unchanged
                       (stagebox sees a clean 250 µs cadence from the mixer's MAC)
```

**Topology requirement (load-bearing):** the gretap-delivered master broadcast
must reach the stagebox **only** via the re-pacer, never via the direct bridge —
otherwise the stagebox sees both the bursty copy and the re-paced copy. So on the
stagebox-facing side the REAC VLAN is **removed from the direct bridge path** and
the re-pacer becomes the sole source on the stagebox segment (capture from the
gretap side, TX to the stagebox side). Two clean options:
- (a) put the stagebox port on its own bridge/VLAN not bridged to reactap.11, and
  let the re-pacer relay between reactap.11 and that port; or
- (b) AF_PACKET capture on reactap.11 + AF_PACKET TX on lan1 with the REAC VLAN
  unbridged between them.

**Direction scope.** Phase 1 re-paces only **master → stagebox** (the broadcast =
the stagebox's word-clock source — the clock-critical path). The return
(stagebox → mixer inputs) keeps flowing the normal bridged way: the master is the
clock owner and tolerates more input jitter than a slave does. Re-pacing the
return is a Phase 2 item, evaluated after Phase 1 (see §7).

## 4. Clock recovery + jitter buffer (rate-adaptive playout)

The re-emit rate must equal the mixer's rate to sub-ppm, or the buffer slowly
over/underruns. Standard adaptive de-jitter:

- **Buffer fill is the control variable.** Target = half-full. If filling
  (source faster than our emit), nudge the emit interval *down*; if draining,
  nudge it *up*. A slow servo (adjust over seconds, tiny steps) locks the emit
  rate to the source without adding jitter.
- **No resampling.** We relay whole frames at the recovered frame rate; there are
  no fractional samples to interpolate (unlike ASRC). The servo only sets the
  inter-frame interval (~250 µs), not the sample values.
- Counter continuity (the REAC `counter[2]`) sanity-checks the buffer: a gap/dup
  in the recovered stream is logged (should be 0 — transport is lossless).

## 5. Real-time pacing (the key risk)

Re-emitting at 250 µs with low jitter on a router CPU is the make-or-break:
- `clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME)` to an accumulated deadline
  (drift-free), `SCHED_FIFO` high prio, IRQ-affinity + `isolcpus`/`nohz_full` for
  the pacing core. PREEMPT_RT (Linux 6.12) strongly preferred.
- **Target: re-emitted cadence jitter ≪ the stagebox tolerance.** The stagebox
  worked on wire at SD 15–73 µs, so the re-pacer must hit roughly that or better.
  Whether a non-RT OpenWrt kernel can is **unknown and must be measured first**
  (see §7) — this gates the whole approach. If non-RT can't, build/boot PREEMPT_RT.
- TX path: AF_PACKET `SOCK_RAW` on lan1. (SO_TXTIME/ETF would be ideal but the
  mt7986 NIC has no TSN launch-time; software pacing it is.)

## 6. Latency budget

Buffer depth must cover the worst gap (8.8 ms measured) + margin → **~12–15 ms**
added one-way latency on the stagebox outputs. For studio/monitor use that's
usually fine; for live performers on in-ears it's borderline (~5 m of air). The
depth is a tunable trade (smaller = lower latency, higher under/overrun risk
under big bursts). Report buffer occupancy + under/overrun counters via ubus.

## 7. Phasing + test plan

1. **Feasibility gate (do FIRST, no audio):** a minimal pacer that AF_PACKET-TXes
   a dummy 4000 pps stream on lan1 under SCHED_FIFO; **measure its cadence jitter
   with tcpdump** (the same `dist.py`/`burst.py` tools). If SD ≫ ~100 µs on the
   non-RT kernel, decide PREEMPT_RT before writing more.
2. **Phase 1 — master→stagebox, one zone:** capture reactap.11 master broadcast →
   buffer + servo → RT-TX lan1. Topology per §3. Listen at the stagebox; soak
   for hours confirming **zero buffer over/underrun** (proves the rate servo
   tracks the mixer clock). Compare stagebox audio before/after.
3. **Phase 2 (if needed):** re-pace the return direction; multi-zone; tune buffer
   depth to the minimum that holds.

TDD where pure: the **jitter buffer + rate servo** is deterministic (feed it a
synthetic bursty arrival trace, assert smooth output + bounded occupancy + locked
rate) — unit-testable off-hardware. The RT pacing + AF_PACKET TX + topology are
rig-validated.

## 8. Risks / open questions (for review)

- **RT jitter on OpenWrt** — the gating unknown (§7 step 1). Non-RT may suffice
  (isolated core) or may force a PREEMPT_RT build for the GL-MT6000.
- **Latency acceptable?** ~12–15 ms — OK for monitor/record, marginal for live IEM.
- **Topology change risk** — unbridging the REAC VLAN on the stagebox side could
  break REAC if done wrong; stage it carefully, keep a revert.
- **Return direction** — does the M-300 actually need its inputs re-paced, or does
  it tolerate the Wi-Fi jitter on the return? (Measure the mixer's behavior in
  Phase 1 before committing to Phase 2.)
- **Overlap with #28** — shares the RT-TX-of-REAC machinery, but avoids the
  handshake-synthesis blocker by relaying real frames.

## 9. Decisions needed before implementation

1. Acceptable added latency (sets buffer depth)?  →  default ~12 ms unless live-IEM.
2. PREEMPT_RT now, or test the stock kernel's pacing first (§7 step 1)?  →  default: test stock first.
3. Phase 1 zone (A = S-1608, or B = S-0808)?  →  default A.

## 10. References
- Jitter measurements: this session's `dist.py` / `burst.py` over the rig.
- [REAC→AES67 bridge design](2026-05-30-reac-aes67-bridge-design.md) (shares the
  reac_capture / reac_decode / OpenWrt packaging).
- [REAC protocol](../../REAC-PROTOCOL.md). Master-TX feasibility: task #28.

## 11. Implementation status and findings

Status: implemented and validated on real hardware. A continuous tone and live
programme material both reproduce cleanly, with no audible clocking artefacts, at
single-digit-millisecond added latency, and the relay re-locks across a live
sample-rate change at the source without a restart. The clock-recovery problem
flagged below as the central difficulty is resolved; the resolution is recorded
in full.

Two tools implement and validate the design: `tools/pacer_probe.c`, a
feasibility gate, and `tools/reac_repacer.c`, the relay. The probe confirms
that a userspace `clock_nanosleep` loop under `SCHED_FIFO`, pinned to the
interrupt-handling CPU with PM-QoS held at zero wake latency, sustains the slot
period with roughly a microsecond of standard deviation on a stock kernel;
PREEMPT_RT is not required for this pacing.

Building the relay surfaced five findings worth recording.

**Control frames must stay in sequence.** Every REAC frame, including the
periodic control frames (the channel map and the master announce), carries
audio samples in its counter slot. An early version of the relay forwarded
control frames immediately to preserve handshake timing; this delivered their
audio samples ahead of cadence and produced one click per control frame — a
low, roughly periodic artifact once locked, and a denser burst during the
higher control-frame rate of connection setup. The fix is to buffer every frame
type in counter order and pace it uniformly. Control frames carry no timing
penalty this way, because the buffer latency is orders of magnitude below the
protocol's connection-loss timeout.

**Underruns are concealed, never dropped.** A clock-slave receiver tolerates no
gap in the counter sequence. When the buffer underruns, the relay repeats the
previous frame's audio under the next counter value, holding the output cadence
and substituting a brief sample hold for the gap. This requires the relay to own
the output counter sequence: a verbatim repeat would reuse a counter value,
which a receiver's loss detector reads as an almost-complete loss because the
unsigned counter difference wraps. A single repeat lasts one slot period and is
inaudible; only a run of consecutive repeats becomes perceptible, which the
adaptive buffer is designed to prevent.

**The buffer is adaptive, and grows only.** A fixed buffer either wastes latency
on a quiet link or underruns on a busy one, because wireless burst depth varies
with conditions. The relay sizes the buffer to the observed burst depth, but the
direction of adjustment matters: growing the buffer is silent, whereas shrinking
it discards a frame, and every discarded frame is an audible click on a
continuous signal. The default policy is therefore grow-only. The relay starts
below the link's burst floor and grows up into it through smooth holds, reaching
the lowest *clean* latency from beneath and never relinquishing it. Active
reclaim — clawing latency back down after a burst subsides — is available but
off by default, because it trades occasional clicks for lower latency. The
achievable clean latency is a property of the link rather than a fixed figure,
and the grow-only path converges on it without ever crossing below it.

**Clock recovery was the central difficulty, and the resolution was to stop
servoing.** The recovered word clock must follow only the slow rate offset
between the source and the relay's pacing clock, and must ignore the fast
occupancy swings caused by bursts, which the buffer absorbs. A servo that
responds quickly to occupancy instead chases those swings and frequency-modulates
the clock, which is audible; an earlier gain-scheduled servo did exactly this and
produced regular clicks. The working design freezes the pacing clock at the
measured rate match rather than continuously steering it. Two mechanisms then
keep it frozen without drifting. First, the edit deadband is wide — occupancy is
allowed to float across a broad band, so ordinary bursts are absorbed by the
buffer with no frame dropped or inserted, and the steady-state edit count is
zero. Second, a slow re-tune nulls the residual rate offset: it averages the
occupancy drift over several seconds and applies a single small period
correction proportional to that drift, inside a one-slot deadband and clamped to
a few nanoseconds per window. This cancels the accumulating offset between the
two crystals before it can walk occupancy to the edit band, while being far too
slow and too bounded to track bursts. The clock is thus held steady at low buffer
depth, with clock stability and latency control fully separated: the frozen
period plus re-tune owns stability; the grow-only buffer owns latency. A subtle
failure mode found here was a re-tune deadband set wider than the per-window
drift, which let the offset accumulate unobserved until it crossed the edit band
and discharged as a periodic burst of drops; tightening the deadband to one slot
and using a proportional correction removed it.

**Sample rate is detected continuously, not just at startup.** The slot period
is derived from the input packet rate — the protocol emits a fixed number of
frames per second per sample rate — so 44.1, 48 and 96 kHz all run without
configuration. Detection also runs while locked, so a live rate change at the
source is followed without a restart and without manual intervention. Two
guards make this safe. A measured rate is snapped to the nearest standard rate
before it is believed, so a transient packet-rate dip from a link stall cannot be
mistaken for a real rate change. And a change must persist for several seconds
before the relay re-locks, matching the deliberate, infrequent nature of a real
rate change at the console; on a confirmed change the relay re-derives the period
and re-prefills the buffer. The same web configuration can also pin the rate
outright, bypassing detection for installations where the rate never moves.

A persistent service definition replaces the earlier runtime setup: the relay
ships as an OpenWrt package with a procd service and per-zone configuration, and a
companion web application exposes the tunable parameters — buffer depth, the
adaptive policy, the CPU assignment, and the rate (auto or pinned).

## 12. Multiport operation and clock-rate latency control

Two refinements followed from running several streams from one console.

**One daemon, one clock, many ports.** A single source emits all its streams from
one word clock, so the relay handles every port in one process driven by one
real-time pacing thread: one recovered period, emitted to all ports on the same
tick. Each port keeps its own jitter buffer and gap concealment, so a burst or
underrun on one port is contained; only the slow clock is shared, and it is
steered from the active ports so an idle or stalled port cannot pull the others.
The benefit over independent per-port relays is twofold — the ports stay
sample-phase-aligned with each other (mirroring the source's single master
clock), and one real-time thread replaces several contending ones. Ports
auto-activate on detected input: each prefills its own buffer before it emits and
stays dormant until its stream appears, so one configuration covers any number of
connected endpoints, including ones patched in after the daemon starts.

**Latency is reclaimed by clock rate, never by dropping frames.** The earlier
design controlled latency by occasionally dropping or holding a frame. On a
continuous signal each such edit is an audible click, which forced a grow-only
policy: latency could rise to cover a burst but never fall, so it drifted upward.
The resolution is to control latency purely through the playout clock. A slow,
tightly-clamped servo biases the shared period by at most a few hundred parts per
million — a fraction of a cent, and steady rather than wandering, so it is
inaudible (the audibility of a clock offset is in its rate of change, not its
magnitude). Running the clock a hair fast drains accumulated latency smoothly to
the floor; a hair slow fills it; no frame is ever discarded, so reclaiming
latency from a clean signal is click-free. The buffer target is sized to the
observed burst depth across ports — the depth a port's occupancy dips below its
own smoothed level, which is independent of any fixed offset between ports — plus
a safety margin: it grows at once to cover a larger burst and eases down toward
the requirement when the link is calm. The servo then steers the tightest port's
occupancy onto that one shared target. In practice the buffer settles at the
lowest latency the link's bursts allow and holds there, rather than ratcheting
upward. A conservative startup prefill, drained down from above, avoids probing
into underruns while the burst depth is first being learned.

A broader conclusion follows from the clock-recovery difficulty. Carrying a
synchronous transport such as REAC across a variable-latency wireless link is an
inherently adversarial problem, because the buffer must always be sized against
the worst recent burst. Carrying a jitter-tolerant packet-audio format such as
AES67 across the link and regenerating REAC locally — with the relay acting as
the REAC master at the far end — removes the synchronous constraint from the
wireless segment altogether. The relay described here is the transparent,
drop-in fix; the local-master approach is the more robust architecture.
