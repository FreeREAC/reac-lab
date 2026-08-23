# On-rig session runbook

**Date:** 2026-06-02
**Status:** Ready to execute on-site. Capture + analysis playbooks committed
(`reac-tools/capture-campaign.sh`, `python3 -m reac.characterize`). This is the
ordered "follow it on the day" sheet; the detailed rationale is in
[the capture campaign](2026-05-31-on-rig-capture-campaign.md).

## 0. Settled — do NOT re-litigate
- **Transport is glitch-free.** gretap (L2 GRE) over 5 GHz WDS at MTU 1700 carries
  REAC with **0 errors / 0 dropped over 113M+ pkts**. Keep MTU 1700.
- **Lock-flap/no-comms = a stagebox CHANNEL-COUNT MISMATCH** (40-ch box on a 32-ch
  M-300), not transport, not clocking. The tunnel-jitter theory is **rejected**
  (no Roland source; contradicts the evidence).
- **REAC = 100BASE-TX** (Roland support, verbatim), EtherType 0x8819, 40-ch hard
  cap/connection, protocol latency 0.375 ms, **44.1/48/96 kHz all supported**.
- **Frame geometry is `52 + n × 36` bytes and is RATE-INVARIANT**: 12 samples ×
  3 B per channel slot at every rate, 40 slots on the master's downstream.
- **96 kHz doubles the PACKET RATE, it does not halve the channels.** The model
  is `{96000, 40, 12}` at 8000 pps. Channel-halving `{96000, 20, 24}` is dead.
- **The rate is a wire OBSERVABLE**, not a config-only value: `rate = pps × 12`
  → 3675 pps = 44.1 kHz, 4000 = 48 kHz, 8000 = 96 kHz. A capture settles it.
- **A 96 kHz segment costs 97.0 Mbit/s.** ~10 boxes per gigabit link; plan 8.
- **Current open problem = audio SATURATED + unnatural at 48k, glitch-free** →
  a **signal/format** issue (gain-staging or 24-bit justification), not timing.

## 1. Prerequisites
- On-site on the **192.168.10.x rig LAN** (not reachable from home).
- Both GL-MT6000 up; REAC flowing; **box channel count ≤ console** (verify first).
- Capture host **wired into a router LAN port** (lan1/2/3 = zone A/B/C). **Never
  capture over the WDS hop you are measuring.**
- `reac-tools` + `reac-aes67` (built) + `reac-label` on the capture host.
- **96 kHz needs a 96k-capable console master + the S-1608.** The **M-200i console
  is 48/44.1 only** (A&E spec) — if the M-200i is master, 96k cannot clock (a
  *console* limit, not REAC). Use the M-300/M-5000 as master for the 96k step;
  confirm the silkscreen.
- busybox `tcpdump` has **no `timeout`** → the capture script backgrounds + kills.
- Telnet 8023: no auth, **one client at a time** — close any iPad Remote/RCS first.

## 2. The session (ordered by value)

> Capture script runs ON a router (or via ssh); analysis runs on the host after
> pulling the .pcap. `scp root@192.168.10.1:/tmp/X.pcap .`

> **WATCH #1 — a VLAN tag makes `reac-aes67` *look* broken.** `reac.characterize`
> is the **authoritative analyzer on the day**: it strips any 802.1Q tag and
> decodes either way. `reac-aes67 --dump-samples` currently requires **untagged**
> frames — a tagged capture makes it print `MALFORMED` / `--count-rtp` = 0, which
> looks exactly like a decode bug at the worst moment. These routers have a known
> phantom-egress-tag risk (see [campaign §VLAN](2026-05-31-on-rig-capture-campaign.md)).
> So: **run `python3 -m reac.characterize` on every pcap FIRST.** If it decodes
> fine but `reac-aes67` shows `MALFORMED`, the wire is **tagged, not buggy** —
> confirm with `tcpdump -nr X.pcap -e -c3` (look for `802.1Q`), and either capture
> on an access port that egresses untagged or just trust `characterize`. The C
> decoder's tag-strip is a **post-rig** fix, not needed to get answers today.

**[0] Sanity / topology truth-check.** Confirm REAC flows + box ≤ console.
```sh
ssh root@192.168.10.1 'sh capture-campaign.sh lan1 5 /tmp/s.pcap sanity'   # 5 s smoke
python3 -m reac.characterize s.pcap        # expect 48 kHz ~4000 pps, 1478 B, loss 0
```

**[8a] THE KEY SPLIT (do before any deep decode): is the 48k saturation the
CONSOLE or our DECODE?** A/B-listen the **stagebox analog out** vs our
**AES67→PipeWire** decode of the same signal.
- box out also saturated → **console gain-staging** (input trim too hot) — fix at the desk, not in code.
- box out clean, our decode saturated → **our decode** (justification/level) → [8b].

**[1] LONG 48k baseline** (the corpus for offline decode + control-frame study).
```sh
ssh root@192.168.10.1 'sh capture-campaign.sh lan1 20 /tmp/48k.pcap 48k'
python3 -m reac.characterize 48k.pcap      # confirm steady-state ~4000 pps, 40 slots, types
```

**[8b] NUMERIC truth test** (only if 8a ⇒ our-decode). Inject a **calibrated**
signal (−20 dBFS sine, full-scale ramp, DC code) on one channel; capture; check
the 24-bit values.
```sh
./build/reac-aes67 --pcap 48k.pcap --dump-samples | head    # numeric 24-bit values
python3 -m reac.characterize 48k.pcap                       # 'saturated' count
```
- values pinned ±0x7FFFFF for a −20 dBFS input → **gain/scale error**.
- ramp scrambled / sign wraps → **byte-order / justification**. **Compare against
  `reaccapture`'s s24be AND s24le variants** — our decode uses obs-h8819's
  justification; a be/le mismatch is the prime saturation suspect. `make verify`
  only proves C==Python, NOT correct levels.

**[8c] Per-channel bleed** (32-ch box on 40 slots). One channel hot, rest silent.
```sh
python3 -m reac.characterize onechan.pcap   # expect active == 1; >1 = stride/justification wrong
```

**[4] 96k confirmation capture** (a regression check, NOT a decision — the model
is settled as `{96000, 40, 12}`, 8000 pps, 40 slots). Needs a 96k-capable
master. Use `-s0` full frames; the script already does.
```sh
ssh root@192.168.10.1 'sh capture-campaign.sh lan1 20 /tmp/96k.pcap 96k'
python3 -m reac.characterize 96k.pcap
#   expect ~8000 pps + ~40 active slots.
#   anything else is a rig fault to chase, not a second 96 kHz model.
```
Read the active-slot count as a count of slots carrying SIGNAL. Idle slots are
silent, so a 96 kHz stream feeding only 20 live inputs still reports ~20 active
on a 40-slot frame — that is the patch, not the framing.

**[8e] 44.1k feasibility.** Set the console master to 44.1; capture.
```sh
ssh root@192.168.10.1 'sh capture-campaign.sh lan1 20 /tmp/44k1.pcap 44k1'
python3 -m reac.characterize 44k1.pcap
#   frames @ ~3675 pps -> REAC fine; our gap is missing REAC_MODE_44K1 = {44100,40,12}
#   no frames / box won't lock -> mixer master-clock/project-rate config, not our code
```

**[L] Telnet label scan** (the one thing the tap can't see — slot→name).
```sh
python3 -m reaclabel --host <mixer_ip> --probe                 # confirm transport/model
python3 -m reaclabel --host <mixer_ip> --model m300 --json slots.json
# also try RCQ -> RCS for REAC connection status (verify it exists; see reac-label spec)
```

**Cross-mix / VLAN isolation (cheap, anytime):**
```sh
ssh root@192.168.10.1 'cat /sys/class/net/br-lan/bridge/vlan_filtering; bridge vlan show'
# each port in exactly one zone VID, none in two.
```

## 3. Drive as REAC MASTER — readiness (gated on the ENROLMENT law)
Goal: become the REAC clock master and drive a stagebox's analog outputs.
**Prerequisite is the capture above** — we must observe + decode the real
handshake before we can replay it.

> **The handshake alone gets you silence.** A stagebox channel is digitally
> silent until a **State-4 COMMIT** promotes staged head-amp values into the
> active table. The commit is the sole promoter: it flushes 12 phantom groups
> and replies `01 03 00 10`. An enrol frame does not arm a bank, and a box that
> has announced, connected and is passing frames still carries nothing on a
> channel that never received a committed head-amp record. So a bench test that
> emits MASTER_ANNOUNCE + a control cadence + a tone and hears nothing has
> proven nothing about protocol acceptance. Build the COMMIT into the sequence
> before treating a silent box as a failed handshake. The law and the record
> layout are in FreeREAC/reac-protocol.
>
> Head-amp granularity is three different things, and conflating them is the
> usual way a commit ends up half-built: **SENS and flags are per CHANNEL**;
> **phantom is per FOUR** (`ch >> 2`, and only multiple-of-four records carry
> it); the **readback nibble is per EIGHT** (`ch >> 3`). SENS is 56 legal values
> `0x00..0x37`, flat at ~1 dB/step, 54.60 dB of span measured by electrical
> loopback (−10 dBu at `0x00`). The head-amp placement base is `0x00` on the
> S-0808 and the S-4000S, `0x20` on the S-1608.

- **The sequence (reacdriver `REACMasterDataStream` / `REACSplitDataStream`):**
  master broadcasts **MASTER_ANNOUNCE** (`type {0xCF,0xEA}`; carries `inChannels`/
  `outChannels` + master MAC) → split/slave replies (**SPLIT_ANNOUNCE** `{0xCE,0xEA}`
  / SLAVE_ANNOUNCE control packets) → `SplitAnnounceResponsePacket` →
  `HANDSHAKE_CONNECTED`. Header = `counter[2]` + `type[2]` + `data[32]` with a
  **checksum** (`applyChecksum`). Frame types: FILLER/CONTROL/MASTER_ANNOUNCE/
  SPLIT_ANNOUNCE + CONTROL sub-types incl. SLAVE_ANNOUNCE1-4.
- **Decode the captured handshake with `norihiro/reaccapture`** — it has the
  MASTER_ANNOUNCE decoder + byte offsets that obs-h8819 dropped (e.g. `data[6]==0x0D`
  marks the master announce). This gives us the `data[32]` state progression to replay.
- **Clocking (now plausible):** mainline **PREEMPT_RT** + **`SCHED_DEADLINE`** on an
  isolated core + `clock_nanosleep(TIMER_ABSTIME)`, emitting frames at the slot
  rate (**4000 pps @48k, 8000 pps @96k**) — and **`SO_TXTIME` + `ETF` qdisc**
  (hardware launch-time) if the NIC supports it. Master role only needs a *stable*
  cadence (the fabric locks to us). 0.375 ms = 3 × 125 µs is the latency anchor.
- **Bench acceptance (Step 5, standalone S-1608, NO console — never the live show):**
  emit MASTER_ANNOUNCE + the replayed control cadence + a known tone in
  correctly-justified audio frames; listen on the box's analog outs. This is the
  yes/no for the drive-stagebox path. Remaining gate is **protocol acceptance**,
  not timing (RT retires the timing objection).

## 4. New source to mine: `norihiro/reaccapture`
Linux REAC pcap→WAV decoder, same per-gron lineage as obs-h8819, but carries the
**handshake/MASTER_ANNOUNCE decoder** AND **both s24be + s24le justification
variants**. Clone + read before tomorrow: it likely answers the saturation
(justification) question and supplies the master-handshake bytes.

## 5. Open after tomorrow
- Apply the 96k/44.1 mode fix (#30) once the capture confirms.
- The master-TX path (#28) — captured handshake → reaccapture decode → RT replay →
  standalone-S-1608 bench.
