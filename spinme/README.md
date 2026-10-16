# spinme

On-device music controller: follow now-playing, knob volume, and zone pick
for Sonos S1 and Volumio, on the Waveshare ESP32-S3-Knob-Touch-LCD-1.8
(S3 half, device-end Type-C).

| Doc | What it is |
|-----|------------|
| [`DESIGN.md`](DESIGN.md) | UI core and Volumio worker |
| [`HILEVEL.md`](HILEVEL.md) | Zones, follow, and volume regimes |
| [`hardware/waveshare-knob-touch-lcd-1.8/`](hardware/waveshare-knob-touch-lcd-1.8/) | Board |
| [`firmware/waveshare-knob-touch-lcd-1.8/`](firmware/waveshare-knob-touch-lcd-1.8/) | Firmware, `make install`, `make screenshot` |

Agent notes: [`AGENTS.md`](AGENTS.md).

Volumio on this LAN is `miniDSP-SHD.local` port 3000.
`GET /api/v1/getState` and `GET /api/v1/commands/?cmd=volume|toggle|play|pause`.
Docs: https://developers.volumio.com/api/rest-api
