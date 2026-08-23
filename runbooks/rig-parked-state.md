<!-- SPDX-License-Identifier: GPL-3.0-or-later
     Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com> -->

# REAC Wi-Fi rig — parked state (2026-06-13)

**Status:** working, symmetric, boot-persistent, documented. Parked here until
the **i226 + PTP hardware** (see §8). This is the canonical description of what
is actually running on `reac1` / `reac2`.

> The OpenWrt **apk** path (`reac-rig`, `REAC-RIG-INSTALL.md`) was deliberately
> **not** used. The hand-tuned shell scripts below are what produce the
> ear-validated "very good" audio; a declarative apk cutover was higher risk for
> no gain on hardware that is about to be replaced. The apks remain staged on
> reac1 (`/root/reac-apks/`) for a future clean-room build.

## 1. Topology

```
 M-5000 (master, FPGA)                                 stageboxes (S-series)
   REAC A/B/C                                              REAC A/B/C
      │ wired                                                  │ wired
   ┌──┴───────────┐        5 GHz WDS (AP↔STA)         ┌─────────┴──┐
   │   reac1      │  gretap "reactap" + VLAN 11/12/13 │   reac2    │
   │ (desk side)  │═══════════════════════════════════│ (stage)    │
   └──────────────┘                                    └────────────┘
   lan1=A(VID11) lan2=B(VID12) lan3=C(VID13)   ← same VLAN map both ends →
```

- **Fabric:** `reactap` = gretap tunnel (reac1 .1 ↔ reac2 .2) over the 5 GHz WDS
  (`reac-wds`; reac1 = AP, reac2 = STA). REAC rings are 802.1q VLANs **11=A,
  12=B, 13=C** tagged over the gretap, bridged into `br-lan` with the matching
  `lanN` access port (PVID `1N` untagged). Built at boot by `/etc/rc.local`.
- **De-jitter is directional** and happens **after** the WDS (where the jitter
  is added), on the consuming side:
  - **reac1** re-paces the **upstream** (box→master): `reactap.1N → lanN`,
    protecting the **phase-strict M-5000 input**.
  - **reac2** re-paces the **downstream** (master→box): `reactap.1N → lanN`,
    feeding the **PLL-tolerant boxes**.
  - The opposite direction on each node is plain bridge-forwarded; an `nft
    table bridge reac` drops the bridge's copy of the re-paced direction so the
    box/master never sees a double (raw + re-paced) frame.

## 2. Per-node final config

| | **reac1** (upstream→master) | **reac2** (downstream→boxes) |
|---|---|---|
| Binary | `/root/reac-repacer-good` (Jun-11 latch-fixed) | `/usr/bin/reac-repacer-clk` |
| Ports | `reactap.12:lan2 reactap.11:lan1 reactap.13:lan3` (B is port 0) | `reactap.11:lan1 reactap.12:lan2 reactap.13:lan3` |
| Direction flags | `--forward-only --pll --pace-by-downstream` | `--forward-only --bcast-only` |
| Clock source | `--clock-source local` | `--clock-source local-in` |
| ETF egress | **lan2=80 µs**, lan1/lan3=300 µs | none |
| Common | `--servo-clamp-ppm 0 --prefill-ms 30 --cpu 2 --clock-margin-ppm 8 --detect-ms 2000` | (same) |
| Restore script | `/root/reac1-restore.sh` | `/root/reac2-restore.sh` |
| Boot | `S99reac-rig` → restore script | `S99reac-rig` → restore script |

### Why the asymmetry is intentional (do NOT "flatten" it)
- **reac1 → phase-strict master:** needs kernel-timed egress (`--etf`) and a
  disciplined emit (`--pll --pace-by-downstream`, `--clock-source local`). Both
  ports latch `clk=wire +0 ppm`.
- **reac2 → PLL-tolerant boxes:** the boxes recover the clock themselves, so it
  free-runs `--clock-source local-in` and needs **no** ETF. Adding ETF here
  would gain nothing and risks dropping frames that lack `SO_TXTIME`.

### Why ETF is per-port on reac1
`lan2` (B) was the only port **tuned and ear-validated** (80 µs = the "tighter"
win on 2026-06-13 ~01:28). `lan1` (A) and `lan3` (C) stay at the **proven 300 µs
default**: A at 80 µs was never ear-confirmed and the operator's faint
impression was "A slightly beepy", so A was returned to its validated baseline.
Reverting A to 300 µs also let its buffer fill to a healthy ~58 ms (it sat
shallow at ~32 ms under 80 µs).

## 3. REAC-C (lan3 / VID 13)
Fully **configured and symmetric** on both nodes (VLAN 13, `reactap.13`, nft
drop, 3rd re-pace port) but **idle** (`rx=0`) — no C box is currently plugged.
Plug a box into both routers' `lan3` and it is carried with no further config.
Tune `lan3`'s ETF on reac1 if C ever proves it needs it.

## 4. Verified health (2026-06-13, post-replug)
Both nodes: `clk=wire +0 ppm`, full **8000 fps** (96 kHz, `per≈125000 ns`) on
A+B, **PLC frozen** (zero active concealment in steady state). reac1 buffers
~58 ms; reac2 ~9 ms. Operator: sounds **as good as before**.

> The large *cumulative* `under/plc` counters are scars from the restart/DGS
> transients. Judge health by the **delta** (frozen = clean), never the total.

## 5. Boot persistence
Power-cycle is safe on **both** nodes: `rc.local` rebuilds the gretap fabric,
then `S99reac-rig` waits for `reactap.11` and runs the restore script (which
relaunches the re-pacer). reac1's init was previously present-but-disabled;
enabled 2026-06-13.

## 6. Recovery (if a box goes dark or after a reboot)
`sh /root/reacN-restore.sh` on the affected node, then **replug the stagebox**
(reac2 side; the M-5000 REAC cable only if a ring stays dark). Pre-close-out
backups: `/root/reacN-restore.sh.pre-closeout`.

## 7. Known watch-items (not faults)
- **reac2 downstream buffer can settle shallow (~9 ms).** Stable + clean now;
  if stage monitors click under load, raise reac2's `--prefill-ms`.
- **Faint, unconfirmed impression:** A slightly "beepy", B slightly "granular".
  Too slight to affirm; recorded for the i226 A/B comparison.

## 8. The residual floor — RE-OPENED, do not buy hardware on it yet
The remaining ~3.6 Hz wobble / ~111 clicks-per-second floor was attributed to
reac1 pacing the upstream phase by the downstream while its **frequency clock is
the router's local oscillator**, not the master's — a hardware limit of the
mt7531/MTK GMAC (no PTP hardware clock, no ETF offload), curable only by moving
to an **Intel i226** with HW PTP + ETF offload.

**One candidate cause has been examined and excluded; the stated one has not
been examined at all.**

The candidate came from `reac-pw`, where the same symptom family was measured on
2026-08-23 and the oscillator was **not** the cause. There the pacing loop
re-based its deadline onto every late wake — `deadline = now + period` instead of
`deadline += period` — abandoning a slot on each overrun, **~3.6 slots per
second**. Accumulating the deadline absolutely moved wire drift from
**−526.7 ppm to −8.7 ppm** and cut graph→wire latency by 66 ms, on unchanged
hardware. Given the `~3.6` in both places, the mechanism was worth checking here.

**EVIDENCED — `reac-repacer` does not have that defect.** `tools/reac_repacer.c`
initialises the emit deadline once (`:1509`) and thereafter only accumulates it,
carrying the fractional nanoseconds so the mean cadence is exactly the base
period (`:1757`); `clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME)` sleeps *to*
that absolute deadline. The one re-base onto a fresh clock read (`:1845`) is a
deliberate re-lock on a detected sample-rate change, which also re-prefills the
ring — correct behaviour, not the defect. The deadline rule is stated as law in
that repo's `docs/internals.md`, under "The recovered output clock". The two
`~3.6`s are therefore most likely coincidence, and fact-8's mechanism does not
explain this floor.

**UNVERIFIED — the oscillator attribution itself.** Excluding one cause does not
restore another. Nothing has ever tested that reac1's frequency clock is what
sets this floor; it was asserted, and an i226 was scoped from the assertion.

**The measurement that now matters** needs no new gear and no hardware spend:
**ask the counter, which discriminates.** A frame the link LOST leaves a gap in
the REAC sequence counter; a slot the pacer never RAN leaves the counter
contiguous. So a capture of reac1's egress separates "the link dropped it" from
"we never sent it" with no timing analysis at all. Count contiguous-counter holes
in time over a long run: if they cluster at ~3.6/s the floor is in the emit path
after all, and if the counter is clean the emit path is exonerated and the clock
source becomes the live suspect for the first time.

Until that is run, treat "software ceiling" as a hypothesis and the i226 purchase
as unjustified.

> A capture long enough to answer this needs a tool that survives the counter
> wrap. The 16-bit counter turns over every 65536 frames — 8.2 s at 96 kHz — and
> the reac-tools instruments used to key a dict on the raw value and sort it,
> which silently truncated anything longer and spliced what remained. Fixed
> 2026-08-23 (`reac_codec.order_by_counter`); check you are on that or later
> before trusting a long run.

## Appendix A — `/root/reac1-restore.sh`
```sh
#!/bin/sh
# reac1 (master-side) — upstream de-jitter (box->master), forward-only, ETF egress.
kill $(pgrep -f reac-repacer) 2>/dev/null; sleep 1
modprobe nf_tables_bridge 2>/dev/null
for v in 11 12 13; do
  ip link set reactap.$v master br-lan
  bridge vlan del dev reactap.$v vid 1 2>/dev/null
  bridge vlan add dev reactap.$v vid $v pvid untagged
done
for i in 1 2 3; do
  ip link set lan$i master br-lan
  bridge vlan del dev lan$i vid 1 2>/dev/null
  bridge vlan add dev lan$i vid 1$i pvid untagged
done
nft delete table bridge reac 2>/dev/null
nft -f - <<'NFT'
table bridge reac {
  chain c {
    type filter hook forward priority 0; policy accept;
    iifname "reactap.11" oifname "lan1" drop
    iifname "reactap.12" oifname "lan2" drop
    iifname "reactap.13" oifname "lan3" drop
  }
}
NFT
modprobe sch_etf 2>/dev/null || insmod /lib/modules/6.12.87/sch_etf.ko 2>/dev/null
for p in lan1 lan2 lan3; do
  d=300000; [ "$p" = lan2 ] && d=80000   # lan2(B) ear-validated 80us; A/C proven 300us
  tc qdisc del dev $p root 2>/dev/null
  tc qdisc add dev $p root etf clockid CLOCK_TAI delta $d 2>/dev/null
done
setsid /root/reac-repacer-good --forward-only --port reactap.12:lan2 --port reactap.11:lan1 --port reactap.13:lan3 --pll --servo-clamp-ppm 0 --prefill-ms 30 --cpu 2 --clock-source local --pace-by-downstream --clock-margin-ppm 8 --detect-ms 2000 --etf >/tmp/rp-up.log 2>&1 </dev/null &
sleep 2
echo "reac1 restored: $(pgrep -af reac-repacer | sed 's|/root/||')"
```

## Appendix B — `/root/reac2-restore.sh`
```sh
#!/bin/sh
# reac2 (box-side) — downstream de-jitter (master->box), forward-only + bcast-only. No ETF.
kill $(pgrep -f reac-repacer) 2>/dev/null; sleep 1
modprobe nf_tables_bridge 2>/dev/null
for v in 11 12 13; do
  ip link set reactap.$v master br-lan
  bridge vlan del dev reactap.$v vid 1 2>/dev/null
  bridge vlan add dev reactap.$v vid $v pvid untagged
done
for i in 1 2 3; do
  ip link set lan$i master br-lan
  bridge vlan del dev lan$i vid 1 2>/dev/null
  bridge vlan add dev lan$i vid 1$i pvid untagged
done
nft delete table bridge reac 2>/dev/null
nft -f - <<'NFT'
table bridge reac {
  chain c {
    type filter hook forward priority 0; policy accept;
    iifname "reactap.11" oifname "lan1" drop
    iifname "reactap.12" oifname "lan2" drop
    iifname "reactap.13" oifname "lan3" drop
  }
}
NFT
setsid /usr/bin/reac-repacer-clk --forward-only --bcast-only --port reactap.11:lan1 --port reactap.12:lan2 --port reactap.13:lan3 --servo-clamp-ppm 0 --prefill-ms 30 --cpu 2 --clock-source local-in --clock-margin-ppm 8 --detect-ms 2000 >/tmp/rp-ds.log 2>&1 </dev/null &
sleep 2
echo "reac2 restored: $(pgrep -af reac-repacer | sed 's|/root/||')"
```
