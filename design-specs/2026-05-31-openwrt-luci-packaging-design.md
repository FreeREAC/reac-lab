# reac-aes67 — OpenWrt packaging + LuCI app design

**Date:** 2026-05-31
**Status:** Implemented — both apk cross-built for aarch64 (`mediatek/filogic`)
and mips (`ramips/mt7621`) (2026-05-31). Validated end-to-end on hardware on a
Cudy WR2100 (`ramips/mt7621`); GL-MT6000 (`mediatek/filogic`) on-device smoke
pending. See Phased delivery below.
**Repo:** `linuxnow/reac-aes67`
**Depends on:** the M2 daemon (decode → media-clock → PLC → AES67 send), built.

## Goal

Ship `reac-aes67` as installable OpenWrt packages on an OpenWrt 25.12 router
(**apk**-based, musl; aarch64 `mediatek/filogic` e.g. GL-MT6000, or mips
`ramips/mt7621` e.g. Cudy WR2100), managed entirely from the web UI: enable/
disable + start/stop, per-stream parameter editing, **live status** (RT data,
like Wi-Fi/DHCP pages), and **SDP/discovery** info so PipeWire/AES67 receivers
can subscribe.

## Packages

Three apk packages (built via the OpenWrt SDK on an aarch64 build pod, task #22):

1. **`reac-aes67`** — the C daemon + UCI default config + procd init script.
   Depends on: libc (musl), and `libubus`+`libblobmsg-json` (for the live-stats
   ubus object). NOT libpcap on the device (live path uses raw `AF_PACKET`;
   pcap is dev-only).
2. **`luci-app-reac-aes67`** — the client-side LuCI app (JS views + menu + ACL).
   Depends on: `reac-aes67`, `luci-base`.
3. *(optional later)* **`luci-i18n-reac-aes67-*`** — translations.

OpenWrt 25.12 uses **apk** (not opkg) — packages are produced as `.apk` by the
SDK; the feed `Makefile` is the standard OpenWrt package recipe (the SDK emits
apk on 25.12 automatically). NOTE per project memory: this is the apk-based
generation, confirmed by the gretap recipe's `apk add`.

## Single source of truth: UCI

`/etc/config/reac-aes67` — config in UCI, runtime state over ubus, never mixed.

```
config reac-aes67 'global'
    option enabled       '1'        # master on/off

config stream 'a'                    # up to 3 stream sections
    option enabled       '1'
    option name          'REAC-A'    # -> RTP/SDP session + PipeWire node name
    option iface         'lan1'      # capture interface (vlan 11 zone)
    option rate          '48000'     # 48000 | 96000 (NOT wire-detectable: set here)
    option mcast_addr    '239.69.0.1'
    option mcast_port    '5004'
    option payload_type  '97'
    option ssrc          '11223344'  # hex
    option ttl           '1'
    option plc_xfade     '0'         # 0 = default min(S,8)
    option plc_fade_pkts '0'         # 0 = default ~50ms
```

- Options 1 & 2 (enable/disable, params) WRITE this; the daemon READS it;
  options 3 & 4 (status, SDP) REPORT derived state.
- 40 ch @ 48k / 20 ch @ 96k is implied by `rate` (channel count is not a
  separate option — it's a property of the mode).

## procd init script (`/etc/init.d/reac-aes67`)

- Iterates UCI `stream` sections; for each `enabled` one (and global enabled),
  spawns a `reac-aes67 --listen <iface> --udp <mcast_addr>:<mcast_port>
  --rate <rate> --pt <payload_type> --ssrc <ssrc> --ttl <ttl> [--plc-* ...]`
  instance under procd (`procd_open_instance` per stream, respawn on crash).
- Sets the `CAP_NET_RAW` capability (the daemon needs raw `AF_PACKET`); via
  procd `seccomp`/`capabilities` or a file capability set at install.
- `enable`/`disable` = procd boot integration; `reload`/`restart` re-reads UCI.
- LuCI buttons drive this through rpcd's `luci.reac-aes67` / standard
  `service` ubus calls.
- **Multi-instance resolution: one daemon process per stream** (matches the ≤3
  independent-zone model, procd idioms, and crash isolation). This is the
  decision the rest of the doc builds on.

## Live status: daemon ubus object

Each daemon instance registers a ubus object **`reac-aes67.<name>`** (one per
stream — see the multi-instance resolution below). Its `status` method returns
that stream's live stats:

```json
{
  "name": "REAC-A", "iface": "lan1", "rate": 48000, "channels": 40,
  "running": true, "uptime_s": 1234,
  "packets_per_sec": 4000, "rtp_seq": 51210,
  "loss_total": 7, "loss_per_min": 0,
  "plc_tier": "clean|crossfade|burst_fade|hold_last|silence",
  "mcast": "239.69.0.1:5004", "ssrc": "11223344"
}
```

- Source data already exists in the pipeline: `media_clock` has loss/seq, `plc`
  knows the last tier used, a small rate counter gives pps. We add a
  `stats` struct updated per packet and a periodic ubus publish.
- This is the canonical OpenWrt pattern (hostapd/dnsmasq expose state via ubus);
  LuCI polls it. Implemented with `libubus` + `libblobmsg-json`.
- Multi-instance resolution: **one daemon process per stream** (matches the ≤3
  independent-zone model + procd idioms + crash isolation), each registering its
  own ubus object **`reac-aes67.<name>`** (e.g. `reac-aes67.REAC-A`). The LuCI
  status view enumerates them with `ubus list 'reac-aes67.*'` and calls `status`
  on each. No shared collector process. (This supersedes any "single object"
  phrasing elsewhere in this doc.)

## Network separation: AES67 off the REAC segment

REAC is the timing-critical clock domain and is heavy (~48 Mbit/s broadcast per
zone at 48 k); it is isolated on its own VLANs/ports (lan1/2/3 = VLAN 11/12/13).
AES67 egress MUST be a **separate L2 network** so it never shares the REAC
segment's airtime/flooding. **No daemon change** achieves this: the daemon sends
each stream's RTP to its UCI `mcast_addr`, and the kernel routes that out the
interface owning the route to the group. Decision: route-by-multicast-subnet —
put the AES67 group (e.g. `239.69.0.0/24`) on a dedicated **`aes67` bridge**
that can carry a separate **Wi-Fi SSID** and/or a **reserved ethernet port**.
Example OpenWrt network/wifi config: `openwrt/files/network-aes67.example`. The
`aes67` bridge must NOT be bridged with the REAC capture interfaces.

## SDP / discovery

- Per stream, render an AES67 SDP from the same config. Implemented: the daemon
  `--print-sdp` mode (uses `sdp_build`) emits `v=0 / s=<name> / c=IN IP4
  <mcast>/<ttl> / m=audio <port> RTP/AVP <pt> / a=rtpmap:<pt> L24/<rate>/<ch> /
  a=ptime:1 / a=recvonly`. LuCI shows it + a download button (calls the binary
  via rpcd, or renders from UCI client-side).
- Optional SAP announce (multicast 239.255.255.255:9875) so receivers
  auto-discover — stretch goal, behind a per-stream `sap` flag.

## LuCI app (`luci-app-reac-aes67`, client-side JS)

OpenWrt 25.12 = modern client-side LuCI (JS, ubus/rpcd backend), not Lua CGI.

- **Config view** (`view/reac-aes67/streams.js`): `form.Map` over the UCI file —
  global enable + a `TypedSection` of streams with the fields above; Save&Apply
  writes UCI + reloads the service.
- **Status view** (`view/reac-aes67/status.js`): enumerates `reac-aes67.*` ubus
  objects and polls each one's `status` method on a timer (poll.add), rendering
  a per-stream table (pps, loss, PLC tier, rate, channels, seq, uptime) — the
  Wi-Fi-status-like dashboard.
- **SDP**: shown per stream on the status (or a dedicated) view with copy +
  download.
- **Menu + ACL**: `root/usr/share/luci/menu.d/luci-app-reac-aes67.json` (under
  Services), `root/usr/share/rpcd/acl.d/luci-app-reac-aes67.json` granting read
  of the `reac-aes67` ubus object + UCI read/write of `reac-aes67`.

## Testing

- Daemon ubus object: unit-testable by calling the publish function and
  asserting blob contents; integration via `ubus call reac-aes67 status` on the
  aarch64 pod.
- UCI→procd: lint the init script; on the pod, `service reac-aes67 start` with a
  test UCI and assert instances spawn with the right args.
- LuCI JS: manual + the standard `luci` lint; the config form maps 1:1 to UCI so
  most risk is in the ubus status wiring (covered by the daemon test).
- The pure audio path stays covered by the existing 27 C tests + cross-verify;
  packaging adds no logic to it.

## Phased delivery

1. **L1 (done)** — daemon `pipeline_stats` (pure, unit-tested) + `ubus_stats` object
   `reac-aes67.<name>.status` + `sdp` generator (tested). (task #24)
2. **L2 (done)** — `/etc/config/reac-aes67` UCI schema + procd init (one daemon per
   stream) + `CAP_NET_RAW` capabilities json. (task #25)
3. **L3 (done)** — `luci-app-reac-aes67`: config form + live status (ubus poll) +
   SDP + menu/ACL. (task #26)
4. **L4 (done)** — OpenWrt feed Makefiles for both packages; **apk built via the
   x86_64 cross-SDK in a Fedora container** (`.build/build-apk.sh`), output
   `reac-aes67-0.1.0-r1.apk` + `luci-app-reac-aes67-0.1.0-r1.apk` for
   `aarch64_cortex-a53`. Daemon ELF verified aarch64-musl, links real libubus.
   (task #23) — **NOTE the build needs NO aarch64 pod**: the SDK is x86_64 and
   cross-compiles. An aarch64 pod is only for running the native test suite.
5. **L5 (pending)** — on-device install + smoke on the GL-MT6000 (task #27).

## Future enhancement — REAC link-health monitor (LuCI/ubus)

The daemon already decodes the live REAC stream, so it can publish **REAC link
health that the mixer's telnet API cannot** — the Roland remote protocol is
mixing-centric and **poll-only**, and even its `RCQ` REAC-connection-status query
is coarse and unpushed (see the reac-label spec), so it can't show the
sub-second sync lock-flap. Extend `pipeline_stats` + the LuCI status view with,
per zone:

- **inter-arrival jitter** (mean / max / p99 vs the ~250 µs slot) — the direct
  proxy for clock-lock stability (the cause of the sync-LED flap; see the
  capture-campaign clock-jitter diagnosis);
- **counter-gap events** (already tracked) + a running **"last cadence break /
  inferred lock-loss" timestamp**;
- **frame rate + last-seen** — is REAC A/B/C actually flowing right now?

This makes the daemon a push-capable, fine-grained REAC-health monitor. Clean
split: **wire-side (reac-aes67) for link HEALTH**, **telnet (reac-label) for
channel LABELS/patch + coarse `RCQ` connection state.**

## Open questions (defer to implementation)

- Setting `CAP_NET_RAW`: procd capabilities mask vs file capability at install
  vs running as root (simplest on a single-purpose appliance).
- SAP auto-discovery: include in v1 SDP view or defer to L4+.
- Whether the OpenWrt SDK feed recipe needs per-package tweaks for apk vs the
  default emit (confirm on the aarch64 pod build, task #22/#23).
