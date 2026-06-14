# Pace convergence: binary-search SEARCH → LOCK → step-by-step drift correction

- **Date:** 2026-06-09
- **Status:** approved (operator), implementing
- **Component:** `tools/reac_repacer.c` — replaces the glacial `--pll` trim
- **Supersedes the trim half of:** the hold-then-correct PLL (commit 48e6525)

## Problem

The current frequency lock is a **glacial incremental PLL**: every window it nudges the
base period a little, forever. Two failure modes, both observed on-rig 2026-06-09:

- **Incremental-forever:** each nudge is a period *step* → the box's recovered clock jumps
  → an audible tick every window. This is the "metallic, adapting every cycle" the operator
  hears (period changed every ~8 s in the telemetry).
- **Frozen (trig disabled):** the period can no longer match the master, so it sits ~500 ppm
  off (e.g. 249843 ns) and the buffer drains → periodic underrun/recovery → beeps.

Neither matches the operator's model. The clock must **arrive at the master's exact rate and
then hold**, so steady state is silent because the rate is *correct*, not because correction
is forbidden.

## Design — three behaviours

### 1. Warm-start (unchanged)
Seed `period_ns` from the persisted per-port lock so SEARCH starts from a value close to the
master's rate → a narrow initial bracket → few search steps.

### 2. SEARCH (startup / re-converge): binary search
Bisect the emit period to null the buffer **drift** (occ movement per window):
- bracket `[p_lo, p_hi]` (fast↔slow). Cold start: `±g_search_range_ppm`. Warm: narrow.
- each eval window measure `drift = mean_occ - occ_ref`:
  - draining (`drift < -dead`) → period too short/fast → `p_lo = period`
  - filling  (`drift > +dead`) → period too long/slow → `p_hi = period`
  - else (within dead-band) → converged this window
- `period = (p_lo + p_hi)/2`; iterate.
- **converged → LOCK** when the bracket is sub-ppm OR drift stays in the dead-band for K windows.
- Converges in ~log₂(range/precision) windows, far faster + more precise than the glacial ramp.
  Steps here are brief and at startup (and tiny once warm-started), so startup ticks are
  acceptable; steady state is what matters.

### 3. LOCK: hold + step-by-step drift correction
- Hold `period_ns` **dead-constant** (no trims) → silent.
- Monitor occupancy. When `|mean_occ - target|` exceeds **`g_research_ms`** (configurable,
  default a few ms → frames) — i.e. the slow crystal/thermal drift has accumulated — do **not**
  jump or re-bisect. Instead **step by step**: apply small clamped period adjustments
  (`≤ g_step_ppm`, one per window) that both re-null the drift and gently walk occupancy back
  toward target, until back in band → LOCK again.
- These corrections are rare (drift is slow) and tiny (clamped), so they're inaudible — the
  operator's "hold long, tiny steps at a threshold."

## New knobs (live-reconfigurable)
- `--research-ms N`     LOCK→correct drift threshold (occ distance from target). Default ~5.
- `--search-range PPM`  initial SEARCH bracket half-width on a cold start. Default ~1500.
- `--step-ppm N`        max ppm per step-by-step correction in LOCK. Default small (~5–10).
- eval window: reuse `--pll-win` but default it short (~1 s) so SEARCH steps are quick.

## Test (on-rig, operator's ear)
1. Warm-started restart → SEARCH converges in a few windows (telemetry: bracket narrows, then
   `state=LOCK`), period then **held constant**. Listen: sine clean, no per-window tick.
2. Leave running → occ drifts slowly; when it crosses `research-ms`, telemetry shows a short
   run of tiny `step` corrections, then LOCK. Listen: no audible beep at the correction.
3. 48 kHz → 96 kHz jump → auto-rate re-lock, then SEARCH re-converges at the new rate.

## Notes
- SEARCH nulls the *rate* (the audio-critical clock). Occupancy *position* is recovered by the
  same step-by-step bias in LOCK (latency/safety, glitch-free), not by a flush.
- If startup ticks ever matter, SEARCH steps can also ramp; deferred (warm-start makes them tiny).
