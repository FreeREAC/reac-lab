# `--clock-source` — select the re-pacer's clock reference

- **Date:** 2026-06-09
- **Status:** approved, implementing
- **Component:** `tools/reac_repacer.c` (0.2.x line)

## Problem

The re-pacer's only clock loop is the occupancy-nulling PLL: it adjusts the emit
period to hold the jitter-buffer fill constant. Holding the buffer constant is
mathematically identical to matching the emit rate to the **input** rate — and the
input is the frame stream arriving over the WiFi tunnel. So the emit clock tracks
the **WiFi arrival cadence** (the far-end device's clock, smeared by WiFi delivery
jitter). The local stagebox recovers its word clock from that emit, so the WiFi
jitter sits *inside* the box's clock loop → the box's A/D produces the audible
"metallic" noise.

Evidence (2026-06-09): transport is bit-faithful (re-time only, frames unmodified);
downstream/D-A path is pristine (coherence 0.991); only the jitter-sensitive A/D is
corrupted (upstream ~0.91 over WiFi vs 0.99 on the *same box* wired). A pure clock
problem — the box recovers word-clock "from the packet-arrival cadence."

## Design

Add **`--clock-source {wifi|local}`** (default `wifi`, hot-reconfigurable via SIGHUP/UCI):

- **wifi** — current behaviour, unchanged. Emit period ← occupancy-nulling PLL →
  tracks the WiFi arrival rate.
- **local** — emit period ← the **local wired device's measured cadence**, so WiFi
  carries data only, never timing. The box then recovers a clock sourced from a
  clean wired reference instead of the smeared tunnel rate.

### Components (all in `reac_repacer.c`)

1. **Local-cadence meter.** Sniff the inbound REAC frames on the OUT interface and
   measure their median inter-frame interval = the local device's true clock.
   - reac2 (downstream, OUT=lan1): the box's **upstream** unicast.
   - reac1 (upstream, OUT=lan1): the master's **downstream** broadcast.
   Reject the WiFi-side (IN-interface) frames — only the OUT device's stream is the
   reference.
2. **Clock loop B.** In `local`, drive the emit period from the meter (slow lock to
   the local cadence) instead of the buffer-null loop.
3. **Rate-adapter.** Locking to the local clock decouples emit rate from buffer fill,
   so the buffer drifts (master crystal vs box crystal). On sustained over/underflow,
   a controlled slip (drop/duplicate one frame at a low-energy sample), logged, so the
   slip rate (= crystal offset) is observable.
4. **Telemetry.** Add `clk=wifi|local` and `slip=N` to the per-port line.

## Test

Flip `--clock-source local` on the live daemon; play stage inputs into REAC-A; listen
→ metallic gone? Read upstream coherence (→ 0.99?). Watch the slip rate and that the
REAC link holds. Flip back to `wifi` to A/B instantly.

## Risks

- Slip rate = the master↔box crystal offset; if large it becomes audible. Mitigation:
  a slow ASRC instead of a hard slip (follow-up if the offset is too wide).
- The meter must measure only the OUT-interface device's stream; a stray
  WiFi-side observation would defeat the whole point.
