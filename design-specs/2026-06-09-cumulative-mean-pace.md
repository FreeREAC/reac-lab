# Pace = cumulative counter-mean (final rate source)

- **Date:** 2026-06-09
- **Status:** implemented (0.2.2)
- **Component:** `tools/reac_repacer.c`
- **Supersedes:** the binary-search SEARCH (`2026-06-09-binary-search-pace.md`)

## Principle

The master's REAC PLL is a hardware crystal — **constant**. So the true pace is the
long-term average, immune to WiFi jitter:

```
period = (ns elapsed since frame #1) / (frames sent since frame #1)
```

"Frames sent" comes from the REAC frame counter (byte 14-15, +1/frame), so it is immune
to WiFi *losses* (a dropped frame still advances the counter). As frames accumulate the
mean sharpens (endpoint-jitter / elapsed → <1 ppm in seconds) — far better than the binary
search, whose 1 s windows floored resolution at ~250 ppm (the 59 ppm residual that drove
the metallic). Measured on-rig: converges within ±5 ns of the full-span value by ~5 s.

## States (`--pll`)

- **CONVERGE** (`pll_state==0`): `period_ns = cm_ts_elapsed / cm_seq`, refined every window
  from the per-stream accumulator filled in `fwd_rx`. After `--converge-s` (default 20 s) →
  **FREEZE**.
- **LOCK** (`pll_state==1`): `period_ns` **frozen** — never touched. Emit rate = input rate
  ⇒ occupancy holds with no drift, so **no steady-state recenter is needed**.
- The recenter is **startup/safety only**: when occ is far past `--research-ms` (a cold-start
  drain, or a real thermal drift) it biases the *emit* (`period`) temporarily to refill, and
  **leaves `period_ns` frozen** — so it can never corrupt the measured rate.

## Hot sample-rate change (48↔96↔44.1 kHz)

The continuous auto-rate detector sees the family change (counter rate 9-100 %), re-locks,
and **resets the cumulative-mean accumulator** (`cm_have=0` per port) so the pace re-converges
at the new rate from frame #1.

## Knobs
`--converge-s` (converge seconds), `--research-ms` (drift band), `--drift-mode hard|slow`,
`--step-ppm` (slow clamp). Counter-mean needs no pin: it self-corrects a wrong cold seed.

## Known residuals (follow-ups)
- **Cold-start occ drain:** box-resync on restart drains ~0.14 s; exceeds the link-check-capped
  buffer, so occ lands low. Recenter refill is slow (averaged occ lags). A one-shot fast
  startup refill on the *raw* occ is the fix.
- **Sine-only granular/beep:** the ~6 µs emit IFI jitter (MT6000 scheduling + WiFi-IRQ) wobbles
  the box's recovered clock — audible on a pure tone, **masked by music** (operator: "almost
  perfect on music"). This is the software-emit floor; a hardware word-clock/genlock is the
  only path below it.
