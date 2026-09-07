# ESP32 as Volumio Remote -- Investigation & Plan

**Goal:** On-device music controller (follow now-playing + knob volume + zone
pick) for **Sonos S1** and **Volumio**, on Waveshare hardware.

**UX / stack map:** [`HILEVEL.md`](HILEVEL.md).

Python / Cursor agent notes: [`AGENTS.md`](AGENTS.md) (venv conventions also in
root [`AGENTS.md`](../AGENTS.md)).

## Hardware

**RATIFIED 2026-09-07: Waveshare ESP32-S3-Knob-Touch-LCD-1.8** (S3 half;
device-end Type-C). Elecrow remains documented sibling only.

| Board | Role | Directory |
|-------|------|-----------|
| Waveshare ESP32-S3-Knob-Touch-LCD-1.8 | **Active target** | [`hardware/waveshare-knob-touch-lcd-1.8/`](hardware/waveshare-knob-touch-lcd-1.8/) |
| Elecrow CrowPanel 1.28" (DHE38128D) | Sibling / reference | [`hardware/elecrow-crowpanel-1.28/`](hardware/elecrow-crowpanel-1.28/) |

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
| **Hardware choice** | **Waveshare** (S3); Elecrow sibling docs kept |
| **HILEVEL UX** | [`HILEVEL.md`](HILEVEL.md) -- zones as pairs, follow, volume regimes, LVGL |
| **Board probes** | Both boards documented under `hardware/` |
| **Volumio API** | `miniDSP-SHD.local` getState OK (2026-09-07) |
| **Firmware** | Scaffolds under `firmware/`; controller impl next |

**Next steps:** Config schema; Sonos SSDP/SOAP + Volumio drivers; LVGL follow +
zone list on Waveshare.

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
