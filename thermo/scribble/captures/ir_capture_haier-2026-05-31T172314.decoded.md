# Decoded Haier Bedroom Capture

Source: `ir_capture_haier-2026-05-31T172314.log`

Device: Bedroom Haier AC remote.

Protocol: Haier YR-W02 / `HAIER_AC_YRW02`, 112-bit AC IR, 38 kHz carrier,
pulse-distance encoding.

Timing observed:

- Header: about 3.1 ms pulse, 3.0 ms space, 3.1 ms pulse, 4.4 ms space.
- Bit mark: about 570 us.
- Zero space: about 530 us.
- One space: about 1.64 ms.
- Checksum: low byte of the sum of bytes 0 through 12.

Representative decoded native frames:

```text
on, cool, 72 F-ish, low fan:
  A6 62 00 00 40 60 80 00 00 00 20 00 05 4D

cool button:
  A6 62 00 00 40 60 80 20 00 00 20 00 06 6E
  A6 62 00 00 40 60 80 20 00 00 20 00 08 70

quiet button:
  A6 62 00 00 40 60 80 20 00 00 20 00 08 ...

off:
  A6 50 00 00 00 40 00 20 00 00 21 00 05 ...
```

Implementation note: use `ONBOARD_IR_PROTOCOL=haier_yrw02` for this room.
The quiet capture was truncated near the checksum, so recapture quiet alone
before relying on that exact button byte.
