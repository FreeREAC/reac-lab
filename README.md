# reac-lab

The **raw working material** behind [FreeREAC](https://github.com/FreeREAC) —
*REAC Exposed Audio Communications*. Dated design specs, a working journal, and
the on-site runbooks that the clean repos are distilled from. Sorted and
sanitized, but **raw**: this is the lab notebook, not the polished reference.

For the distilled, reader-facing material — the protocol reference and the
engineering findings — see the `reac-protocol` and `reac-docs` repos in the
[FreeREAC organization](https://github.com/FreeREAC).

## Read this before you open a dated document

**`reac-protocol` wins every disagreement with anything here.** A dated document
in `design-specs/` or `journal/` records what was believed and measured *on that
date*. That is the archive's whole job, so those bodies are not rewritten when a
later measurement contradicts them — rewriting them would destroy the record of
how the answer was reached. Where a document's central claim has since been
refuted it carries a **SUPERSEDED** banner at the top naming the claim and the
measurement that killed it; the body below the banner is history, not
instruction.

`runbooks/` are the exception and are corrected in place. A runbook tells
someone to go do something on a live rig, so a stale one costs a session rather
than a wrong belief.

Two refutations account for most of the banners, and are worth carrying into any
old document you read here:

- **96 kHz doubles the PACKET RATE; it never halves the channel count.** The
  frame is 40 channel slots × 12 samples × 3 B at every rate — geometry
  `52 + n × 36` bytes, rate-invariant. 3675 packets/s at 44.1 kHz, 4000 at
  48 kHz, 8000 at 96 kHz.
- **The rate is a wire observable.** It is not a wire *field*, but
  `rate = pps × 12` reads it off any capture. Documents saying it must come from
  config are wrong; a config `rate` is a legitimate pin, not the only source.

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
