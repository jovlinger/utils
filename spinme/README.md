# ESP32 as Volumio Remote -- Investigation & Plan

**Goal:** Use ESP32-based knob/touch boards as wireless volume (and playback)
remotes for a Volumio server on the local network -- WiFi or Bluetooth as
available.

Python / Cursor agent notes: [`AGENTS.md`](AGENTS.md) (venv conventions also in
root [`AGENTS.md`](../AGENTS.md)).

## Hardware (two boards)

Both are in inventory. Research for each lives in its own directory; pin maps and
firmware are **not** interchangeable.

| Board | Directory |
|-------|-----------|
| Elecrow CrowPanel 1.28" rotary (SKU **DHE38128D**) | [`hardware/elecrow-crowpanel-1.28/`](hardware/elecrow-crowpanel-1.28/) |
| Waveshare ESP32-S3-Knob-Touch-LCD-1.8 (dual MCU) | [`hardware/waveshare-knob-touch-lcd-1.8/`](hardware/waveshare-knob-touch-lcd-1.8/) |

Index: [`hardware/README.md`](hardware/README.md).

### Snapshot

| | Elecrow CrowPanel 1.28 | Waveshare Knob-Touch 1.8 |
|--|------------------------|---------------------------|
| MCU | ESP32-S3R8 only | ESP32-S3R8 + ESP32-U4WDH |
| Display | GC9A01 SPI, 240x240 | ST77916 QSPI, 360x360 |
| Touch | CST816D | CST816 |
| USB flash | Native USB-Serial/JTAG | Type-C orientation selects MCU |
| Live probe 2026-09-07 | Yes (MAC `1c:db:d4:b3:6c:fc`) | Research from wiki/community (recovered) |

## Progress summary

| Item | Status |
|------|--------|
| **Elecrow identity / OTA / display docs** | Done under `hardware/elecrow-crowpanel-1.28/` |
| **Waveshare research** | Recovered under `hardware/waveshare-knob-touch-lcd-1.8/` |
| **Volumio API** | Documented below; host probe: `miniDSP-SHD.local` answers getState (2026-09-07) |
| **Firmware scaffold** | Pending (prefer PlatformIO Arduino + OTA partitions per board) |

**Next steps:** (1) Per-board PlatformIO scaffold. (2) Confirm Volumio commands on
`miniDSP-SHD.local`. (3) Encoder -> HTTP on chosen board.

## Shared: Volumio API

- REST on port 3000. On this LAN (2026-09-07): **`http://miniDSP-SHD.local`**
  responds; `volumio.local` did not resolve from the research host.
- Key endpoints: `GET /api/v1/getState`;
  `GET /api/v1/commands/?cmd=volume&volume=plus|minus|mute|unmute|<0-100>`;
  `GET /api/v1/commands/?cmd=play|pause|toggle|stop|prev|next`.
- Docs: https://developers.volumio.com/api/rest-api

## Shared: development shape

Suggested mapping (either board): encoder CW/CCW -> volume plus/minus; button ->
toggle or mute. Optional later: display from getState, haptics where present
(Waveshare DRV2605).

Toolchain default: Arduino ESP32 core via PlatformIO; ESP-IDF if OTA/layout needs
it. MicroPython is optional, not factory default on the probed CrowPanel.

```text
Encoder/touch -> firmware logic -> WiFi HTTP -> Volumio :3000
```

## Firmware scaffolds

- [`firmware/elecrow-crowpanel-1.28/`](firmware/elecrow-crowpanel-1.28/)
- [`firmware/waveshare-knob-touch-lcd-1.8/`](firmware/waveshare-knob-touch-lcd-1.8/)
