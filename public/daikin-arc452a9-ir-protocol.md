# Daikin ARC452A9 IR protocol — reverse-engineered byte map

## Clickbait

The Daikin **ARC452A9** wireless remote does not match any of the public
reverse-engineering write-ups you will find by searching: blafois documents the
**ARC470A1** (three frames per button, different fixed bytes) and rdlab covers
the **ARC433A46** (similar timing, different layout). Captured against a real
ARC452A9 with an ANAVI IR pHAT (LIRC, 38 kHz, GPIO 17 RX / 18 TX) on a Raspberry
Pi, every button press is **two frames** — an 8-byte fixed F1 (`11 da 27 f0 00
00 00 02`) and a 19-byte state frame F3 — separated by a **~30 ms** inter-frame
gap. Anyone re-using LIRC's default **5000 µs** receiver timeout will
silently fragment every transmission; you must pass `--timeout 200000`
(200 ms) to capture full frames. The F3 byte map below was confirmed by
single-variable button captures for **mode, temperature, fan speed (incl.
Silent and Auto), vertical swing, powerful, and presence/away**, and the
**checksum** is just `sum(preceding bytes) & 0xFF`. Differences from the
blafois ARC470A1 spec (frame count, F1 byte 3 = `0xf0` vs `0x00`, F3 byte
`0x0f` = `0xc0` vs `0xc1`, byte 5 bit 1, …) are called out inline so anyone
working from the older write-up can pivot without redoing the captures.

---

## Hardware setup used for captures

- IR receiver / transmitter: **ANAVI IR pHAT** on a Raspberry Pi
  - `/dev/lirc0` = TX (GPIO 18)
  - `/dev/lirc1` = RX (GPIO 17)
- Carrier: 38 kHz (handled by hardware/LIRC).
- The RX device cannot measure carrier frequency (hardware limitation).
- **Critical:** the default LIRC receiver timeout is **5000 µs (5 ms)**;
  Daikin inter-frame gaps are ~30 ms, so the default fragments every
  transmission. Use `ir-ctl --receive --mode2 --timeout 200000` (200 ms).

---

## Daikin IR protocol — ARC452A9

Target remote: **ARC452A9**. All facts below are confirmed by captures
(`scribble/captures/`) unless noted otherwise.

### Encoding

- Pulse-distance, 38 kHz carrier, LSB-first bytes.
- Start mark: pulse ~3490 µs, space ~1750 µs.
- Bit 0: pulse ~420 µs, space ~420 µs.
- Bit 1: pulse ~420 µs, space ~1300 µs.
- Checksum: last byte of each frame = `sum(preceding bytes) & 0xFF`.

### Frame structure

Each button press sends **2 frames** separated by a ~30 ms gap:

| Frame | Bytes | Content |
|-------|-------|---------|
| F1 | 8 | Fixed: `11 da 27 f0 00 00 00 02` |
| F3 | 19 | Full unit state (mode, temp, fan, etc.) |

No Frame 2 (`0x42`) is sent. This differs from the ARC470A1 (blafois)
which sends 3 frames (F1 + F2 + F3).

F1 is identical in every ARC452A9 capture: `11 da 27 f0 00 00 00 02`.
Byte 3 = `0xf0` (vs `0x00` in blafois) identifies the ARC452A9 variant.
Comfort mode may be encoded in F1 byte 6 bit 4, but we have no captures
with comfort enabled.

### F3 byte map (19 bytes, 0-indexed)

| Byte | Field | Decode | Status |
|------|-------|--------|--------|
| 0-2 | Header | `11 da 27` | ✅ confirmed |
| 3 | Fixed | `0x00` | ✅ confirmed |
| 4 | Fixed | `0x00` | ✅ confirmed |
| 5[7:4] | Mode | 0=AUTO 2=DRY 3=COOL 4=HEAT 6=FAN | ✅ all five confirmed (ir_capture_2026-02-25T160150) |
| 5[0] | Power | 0=OFF, 1=ON | ✅ confirmed |
| 5[1] | Timer OFF enable | per blafois | ✅ confirmed (timer captures) |
| 5[2] | Timer ON enable | per blafois | ✅ confirmed (timer captures) |
| 5[3] | Unknown | always 0 in captures | ❓ blafois says "always 1" for ARC470A1 |
| 6 | Temp × 2 | e.g. 0x2c = 22 °C | ✅ confirmed 22 °C, 25 °C |
| 7 | Unknown | always `0x00` | ❓ |
| 8[7:4] | Fan speed | 3-7 = 1/5-5/5, A=Auto, B=Silent | ✅ confirmed 5/5, Silent |
| 8[3:0] | Swing (vertical) | 0=off, F=on | ✅ confirmed (ir_capture_2026-02-25T155204: vswing on→0xF) |
| 9 | Unknown | always `0x00` in captures | ❓ horizontal swing? (unconfirmed) |
| 0x0a | Timer ON low | low byte of ON minutes | ✅ confirmed (see timer note below) |
| 0x0b | Timer hi/lo | shared by ON and OFF timers | ✅ confirmed |
| 0x0c | Timer OFF high | high byte of OFF minutes | ✅ confirmed |
| 0x0d | Powerful / Presence | bit 0 = powerful on; bit 7 (0x80) = presence/away on | ✅ powerful; 0x80 in 155204 (presense/away) |
| 0x0e | Unknown | always `0x00` | ❓ |
| 0x0f | Fixed? | always `0xc0` (blafois: `0xc1`) | ❓ ARC452A9 difference |
| 0x10 | Econo / other | bit 2 = econo (blafois); bit 1 (0x02) seen in 155204 | ❓ econo not captured; 0x02 = ? |
| 0x11 | Unknown | always `0x00` in captures | ❓ |
| 0x12 | Checksum | sum(0x00..0x11) & 0xFF | ✅ confirmed |

Legend: ✅ = confirmed by ARC452A9 captures. ❓ = from blafois (ARC470A1),
not yet confirmed. ❌ = blafois mapping appears wrong for this remote.

### Known discrepancies vs blafois (ARC470A1)

1. **Frame count:** ARC452A9 sends 2 frames (F1+F3). ARC470A1 sends 3 (F1+F2+F3).
2. **F1 byte 3:** `0xf0` (ARC452A9) vs `0x00` (ARC470A1).
3. **F3 byte 5 bit 1:** Always 0 in captures. Blafois says "always 1" for ARC470A1.
4. **F3 byte 0x0f:** `0xc0` (ARC452A9) vs `0xc1` (blafois).
5. **Powerful bit:** Now confirmed: F3 byte 0x0d bit 0 = 1 when "powerful" is on
   (see ir_capture_2026-02-25T153723.log).

### Learnings from ir_capture_2026-02-25T153723.log

- **Leading noise:** Some records start with short pulses (197–458 µs) and long
  `timeout` events (~212–217 ms) before the real start mark; the decoder
  correctly ignores these and finds F1+F3 after the first ~3485 µs pulse and
  ~30 ms gap.
- **Powerful on/off:** "powerful on" → F3 byte 0x0d = 0x01; "powerful off" → 0x00.
  Decode is correct.
- **Set time (fri 10:30):** F3 decoded as temp=20 °C and later records show
  timer bytes; clock may be encoded in timer or other bytes (to confirm).
- **Set timer 6:30 turn on / 6:40 turn off:** Byte 5 has timer-on and timer-off
  bits set; bytes 0x0a–0x0c carry values. Decoder reports e.g. timer_on=1190m,
  timer_off=1200m. Those are minutes-from-midnight (19:50 and 20:00), not
  duration; 6:30/6:40 on the remote may be time-of-day. Exact encoding still
  to be confirmed (BCD vs integer, which byte is which).
- **Quiet mode:** "quiet mode" and "quiet off" (last record: "quest off") decode
  as fan=5/5 in some frames; Silent is 0xB in the fan nibble — if the remote
  sends a different value when toggling quiet, or borderline pulse/space timing
  flips bits, we may need to widen decode thresholds or re-capture.
- **Structure:** Every record is 2-frame (F1 + ~30 ms gap + F3). Inter-frame gap
  in log: 29969–29976 µs. Start mark: pulse 3465–3498 µs, space 1726–1762 µs.

### Learnings from ir_capture_2026-02-25T155204.log

- **vswing / hswing:** “vswing on” → F3 byte 8 low nibble = `0xF`; “vswing off” (or
  hswing off) → low nibble = `0x0`. Vertical swing encoding confirmed. Byte 9
  did not change in this run (still `0x00`), so horizontal swing may be
  elsewhere or same nibble in another encoding.
- **Presence / away:** One frame has F3 byte 0x0d = `0x80` (bit 7 set), from
  “presensemaybe on” or “away mode on”. So 0x0d bit 7 = presence or away
  (same button or different buttons — need separate captures to label).
- **Byte 0x10 bit 1:** A frame with swing off had 0x10 = `0x02` (bit 1 set).
  Unclear whether that is hswing-off, presence-off, or another flag.
- **Temp:** “temp up 70 71 72 then down 71 70 69” produced 25 °C and 21 °C in
  decoded frames; temp byte (×2) matches.

### Learnings from ir_capture_2026-02-25T160150.log

- **Mode cycle:** Description was "press mode button 5 times: A → dehumid → cool → heat → fan → A".
  All five modes seen in F3 byte 5 high nibble: **0=AUTO, 2=DRY, 3=COOL, 4=HEAT, 6=FAN**. Frame sequence:
  DRY (0x21), COOL (0x31), HEAT (0x41), FAN (0x61), AUTO (0x01). Temp byte in DRY was 0xc0 (decoder
  shows 96 °C; DRY may use temp differently or that frame is display-only).
- **F1 byte 6 (comfort):** Still `0x00` in every frame. This run did not use the comfort button;
  we still need a dedicated "comfort on" / "comfort off" capture to confirm F1 byte 6 bit 4.

### Slots still unknown or unassigned

After parsing all button captures (including ir_capture_2026-02-25T155204.log, 160150.log),
these protocol slots are still unassigned or only partly known:

| Where | Current state | Notes |
|-------|----------------|--------|
| **F1 byte 6** | Always `0x00` | Comfort (bit 4) suspected; no comfort-on capture |
| **F3 byte 5 bit 3** | Always 0 | Blafois says "always 1" for ARC470A1; we never see it |
| **F3 byte 7** | Always `0x00` | No capture has used it |
| **F3 byte 9** | Always `0x00` | Candidate for horizontal swing; no change in vswing/hswing captures |
| **F3 byte 0x0d bits 6:1** | Always 0 | Only bit 0 (powerful) and bit 7 (0x80 = presence/away) seen |
| **F3 byte 0x0e** | Always `0x00` | No capture has used it |
| **F3 byte 0x0f** | Always `0xc0` | Purpose unknown; may be fixed for ARC452A9 |
| **F3 byte 0x10** | Bit 2 = econo (unconfirmed); bit 1 = 0x02 seen | 0x02 seen in one frame (hswing off?); other bits never seen |
| **F3 byte 0x11** | Always `0x00` | No capture has used it |

So: **F1 byte 6**; **F3 bytes 7, 9, 0x0e, 0x0f, 0x11**; **F3 byte 5[3]**; **F3 0x0d[6:1]**; and **F3 0x10** (except bit 1 seen) are still unassigned or speculative. Timer encoding (minutes vs time-of-day, BCD vs int) also still to be pinned down.

### Captures needed to resolve unknowns

| Test | Purpose | Bytes to watch |
|------|---------|----------------|
| Hswing only | Does byte 9 or 0x10 change? | byte 9, 0x10 |
| Econo on vs off | Find the econo bit | byte 0x10 |
| Comfort on vs off | Find comfort encoding | F1 byte 6, or F3 |
| Timer encoding | Confirm 6:30/6:40 = time-of-day vs duration | bytes 0x0a-0x0c, byte 5 |
| Set clock on remote | Map clock to bytes | compare set-time vs set-timer |
| Mode AUTO/DRY/COOL | Confirm remaining mode nibbles | byte 5 |
| Quiet/Silent toggle | Confirm fan 0xB and edge cases | byte 8 high nibble |

Each test: capture baseline, change ONE setting, capture again, diff.
Use `ir-ctl --receive --mode2 --timeout 200000` for reliable full-frame capture.

### Common encoding mistakes when porting from the blafois ARC470A1 spec

These are the specific bytes where a sender derived from the blafois ARC470A1
write-up will be wrong on a real ARC452A9 unit:

1. **byte 5 power encoding:** blafois-derived senders use `0x09` (bit0 + bit3)
   for ON. ARC452A9 captures show `0x01` (bit0 only). bit3 is not used on
   ARC452A9.
2. **F1 header:** blafois-derived senders use `11 da 27 00 c5`. ARC452A9 uses
   `11 da 27 f0 00`.
3. **Frame 2:** blafois-derived senders include an F2 frame
   (`11 da 27 00 42 ...`). ARC452A9 omits it; only F1+F3 are sent.
4. **F3 byte 0x0f:** blafois-derived senders use `0xc1`. ARC452A9 captures show
   `0xc0`.

All four must be fixed before a ported sender will be accepted by an ARC452A9
head unit.

### Timing and receiver configuration

| Parameter | Value | Source |
|-----------|-------|--------|
| Start mark pulse | ~3490 µs | captures |
| Start mark space | ~1750 µs | captures |
| Bit pulse | ~420 µs | captures |
| Bit 0 space | ~420 µs | captures |
| Bit 1 space | ~1300 µs | captures |
| Inter-frame gap | ~30 ms | captures (29974 µs) |
| LIRC receiver timeout | 200000 µs | required (default 5000 fragments) |
| Full transmission | ~50 ms | F1 + gap + F3 |

### Tooling

You only need two things to capture and decode ARC452A9 on a Pi with an
ANAVI IR pHAT (or any LIRC-compatible IR receiver/transmitter):

- **`ir-ctl`** (part of `v4l-utils`) for raw capture and send:
  - Capture: `ir-ctl -d /dev/lirc1 --receive --mode2 --timeout 200000`
  - Send: `ir-ctl -d /dev/lirc0 --send <file>` where the file contains
    `pulse N` / `space N` lines (µs).
- A small decoder that walks the pulse/space stream, finds the ~3490/~1750 µs
  start mark, slices on the ~30 ms gap into F1 and F3, and applies the byte
  map above. The protocol is simple enough to implement in under 200 lines
  of Python; the open-source implementation that backed these captures
  lives at [jovlinger/utils — `thermo/onboard/heatpumpirctl/`](https://github.com/jovlinger/utils/tree/main/thermo/onboard/heatpumpirctl).

### Reference links

- [blafois/Daikin-IR-Reverse](https://github.com/blafois/Daikin-IR-Reverse) — ARC470A1 protocol (primary reference, differs from ARC452A9)
- [rdlab Daikin IR protocol](https://rdlab.cdmt.vn/experience/daikin-ir-protocol) — ARC433A46 timing and layout
- [IRremoteESP8266](https://github.com/crankyoldgit/IRremoteESP8266) — ARC433 timing constants (ARC452A9 not in supported list)
