# Thermo onboard Pico2W

Rust target for the Pico2W thermostat controller.

In-progress HAT work: [`hat/BOOKMARK.md`](hat/BOOKMARK.md).

Agent bring-up (USB serial first), deploy env, and firmware make targets:
[`AGENTS.md`](AGENTS.md).

The firmware binary `ledw_status` runs the fused onboard controller loop:

- `pico2w_aht20_ir` hardware profile.
- AHT20 on software I2C (SDA GP28, SCL GP27) with fallback to 1.0 C / 1.0 %
  when the sensor is missing and `SENSOR_BOOT_REQUIRED=0`.
- Signed HTTP `POST /zone/<zone>/sensors` to the DMZ long-poll endpoint.
- Command freshness comparison matching the existing DMZ protocol.
- Midea IR transmit on GP10 for strictly newer returned commands.
- Status LED events: one pulse when a DMZ poll starts, two pulses before
  IR send, three pulses during startup/config, and four pulses for error paths.

The physical status LED is the Pico2W onboard LED labeled `LEDW`, driven by the
CYW43 WiFi chip. Because LEDW is single-color, the firmware renders semantic
status as blink patterns: 1 pulse for poll-start happy path, 2 for IR send,
3 for startup/config, and 4 for errors.

A successful long-poll response with no command, or with an old command, is still
green/3 pulses. Blue/2 pulses is only for a newer command that the firmware is
about to send over IR.

The firmware exposes `GET /healthz` and `GET /logs` on the same default onboard
app port as Pi Zero, `5000`, after WiFi and DHCP are ready. `GET /healthz`
returns the Pi Zero health contract shape with Pico-specific details under a
`pico` object. There is no Pico filesystem log. The in-memory firmware log keeps
64 entries and returns up to 32 entries in newest-first order.

## Office Midea IR Reference

The Office capture matches the Coolix / Midea24-style byte-complement protocol,
not IRremoteESP8266's native `IRMideaAC` checksum protocol. Useful references:

- IRremoteESP8266 `ir_Coolix`: byte plus inverse encoding, 4.4 ms header, 560 us
  mark, 1.6 ms / 560 us spaces, and about a 5.2 ms packet gap:
  <https://github.com/crankyoldgit/IRremoteESP8266/blob/master/src/ir_Coolix.cpp>
- IRremoteESP8266 Midea24 note: a 48-bit NEC-like form with alternate inverted
  bytes, carrying 24 bits of real data:
  <https://github.com/crankyoldgit/IRremoteESP8266/blob/master/src/ir_Midea.cpp>
- Older standalone Midea encoder with the same `B2 xx yy` plus complement
  packet shape:
  <https://github.com/sheinz/esp-midea-ir/blob/master/midea-ir.c>

Current Office evidence: each command sends the complement-paired state packet
twice, then a third 48-bit `D5 ...` packet after the same roughly 5.2 ms gap.
For example, power-on captured as `B2 4D 9F 60 60 9F`,
`B2 4D 9F 60 60 9F`, then `D5 28 20 01 00 1E`.
