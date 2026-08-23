# reac-label — mixer-driven AES67 channel labeller — Design

**Date:** 2026-05-31
**Status:** Approved design; prototyping against the VMXProxy simulator.
**Repo:** new, under the `FreeREAC` org (`FreeREAC/reac-label`), pairing
with `reac-aes67`.

## Goal

Query a Roland V-Mixer / M-5000 over its remote-control protocol (TCP 8023) and
build a **slot → human name** table, so `reac-aes67` can label the AES67
channels it emits — turning "REAC-A slot 22" into the desk's channel name
("Vocal 1"). **Read-only:** the labeller never sets/controls the mixer.

This supplies the one thing the passive REAC tap **cannot** see: the
slot↔channel↔name mapping, which lives in the mixer's patch, not on the wire.

## Background (verified by research, 2026-05-31)

- **Protocol:** ASCII, framing `STX(0x02) + 3 letters + ':' + CSV args + ';'`.
  Over telnet, STX is dropped and the `0x06` ack renders as the text `OK`.
  3rd letter = action: **C**=set, **Q**=query/GET, **S**=status reply.
- **Transport:** TCP **port 8023**, single connection at a time, **no auth**.
  No unsolicited push → the labeller must **poll**.
- **Models (all testable here):** M-200/M-200i (32 in), M-300 (32), M-480 (48),
  **M-5000** (128, OHRCA). M-5000 has a native LAN server; M-200i's telnet must
  be enabled in its LAN menu; older V-Mixers may be RS-232C-only → reachable via
  a serial↔TCP bridge (VMXProxy listening on 8023). Same command vocabulary
  across all.
- **The key queries:**
  - `CNQ:I<ch>;` → `CNS:I<ch>,"<name>";` — channel name (6 chars; blank = 6
    spaces).
  - `PIQ:I<ch>;` → `PIS:I<ch>,RAI<slot>;` — **input patch**: which REAC input
    slot feeds this channel (`RAI1..RAI40` = REAC A in, `RBI*` = REAC B,
    plus `CI*`, `STIL/STIR`, `FX*`, `PLAY*`, `OFF`).
  - `POQ:RAO<slot>;` → `POS:RAO<slot>,<source>;` — **output patch**.
  - `FDQ`/`MUQ`/`VRQ`/`RCQ` — fader, mute, version, REAC connection status.
- **Open references:** `bitfocus/companion-module-roland-m5000` (Node, proven
  query path, per-model channel counts), `JamesCC/VMXProxyPy` (Python; ships
  Roland's protocol PDF AND a **mixer simulator** + `simrc.txt` of real
  command/response pairs → hardware-free development).

## The join (slot → name)

`PIS` gives **channel → slot** (`I2 → RAI22`). To label REAC slot *N* we invert:
scan `PIQ` across all channels, build `slot → channel`, then join with `CNQ`'s
`channel → name`:

```
for ch in 1..model.inputs:
    name[ch]  = CNQ(ch)
    slot[ch]  = PIQ(ch)        # e.g. RAI22
slot_to_name[ slot[ch] ] = name[ch]   # RAI22 -> "Vocal 1"
```

The `RAI<n>`/`RAO<n>` index is exactly the REAC slot index `reac-aes67`'s tap
keys on, so the label lands on the correct AES67 channel directly. (M-5000 OHRCA
uses 128 free paths and may use different port tokens than `RAI/RAO` — detected
and branched at runtime; see Open questions.)

## Architecture (isolated, testable units)

```
mixer (TCP 8023)
  → mixer_proto   pure: frame a Q command, parse an S reply (no I/O)
  → mixer_client  thin socket: connect, line I/O, poll loop, ret/reconnect
  → label_join    pure: CNQ+PIQ results -> slot_to_name table
  → label_sink    write the table where reac-aes67 reads it (file/ubus)
```

- **`mixer_proto` (pure):** `frame(cmd, args) -> bytes` and
  `parse(line) -> {action, target, args}`. Handles the STX/telnet variants and
  `ERR:<n>` / `OK`. Unit-tested against canned strings + `simrc.txt` pairs.
- **`mixer_client` (thin I/O):** TCP connect to `host:8023`; send `CMD;\r\n`,
  read until `;`/`OK`; single-connection aware; reconnect on drop; **poll**
  cadence configurable (names fetched once at startup like the Companion module;
  fader/mute optionally polled).
- **`label_join` (pure):** consume `CNS`/`PIS` results → `slot_to_name`
  (keyed `RAI<n>`/`RAO<n>` → name). Unit-tested.
- **`label_sink`:** publish the table for `reac-aes67`. **Decision:** a simple
  JSON file (e.g. `/var/run/reac-label/slots.json`) the daemon reads + optional
  ubus method — keeps the two tools decoupled (labeller can run/restart
  independently; daemon degrades to numeric labels if absent).
- **`model` table:** per-model input/aux counts (M-200/300=32, M-480=48,
  M-5000=128) sizing the scan.

## Language

Prototype in **Python** — matches VMXProxy (the simulator + protocol PDF are
Python), fastest path to a working labeller against the sim, and the protocol is
line-oriented (no real-time constraint, unlike the C audio daemon). A later C
port into `reac-aes67` is possible but not needed: the labeller is not on the
audio path, so Python on the router is fine. (If on-router footprint matters,
revisit.)

## Dev & test strategy (hardware-free first)

1. **Against the VMXProxy simulator:** stand up VMXProxy's mixer sim (`simrc.txt`
   canned names/patch/levels), point the client at it, prove the full
   CNQ+PIQ→slot_to_name join end-to-end with **no hardware**.
2. **Unit tests** for `mixer_proto` (frame/parse incl. STX vs telnet, ERR, OK)
   and `label_join` (invert+join, OFF/unpatched channels, REAC A vs B slots).
3. **On real hardware (all four models available):** confirm transport
   (native LAN vs enable-telnet vs serial-bridge), the `VRQ`/`CNQ`/`PIQ`/`POQ`
   responses, and the slot-token format — especially the **M-5000 OHRCA** token
   format vs the V-Mixer `RAI/RAO`.

## Operational constraints

- **Single connection at a time:** the labeller must be the sole 8023 client, or
  contend with an iPad Remote/RCS session. Document; consider VMXProxy fan-out if
  concurrent control is needed.
- **No auth on the mixer:** anything on the control subnet can read/control it —
  keep the mixer's control port on a trusted segment (the LAN4/5 / 192.168.10.x
  side), not exposed.
- **Poll, don't expect push:** names fetched at startup; re-poll on an interval
  for live renames; fader/mute polled only if a live view wants them.

## Non-goals

- **No control/write** (no setting faders/mutes/patch). Read-only.
- **No live mixing UI.** This labels channels; it is not a mixer remote.
- **Not on the audio path.** It produces metadata; `reac-aes67` keeps emitting
  audio regardless of whether the labeller is running.

## Open questions (resolve on hardware)

- **M-5000 OHRCA patch tokens:** 128 free paths may not use `RAI/RAO`; confirm
  `PIS`/`POS` token format on the real M-5000 and branch the join accordingly.
- **Exact transport per model:** native TCP (M-5000), telnet-enable (M-200i),
  or serial-bridge (older) — confirm with a `nc <ip> 8023` probe + `VRQ;`.
- **REAC connection status via `RCQ` → `RCS` (the "monitor REAC over telnet"
  path):** our notes record `RCQ` = REAC-connection-status query (see Background
  above). On the real mixer, confirm it exists and capture: the `RCS` response
  format and exactly what it reports (link up/down, sample rate, which
  racks/zones are online, error/fault state), plus the practical poll cadence.
  **Decide whether it is granular/fast enough to observe the sync lock-flap, or
  only coarse connected/disconnected** — the hardware clock-recovery PLL state is
  likely below the remote-control API, and the protocol is **poll-only (no
  push)**, so sub-second flap may be invisible from telnet. Pair telnet `RCQ`
  (coarse connection state + labels) with the **wire-side health monitor in
  reac-aes67** (fine-grained jitter/lock view) — see that repo's packaging spec.
  Also probe for any broader system/status command and read Roland's protocol
  PDF (shipped in VMXProxy `docs/`) to enumerate the full command set.
- **Fader value encoding** (dB range/INF/step) — only matters if we add a live
  fader view; not needed for labelling.
