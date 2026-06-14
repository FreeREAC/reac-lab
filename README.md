# reac-lab

The **raw working material** behind [FreeREAC](https://github.com/FreeREAC) —
*REAC Exposed Audio Communications*. Dated design specs, a working journal, and
the on-site runbooks that the clean repos are distilled from. Sorted and
sanitized, but **raw**: this is the lab notebook, not the polished reference.

For the distilled, reader-facing material — the protocol reference and the
engineering findings — see the `reac-protocol` and `reac-docs` repos in the
[FreeREAC organization](https://github.com/FreeREAC).

## Layout

- `design-specs/` — dated design specs for the REAC→AES67 converter, the Wi-Fi
  de-jitter re-pacer, and the OpenWrt fabric, in the order they were worked out.
- `journal/` — dated working-journal entries (findings, decisions).
- `runbooks/` — on-site field sheets: the capture session, the rig install, the
  parked-state restore, the PipeWire receiver setup.
- `captures/` — packet captures and per-capture notes.

## On sources and sanitization

Everything here is FreeREAC's own work and observations. Site-, venue-, and
client-specific details (hostnames, SSIDs, LAN addresses, device MACs) have been
stripped or replaced with neutral examples. Firmware reverse-engineering findings
are re-expressed in the `reac-protocol` firmware-findings doc — they are not
reproduced here as vendor binaries or decompilation listings.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
