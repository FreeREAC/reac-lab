# On-rig REAC capture campaign — plan

**Date:** 2026-05-31
**Status:** Plan, to execute at the venue (needs the live rig)
**Repo:** `FreeREAC/reac-aes67`
**Purpose:** A single structured capture session at the venue that closes the
open questions blocking three threads at once:

1. **Bidirectional feasibility** (REAC TX) — verify the audio-packet header, the
   `cdea` control cadence, and the real-time timing tolerance a sender must meet.
2. **96 kHz de-interleave** (task #21) — confirm the 24-sample × 20-channel byte
   layout against a real 96 kHz stream.
3. **Audio quality** (NEW, 2026-06-02) — REAC now connects and streams cleanly
   (no glitches, no clicking) once the stagebox channel count matched the M-300,
   but the sound is **saturated + unnatural** at 48 kHz, and **44.1 kHz won't
   run**. Audit the signal path: levels, 24-bit justification, channel mapping,
   rate. See Step 8. (The transport investigation in Step 7 is **SUPERSEDED** —
   the lock-flap was a stagebox-capacity mismatch, not the Wi-Fi/VLAN path.)

All steps are **passive capture** except step 5 (bench TX), which requires a
**standalone S-1608** (no console) so nothing in a live show is at risk.

## Expected packet rates (the rate fingerprint — verify on every capture)

REAC carries **no rate field**; the frame is a fixed 1492 B / 40-slot /
12-sample container, so **the packet rate IS the sample-rate fingerprint**
(pps = rate / 12):

| rate | pps | slot | wire Mbit/s (1516 B/frame) | notes |
| --- | --- | --- | --- | --- |
| 44.1 kHz | **3675** | 272 µs | 44.6 | same 40×12 frame; we lack `REAC_MODE_44K1` |
| 48 kHz | **4000** | 250 µs | 48.5 | VERIFIED (4-frame capture → ~4060 pps) |
| 96 kHz | **8000** *or* 4000 | 125 / 250 µs | 97.0 / 48.5 | TWO candidates — capture decides |

REAC is a **100BASE-TX (Fast Ethernet)** design — confirmed by Roland support
("REAC is based on 100BASE-TX … uses the full bandwidth"). 40 ch × 24 bit × 96 k
= 92.2 Mbit/s payload ≈ fills one 100 Mbps link (10 Mbps can't carry >~8 ch;
gigabit isn't used at the link layer). **96 kHz model is UNSETTLED — two live
candidates:** double-pps `{96000,40,12}` (~8000 pps, 40 ch — what reacdriver's
`REACConstants.h` implements: SAMPLES_PER_PACKET=12, PACKETS_PER_SECOND=8000)
vs channel-halving `{96000,20,24}` (~4000 pps, 20 ch — current). The evidence
**leans double-pps**, but it's one reverse-engineered driver, not our wire.
A bigger-frame payload-growth option is **ruled out by the 1500 MTU** (the 48 k
frame already ≈ fills it). Frame size is ~1492 B in both live candidates, so
**pps + live-channel count decide** (Step 4) — not frame size. (The R-1000 "24
tracks @ 96k" that seeded the halving idea was a recorder storage limit.)

## What a REAC capture actually contains (the data model)

A single REAC port is **bidirectional**, and a passive `0x8819` tap captures
**both halves** in one go:

- **Stagebox INPUT channels** (mic/DI jacks) travel *toward the mixer* as raw,
  converted, **pre-patch** PCM — placed on the wire as-is by the stagebox. These
  are the clean per-input sources; the mixer's patchbay decides what they map to
  *inside the desk*, **after** they cross REAC. So inputs on the wire are
  **raw, not patched**.
- **Stagebox OUTPUT channels** travel *from the mixer to the box* and carry
  whatever the mixer **routed** to each output slot (a mix bus / matrix / direct
  out). The mixer is the authority that fills these; on the wire they are
  **post-mixer-routing**. We only observe the result.

REAC is a **transport of discrete channel slots** (up to 40 × 24-bit), not a
mix — every slot is an independent channel. Consequence for bidirectional TX:
feeding the mixer = injecting into the *input* slots (mixer then patches them);
driving a stagebox's outputs = *replacing the mixer* as the authority for the
*output* slots (hence step 5 uses a **standalone** box — two authorities can't
fill the same output slots). The receive side already captures both halves
passively, so only the *inject* side is new work.

### Distinguishing source / target / direction per datagram

All from the wire, no config (confirmed by the 2026-05-31 dual-point capture):

- **Source MAC** → which device/port. Roland OUI `00:40:ab`; e.g. console ports
  `…00:00:01` (zone A) / `…00:00:02` (zone B), stageboxes `…00:00:03` /
  `…00:00:04`.
- **Dest MAC → direction/role.** Mixer→box **OUTPUT** frames are **broadcast**
  (`ff:ff:ff:ff:ff:ff`, full 1492 B — master pushing to all); box→mixer **INPUT**
  frames are **unicast to the console MAC** (smaller). (Matches reacdriver:
  master dhost = broadcast, slave/box unicast to master.)
- **VLAN tag → which REAC port/zone** (11/12/13 = A/B/C on lan1/2/3).

**NOT derivable from the wire:** which *physical jack or patch point* a given
channel **slot** maps to. The frame carries 40 positional slots but no labels
(no "slot 7 = input 7" / "slot 3 = Mix L"); that mapping is convention + lives
in the mixer's patch, invisible to a passive tap. Step 1's labelled-probe
resolves it empirically.

## Prerequisites at the rig

- The two GL-MT6000 routers running, REAC flowing (M-200i/console master +
  S-1608 stagebox), as in the verified 2026-05-29 setup.
- A capture host on the `192.168.10.x` rig LAN (wired into a router LAN port is
  best for full-rate capture — do not capture over the WDS you are measuring).
- `reac-tools` checked out on the capture host; `tcpdump` on the routers.
- For step 5 only: a **standalone S-1608** powered without the console, on a
  port we can transmit to.

> busybox `tcpdump` on the routers has **no `timeout`** — background the capture
> and `kill` it (per the reac-tools capture helper). Prefer `capture-dualpoint.sh`.

## Step 1 — Full-frame audio + control capture (the core unknown)

Goal: resolve the audio packet's own `type[2]` + `data[32]` (admitted-unverified
in reacdriver) and classify audio vs control frames.

- Capture ≥2 s of **all** `ether proto 0x8819` to pcap on a LAN-side tap, full
  frame (`-s0`), both the console→box and box→console directions.
- With `reac-tools` (extend the parser), per frame extract: `counter`, `type[2]`,
  full `data[32]` hex, length, ENDING word. Classify by `type`:
  FILLER `{00,00}`, CONTROL `{cd,ea}`, MASTER_ANNOUNCE `{cf,ea}`,
  SPLIT_ANNOUNCE `{ce,ea}`.
- **Deliverable:** the verified `type[2]` of a real *audio* packet and the
  structure of its `data[32]` — the single most load-bearing TX field.

### Step 1b — Slot ↔ jack mapping (labelled probe)

Goal: resolve the one thing NOT derivable from the wire — which channel **slot**
corresponds to which physical jack / patch point.

- **Inputs:** feed a known tone into a *specific* stagebox input jack (e.g. jack
  7); decode the capture and find which slot in the box→mixer (unicast) frames
  carries it. Repeat for a couple of jacks. Confirms inputs are raw and pins the
  input slot order. (Expectation: jack N → slot N, but verify.)
- **Outputs:** on the console, route a known signal to a *specific* output (e.g.
  Mix L → stagebox out 3); watch which slot in the mixer→box (broadcast) frames
  follows it, and change the patch to confirm the slot tracks the console's
  output routing. Confirms outputs are post-patch.
- **Deliverable:** an empirical slot→jack/patch map for this rig, and
  confirmation of the raw-input / post-patch-output model. (Useful for labelling
  the AES67 channels meaningfully, and required to know where a TX injection
  would land.)

## Step 2 — Decode the `cdea` control cadence

Goal: learn what control metadata a stagebox actually needs (vs reacdriver's
"magic" cadence 8 / 8018 / 7947 / 27 that the author didn't understand).

- From the same pcap, measure how often CONTROL/MASTER_ANNOUNCE frames are
  interleaved among audio frames, and dump the `data[32]` byte sequence across
  successive control frames (the state progression).
- **Deliverable:** the real control-frame cadence + byte sequence a MASTER sender
  must replay for a stagebox to accept audio.

## Step 3 — Timing characterisation (the go/no-go for TX)

Goal: measure the real inter-packet jitter tolerance the rig sustains, and
whether a Linux box can meet it.

- Timestamp every received frame (hardware RX timestamps if the NIC supports
  them; else kernel) → inter-packet interval distribution (mean, max, p99).
  Cross-check with `reac-tools` jitter analysis.
- Separately, bench a Linux TX loop on a **PREEMPT_RT kernel (mainline since
  Linux 6.12)** under **`SCHED_DEADLINE`** (period = the REAC slot; `SCHED_FIFO`
  as fallback) pinned to an **isolated core** (`isolcpus` / `nohz_full` + IRQ
  affinity), waking via `clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME)` to an
  accumulated absolute deadline (no drift; busy-spin the last few µs). Transmit
  dummy `0x8819` frames at the slot rate and measure achieved cadence jitter vs
  the tolerance above. For the tightest pacing prefer **`SO_TXTIME` + the `ETF`
  qdisc (hardware launch-time / TSN)** if the NIC supports it (Intel i210/i225-
  class do — check the target NIC); else `AF_PACKET TX_RING`. Measure **scheduler
  jitter AND on-wire send jitter (hardware TX timestamps) separately** — they are
  different sources.
- **Master vs slave timing:** as MASTER, Linux needs only a *stable, continuous*
  cadence (the whole fabric locks to us → our rate becomes the system rate), so
  RT scheduling suffices; as SLAVE, add a software **clock servo** disciplining
  TX to the master's recovered clock. **Target the MASTER role first.**
- **Deliverable:** go/no-go on timing for an audio-injecting role on RT-tuned
  hardware. NOTE: reacdriver's "kernel scheduling can't do jitter-free playback"
  predates mainline PREEMPT_RT — this step **re-tests that conclusion on an RT
  kernel**, where it is expected to be feasible on a wired host.

## Step 4 — 96 kHz packet-rate + de-interleave (task #21) — UPDATED 2026-06-02

Goal: settle the 96 k model + byte layout. **Two live candidates**, decided by
**pps + live-channel count** (NOT frame size — both are ~1492 B):
double-pps `{96000,40,12}` (~8000 pps, 40 ch — what reacdriver implements) vs
channel-halving `{96000,20,24}` (~4000 pps, 20 ch — current). A third option,
growing the payload to a bigger frame (`{96000,40,24}`, 2880 B audio, ~4000 pps),
is **ruled out**: the 48 k frame already ≈ fills the 1500 B MTU and REAC is
100BASE-TX, so it adds *packets*, not *bytes* (bandwidth = pps × payload, and
payload can't grow). Also bears on the saturated/unnatural symptom (Step 8).

- Set the console/project to **96 kHz**; capture FULL frames with timing:
  `tcpdump -i lanN -xx 'ether proto 0x8819'` for 10–30 s (busybox has no
  `timeout`: `tcpdump … & P=$!; sleep 20; kill $P`). Use `-xx`, **not** `-x`
  (payload-only strips timing).
- Measure **mean inter-arrival / pps** with `reac-tools` + count non-zero
  channel slots:
  - **~8000 pps / 125 µs / 40 active slots ⇒ double-pps** ⇒ set `REAC_MODE_96K`
    to **{96000, 40, 12}** (decode with the verified 48k stride). (reacdriver's
    model — the leaning candidate.)
  - **~4000 pps / 250 µs / 20 active slots ⇒ channel-halving** ⇒ current
    `{96000, 20, 24}` is right after all (or the rig splits 40 ch @ 96 k across
    REAC A+B, 20 ch per 4000-pps link).
  - frame ≈ 2932 B ⇒ payload-growth — but the 1500 MTU says you shouldn't see it.
  Frame is 1492 B either way; **pps + active-slot count disambiguate.**
- Inject a **single-channel full-scale ramp / DC code** and read it back to pin
  the 24-bit byte-justification at 96 k (obs-h8819 is 48k-only — the 96k
  interleave is reverse-engineered from this).
- **Deliverable:** confirmed 96 k model → fix `REAC_MODE_96K` (+ add
  `REAC_MODE_44K1 = {44100,40,12}`); the same capture pins the OUTPUT byte order
  for future TX.

## Step 5 — MASTER-mode bench acceptance test (converts feasibility → yes/no)

**Only with a standalone S-1608, no console.** Goal: does a Linux MASTER sender
drive the stagebox's analog outputs?

- Power the S-1608 standalone. From the Linux box transmit: broadcast
  MASTER_ANNOUNCE + the replayed `cdea` control bytes (from step 2) + a known
  test tone in correctly byte-ordered audio frames (layout from step 1).
- Listen on the S-1608's analog outputs: does the tone play, on the right
  channels, cleanly (no clicks)?
- **Deliverable:** the single experiment that converts bidirectional
  feasibility from "partial" to a definitive yes/no for the drive-stagebox path.
  With RT timing now plausible (Step 3), the variable this isolates is
  **protocol acceptance** — does the box accept our handshake + correctly
  byte-ordered audio frames? Timing is no longer the expected blocker.

## Step 6 (optional, only if SLAVE/feed-mixer-inputs is pursued)

Capture a **real third-party slave/stagebox completing its handshake** with the
console master, to reverse the missing slave-handshake step + the
`handshakeData[][19]` blob semantics that reacdriver cannot supply.

## Step 7 — Why the link won't hold REAC lock (clock-jitter diagnosis, #15)

> **SUPERSEDED (2026-06-02).** Root cause of the lock-flap / "couldn't establish
> communication" was a **channel-count mismatch** — a large (40-ch) stagebox
> connected to an **M-300 (32-ch max)**. With a correctly-sized box, REAC
> connects and streams cleanly over the Wi-Fi / gretap / VLAN path — **transport
> confirmed working**, and not clocking either. The jitter / MTU / cross-VLAN
> hypotheses below are kept for reference only; re-test **only** if instability
> returns with a correctly-matched box. The current open issue is **audio
> quality** — see Step 8.

Separate from "is the payload audio or silence", the rig's standing failure is
that the mixer's **REAC sync LED locks, flashes, drops, and re-acquires** — the
stagebox repeatedly loses sample-clock lock. Leading hypothesis (ranked against
all evidence): **REAC's hardware clock slave cannot tolerate the arrival jitter
the 5 GHz WDS + gretap path injects**, and this is **loss-free** — invisible to
drop counters (0 errors / 113M pkts), so it must be measured as *timing*, not
loss. Airtime/half-duplex contention + mt76 retransmit + A-MPDU re-serialization
are the mechanism. Broadcast-over-Wi-Fi and VLAN cross-mix are down-ranked
(gretap carries each zone as **unicast** GRE to the peer; the LED flapped even
with a **single zone** on 2026-05-29, which alone refutes cross-mix as primary).
Run in order — the first two are decisive:

- **7a — Wired back-to-back control (the clincher).** Temporarily replace the
  WDS air hop with a wired Ethernet link between the two routers, **same
  gretap/VLAN/MTU config**. LED rock-solid on wire while it flaps on Wi-Fi (with
  identical zero-loss counters) ⇒ Wi-Fi jitter proven causal, and every
  air-independent cause (MTU design, console side, clock master) excluded in one
  move.
- **7b — Box-side inter-arrival histogram, single zone.** One zone live;
  dual-point capture the same zone at master-egress (`r1:lan1`, wired) AND
  box-side after the hop (`r2:lan1`) for 30–60 s *while the LED is flapping*
  (`capture-dualpoint.sh`). `python3 -m reac.diff` → expect seq set complete +
  in-order at BOTH (0 loss). `python3 -m reac.cli box.txt --fps 4000` → expect a
  long tail of multi-hundred-µs–ms gaps + back-to-back clusters, far wider than
  egress; time-correlate the worst bursts with the LED dropping. Single-zone
  isolates jitter from cross-mix and from load-scaling.
- **7c — Static MTU + fragmentation check (cheap; do first).** REAC 1492 B inner
  → ~1516 B outer IP → ~1530 on-air **overflows a 1500 MTU**. Find the real
  WDS/wifi netdev (`iw dev` / `ls /sys/class/net`); `ip link show` it + `br-lan`
  + `reactap` + `reactap.11/12/13` and read the MTU column — the recipe's
  MTU-raise-to-1700 loops over *guessed* iface names, so verify it actually took.
  Then `cat /proc/net/snmp | grep '^Ip:'` twice ~10 s apart on the far router:
  climbing `ReasmReqds` / non-zero `ReasmFails` confirms fragmentation; flat-zero
  refutes it. One-line fix if wrong: `ip link set <wifi-iface> mtu 1700` both ends.
- **7d — VLAN isolation / cross-mix ("can the broadcast/multicast cross to
  another VLAN?").** The stagebox is **VLAN-blind** — it decodes *any* `0x8819`
  broadcast/multicast on its access port (the tag is stripped before the box),
  so the VLAN boundary is the ONLY thing isolating zone A from zone B; any leak =
  instant cross-mix (clicking) **and** a second master stream at a different
  counter/cadence hitting a clock slave that expects exactly one → can also
  disturb lock. REAC uses broadcast **and non-IGMP multicast** (hence the
  recipe's `multicast_snooping=0` + forced `bcast_flood`/`mcast_flood`), so both
  are flooded. The config *should* confine that flooding (`br-lan
  vlan_filtering=1`, per-port PVIDs 11/12/13) → this is a **multi-zone**
  contributor, NOT the single-zone flap. Verify, don't assume:
  - **Static (decisive, ~10 s — do first):** on BOTH routers
    `cat /sys/class/net/br-lan/bridge/vlan_filtering` (must be `1`) and
    `bridge vlan show`. Confirm each port/sub-iface is in **exactly one** zone VID
    (lan1/reactap.11→11, lan2/reactap.12→12, lan3/reactap.13→13) and **no port
    sits in two zone VIDs**. Flag two known fragilities: the recipe's silenced
    `bridge vlan del … vid 1 2>/dev/null` (can leave a sub-iface in VID 1 *and*
    its zone VID) and the already-observed **phantom egress tag** — both signal
    shaky tag handling that could break isolation.
  - **Wire:** with A (vid 11) + B (vid 12) live, capture zone B's box port
    (`tcpdump -i lan2 -nn -e -xx 'ether proto 0x8819'`, background + `kill`) →
    `reac.cli --expect-vlan 12 --expect-src <B-console-MAC>` (`detect_crossmix`).
    Any `0x8819` frame from zone A's console MAC (`00:40:ab:00:00:01`) or tagged
    11 = leak proven; zero = excluded.
  - **Tunnel-level:** capture `reactap.11` vs `reactap.12` to check whether the
    single GRE tunnel carries cross-tagged frames between the routers.
- **7e — Jitter vs zone-count / rate scaling.** Repeat 7b at 1, 2, 3 zones (and
  one zone @ 96 kHz). Monotonically worse jitter with offered airtime (loss ~0)
  = airtime contention contributing on top of the single-zone baseline.
- **7f — Airtime/retransmit telemetry + RF confound.** During a flap:
  `iw dev <wifi> station dump` (MCS, A-MPDU, airtime), real retries via
  `ip -s link` (not the mt76 KPI). Compare bench (~−33 dBm) vs 30 m RSSI/MCS —
  worse jitter at range implicates RF/airtime-per-frame (informs HE40 / antenna /
  re-aim).

**Architectural takeaway (already in hand):** raw REAC over Wi-Fi is a
fundamental mismatch — the stagebox is a hardware clock slave with no jitter
buffer. For **monitor / record / route to a computer**, the reac-aes67 bridge is
the robust answer: it decodes on the wired side and carries AES67 (sample-count
timestamp + PipeWire resampler) over Wi-Fi — exactly the de-jitter layer the
Roland slave lacks. **Driving a remote stagebox's analog I/O** over Wi-Fi stays
hard regardless; the only real levers are a wired backhaul or a far more
deterministic single-zone / raised-MTU point-to-point link.

## Step 8 — Signal-quality audit (saturated / unnatural at 48 k; 44.1 k won't run)

**The live priority.** Transport + lock are fine now; the open problem is audio
QUALITY: at 48 kHz the stream is **glitch-free but saturated and unnatural**, and
**44.1 kHz won't run** at all. Glitch-free rules out loss/timing — this is a
**level / sample-format / channel-map / rate** problem, not a packet problem.
Audit in order; **8a is the key split.**

- **8a — Source vs decode A/B (decisive, do first).** Compare the **stagebox's
  own analog output** (the Roland D/A) against **our reac-aes67 → AES67 →
  PipeWire** decode of the *same* signal.
  - Box analog out ALSO saturated/unnatural ⇒ **gain-staging / console config /
    converter level** (input trim too hot, output level) — NOT our code; fix at
    the desk.
  - Box analog out clean but our decode saturated/unnatural ⇒ **our decode**
    (level scaling, 24-bit justification, byte order, or channel map) → 8b.
- **8b — Known-signal level + justification (the truth test).** Inject a
  *calibrated* signal into one channel from the console — sine at known dBFS
  (e.g. −20 and −1 dBFS), a full-scale **ramp**, and a **DC code** — capture,
  decode with `reac-tools`, and check the **numeric 24-bit sample values** vs
  expected:
  - values clipping at ±0x7FFFFF for a −20 dBFS input ⇒ **gain/scaling error**
    (the "saturation");
  - ramp non-monotonic / scrambled ⇒ **byte order / justification** wrong;
  - sign wraps ⇒ **signed/unsigned** error.
  IMPORTANT: `make verify` (cross_verify) only proves **C == Python** — both
  replicate obs-h8819's de-interleave, so it does **not** validate *levels vs a
  known input*. This test is essential and not redundant; it is the
  level/justification half of Step 4's ramp/DC test.
- **8c — Per-channel isolation / bleed (the 32-ch angle).** Feed a tone to ONE
  channel; confirm it appears ONLY there at the right level, adjacent channels
  silent. Bleed between decoded channels ⇒ **de-interleave stride/packing wrong**
  — verify a 32-ch M-300 still fills the 40-slot / 1440 B frame (32 used, 8 idle)
  rather than a different packing; our `REAC_MODE` assumes 40 ch.
- **8d — End-to-end gain/format map.** Trace level through each stage: console
  output meter → REAC wire sample values (`reac-tools`) → AES67 **RTP L24** values
  → PipeWire node level — find WHERE it explodes. Confirm the **SDP-declared rate
  + format** (`L24/48000`) matches the actual data; a rate/format mismatch reads
  as "unnatural" (wrong pitch/scale).
- **8e — 44.1 kHz investigation.** Determine whether the **REAC fabric / these
  boxes support 44.1 at all** (Roland REAC is largely 48/96-native — 44.1 may be
  unsupported or need explicit master-clock config) vs a clock issue (box won't
  lock ⇒ no audio). Our side has no `REAC_MODE_44K1`; if the rig *can* run 44.1
  the decode is rate-agnostic (same framing, `{44100, 40, 12}` → ~3675 pps), so
  add the mode — but first confirm whether 44.1 is even required/possible here.

Most likely (per 8a): either **console gain-staging** (saturated at the source)
or a **24-bit justification/scale bug in our decode** (saturated only in our
path). 8a settles which in one listen; 8b quantifies it.

## Sequencing & outcomes

1–4 are passive and can be done in one sitting. Step 3's go/no-go decides
whether 5 is worth attempting. Outcomes feed back to the repo:

- Step 4 → verify/fix `REAC_MODE_96K`, add a 96 k fixture to `reac-tools`.
- Steps 1–3,5 → a grounded **bidirectional design**. Timing is no longer the
  expected blocker (mainline PREEMPT_RT + `SCHED_DEADLINE` + NIC launch-time —
  Step 3 confirms the achievable jitter); the remaining gate is **protocol
  reverse-engineering** (the handshake blob + audio `l2_type`, Steps 1/2/6). PTP
  / the clock servo folds in for the slave role's master-clock discipline.
- **Step 7 is SUPERSEDED** (lock-flap = stagebox channel-count mismatch;
  transport confirmed working) — run its tests only if instability returns with
  a correctly-matched box.
- **Step 8 is the live priority for tomorrow's session** — the saturated /
  unnatural audio. Do **8a (source-vs-decode A/B)** first: it splits a console
  gain-staging problem from a decode bug in one listen, before any deep capture.

## Non-goals

- No production TX code is written from this campaign — it produces the
  *evidence* a future design needs.
- No changes to the live console/show during steps 1–4 beyond a sample-rate
  switch for step 4; step 5 uses a standalone box only.
