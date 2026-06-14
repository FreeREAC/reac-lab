# REAC re-pacer — ETF kernel-timed egress + `local-in` clock repeating

- **Date:** 2026-06-11
- **Status:** best working version installed; one residual open (0.8 Hz warble)
- **Component:** `tools/reac_repacer.c`, plus a built `sch_etf.ko` kmod

## The problem this attacks

Downstream (mixer→box) is flawless; upstream (box→mixer) carries a faint warble.
Confound-free profiling (decode the 360 Hz loop sine, plain-LE offset 50 sample-major,
FFT) showed: silence is perfectly clean, harmonics −73 dB, broadband floor −94 dB —
so the artifact is **pure timing jitter**, manifesting as **FM sidebands on the
carrier** (dominant ±0.8 Hz at ~−27 dB, plus a 15–30 Hz cluster).

**Why the asymmetry** (the key mental model): the downstream is a one-way flow *into*
the box's clock domain — the box recovers its word-clock from the arriving cadence and
plays/relays everything synchronised to that one clock, so any mismatch between the
box's recovered clock and the mixer's true clock is *invisible* (self-consistent). The
upstream is the **only clock-domain crossing**: the box captures at its clock, the mixer
reads at the mixer's clock. On a direct wire those are physically identical (PHY clock
recovery). Through our rig the box's clock is a *reconstruction* of the mixer's, right
rate but with residual wobble — and the upstream is the one place that wobble becomes
audible. Same physical jitter: harmless one direction, permanent the other.

## The best-version architecture

Two re-pacers, each made a **faithful clock-repeater of the mixer** (mimicking the
single-clock-domain of a direct wire):

- **reac1 (upstream, OUT = mixer):**
  `--clock-source local` (counts the mixer's downstream frame-counter on the *wired*
  lan1 = exact master rate) + `--pace-by-downstream` (PI loop phase-aligns the emit to
  the mixer's TDM slot, ~69 µs answer offset) + `--etf` (stamps SO_TXTIME and lets the
  kernel `sch_etf` qdisc release each frame on a hr-timer) + `--clock-margin-ppm 8`
  (hold, don't thrash) + `--detect-ms 2000` (move the rate-detect off the audible
  16 Hz). ETF tightened egress cadence **3.6 → 1.4 µs** (measured, AF_PACKET TX ts).

- **reac2 (downstream, OUT = box):**
  `--clock-source local-in` (NEW: the clk_meter binds the *IN* interface = `reactap.11`,
  the mixer's downstream over WiFi — drop-immune frame counter = mixer's exact rate)
  `--clock-margin-ppm 8 --detect-ms 2000`, **no ETF**. This collapsed the box-vs-mixer
  beat **−71/+58 ppm → ~−10 ppm**. ETF on reac2 *backfired* (disturbed the servo +
  underruns) — the box is a tolerant PLL slave and does not need it.

New `reac_repacer.c` flags this session: `--etf` / `--etf-lead-ms` (SO_TXTIME emit via
`tx()` wrapper, clockid CLOCK_TAI, txtime = MONOTONIC deadline + TAI offset, loose
pre-sleep); `--clock-source local-in` (g_clock_in → clk_meter binds IN.ifindex); a PI
integral on the `--pace-by-downstream` phase loop.

## Building `sch_etf.ko` (it's mainline but unpackaged by OpenWrt)

stock OpenWrt 25.12.4 / mediatek-filogic / kernel 6.12.87. The package layer prunes a
hand-added `kmod-sched-etf`, so build out-of-tree against the SDK-prepared kernel:
```
# in the openwrt-sdk-25.12.4-mediatek-filogic_*; after one `make package/kernel/linux/compile`
KDIR=build_dir/.../linux-6.12.87 ; TC=staging_dir/toolchain-*
curl -o /tmp/m/sch_etf.c "https://git.kernel.org/.../net/sched/sch_etf.c?h=v6.12.87"
echo 'obj-m := sch_etf.o' > /tmp/m/Makefile
PATH=$TC/bin:$PATH make -C $KDIR M=/tmp/m ARCH=arm64 CROSS_COMPILE=aarch64-openwrt-linux-musl- modules
# vermagic = "6.12.87 SMP mod_unload aarch64" → insmod loads; etf qdisc needs clockid CLOCK_TAI
```
Kept at `.build/sch_etf.ko-6.12.87`; deployed to `/lib/modules/6.12.87/` + `/etc/modules.d/sch_etf` on both routers. Same recipe builds `sch_cbs`/`sch_taprio`.

## Results / state

From "everything metallic" → quality much improved, rig working. Downstream flawless;
upstream much cleaner; both clocks ~8000 pps; the chain is one clock domain again.

## Open issue (next, fresh)

Residual ±0.8 Hz FM warble (~−27 dB) on captured audio. A 6-point loop audit
(`/tmp/reac_audit.sh` recipe) showed the warble is **seeded by reac2's downstream clock
estimate** (the WiFi-fed `local-in` meter breathing at ~1 Hz, pt3 −21.4 dB) which the
box bakes into its A/D (pt4 −16 dB). ETF on reac2 made it worse (not emit jitter — it's
the clock *value*). Next: stabilise reac2's IN-meter against WiFi gaps (don't re-anchor
on a >250 ms drop; the counter is drop-immune), and a direct-wire control to bound the
box's own PLL floor. Prior art (per-gron/reacdriver) hit the same software-REAC
master/slave jitter wall and shipped listen-only — our ETF + clock-repeater approach is
past that.
