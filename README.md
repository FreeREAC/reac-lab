# reac-lab

Field captures of REAC traffic for [FreeREAC](https://github.com/FreeREAC) —
*REAC Exposed Audio Communications* — with a short notes file per capture
describing the gear, the link, and what the capture shows. Captures are added
to [`captures/`](captures/README.md) as they are cleared for publication.

The reference material lives in the other FreeREAC repositories:
`reac-protocol` holds the wire format and the protocol facts, and `reac-docs`
holds the engineering findings. **`reac-protocol` wins every disagreement**
with anything said elsewhere, this repository included.

## Two facts worth carrying

These two settle most of what older REAC write-ups get wrong:

- **96 kHz doubles the PACKET RATE; it never halves the channel count.** The
  frame is 40 channel slots × 12 samples × 3 B at every rate — geometry
  `52 + n × 36` bytes, rate-invariant. 3675 packets/s at 44.1 kHz, 4000 at
  48 kHz, 8000 at 96 kHz.
- **The rate is a wire observable.** It is not a wire *field*, but
  `rate = pps × 12` reads it off any capture. A configured rate is a
  legitimate pin, not the only source.

## On sources and sanitization

Everything here is FreeREAC's own work and observations. Site-, venue-, and
client-specific details (hostnames, SSIDs, LAN addresses, device MACs) are
stripped or replaced with neutral examples before a capture is published. No
vendor binaries or decompilation listings are reproduced here.

`tools/freereac_ops.py check` keeps it that way: it refuses working notes,
plans and session runbooks in this tree, which belong to the project's private
working repository.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
