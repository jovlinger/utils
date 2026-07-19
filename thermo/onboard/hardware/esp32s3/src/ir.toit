// Midea24 / Coolix IR frame builder + RMT TX (port of pico2w/src/ir.rs).

import gpio
import rmt

MIDEA-START-PULSE-US ::= 4500
MIDEA-START-SPACE-US ::= 4500
MIDEA-PULSE-US ::= 560
MIDEA-SPACE-ZERO-US ::= 560
MIDEA-SPACE-ONE-US ::= 1680
MIDEA-GAP-US ::= 5200
CARRIER-HZ ::= 38_000
RESOLUTION-HZ ::= 1_000_000

class HeatpumpCommand:
  power/bool
  mode/string  // AUTO COOL DRY HEAT FAN
  fan/string   // F1..F5 AUTO SILENT
  temp-c/int

  constructor --power/bool --mode/string --fan/string --temp-c/int=24:
    this.power = power
    this.mode = mode
    this.fan = fan
    this.temp-c = temp-c

temp-nibble temp-c/int -> int:
  t := temp-c
  if t < 17: t = 17
  if t > 30: t = 30
  if t == 17: return 0x0
  if t == 18: return 0x1
  if t == 19: return 0x3
  if t == 20: return 0x2
  if t == 21: return 0x6
  if t == 22: return 0x7
  if t == 23: return 0x5
  if t == 24: return 0x4
  if t == 25: return 0xC
  if t == 26: return 0xD
  if t == 27: return 0x9
  if t == 28: return 0x8
  if t == 29: return 0xA
  return 0xB

fan-nibble fan/string -> int:
  if fan == "F3": return 0x5
  if fan == "F4" or fan == "F5": return 0x3
  if fan == "AUTO": return 0xB
  // F1 F2 SILENT
  return 0x9

mode-nibble mode/string -> int:
  if mode == "AUTO": return 0x8
  if mode == "COOL": return 0x0
  if mode == "HEAT": return 0xC
  // DRY or FAN
  return 0x4

/**
Return 3 payload bytes (before complement pairing).
*/
state-bytes command/HeatpumpCommand -> ByteArray:
  fan-n := fan-nibble command.fan
  state-n := command.power ? 0xF : 0xB
  mode-n := mode-nibble command.mode
  temp-n := temp-nibble command.temp-c
  if not command.power:
    fan-n = 0x7
    temp-n = 0xE
  return #[
    0xB2,
    (fan-n << 4) | state-n,
    (temp-n << 4) | mode-n,
  ]

complement-frame data/ByteArray -> ByteArray:
  return #[
    data[0],
    data[0] ^ 0xFF,
    data[1],
    data[1] ^ 0xFF,
    data[2],
    data[2] ^ 0xFF,
  ]

secondary-frame data/ByteArray -> ByteArray:
  fan-code := 0x28
  if (data[1] >> 4) == 0x1: fan-code = 0x65
  else if (data[1] >> 4) == 0x3: fan-code = 0x64
  else if (data[1] >> 4) == 0x5: fan-code = 0x3C
  else if (data[1] >> 4) == 0x9: fan-code = 0x28
  else if (data[1] >> 4) == 0xB: fan-code = 0x66
  temp-flag := ((data[2] >> 4) == 0x6) ? 0x20 : 0x00
  frame := #[0xD5, fan-code, temp-flag, 0x01, 0x00, 0x00]
  frame[5] = (frame[0] + frame[1] + frame[2] + frame[3] + frame[4]) & 0xFF
  return frame

/**
List of 6-byte frames to transmit (state x2 + D5 when power on).
*/
classic-frames command/HeatpumpCommand -> List:
  data := state-bytes command
  state := complement-frame data
  if command.power:
    return [state, state, secondary-frame data]
  return [state, state]

hex-frame frame/ByteArray -> string:
  out := ""
  frame.do: | b |
    if out.size > 0: out += " "
    out += "$(%02X b)"
  return out

count-signals-for-frames frames/List -> int:
  // per frame: start mark+space + 6*8*(mark+space) + final mark+gap
  per := 2 + (6 * 8 * 2) + 2
  return per * frames.size

append-mark-space signals/rmt.Signals index/int mark-us/int space-us/int -> int:
  signals.set index --level=1 --period=mark-us
  signals.set index + 1 --level=0 --period=space-us
  return index + 2

append-byte signals/rmt.Signals index/int byte/int -> int:
  bit := 7
  while bit >= 0:
    space := ((byte >> bit) & 1) == 1 ? MIDEA-SPACE-ONE-US : MIDEA-SPACE-ZERO-US
    index = append-mark-space signals index MIDEA-PULSE-US space
    bit--
  return index

build-signals frames/List -> rmt.Signals:
  total := count-signals-for-frames frames
  signals := rmt.Signals total
  idx := 0
  frames.do: | frame/ByteArray |
    idx = append-mark-space signals idx MIDEA-START-PULSE-US MIDEA-START-SPACE-US
    frame.do: | b |
      idx = append-byte signals idx b
    idx = append-mark-space signals idx MIDEA-PULSE-US MIDEA-GAP-US
  if idx != total: throw "signal count mismatch $idx vs $total"
  return signals

/**
Transmit Midea classic frames on $tx-gpio using RMT + 38 kHz carrier.
*/
transmit-midea tx-gpio/int command/HeatpumpCommand -> List:
  frames := classic-frames command
  signals := build-signals frames
  pin := gpio.Pin tx-gpio
  // Enough memory for ~300 signals (2 bytes each).
  channel := rmt.Out pin --resolution=RESOLUTION-HZ --memory-blocks=4
  channel.apply-carrier CARRIER-HZ --duty-factor=0.5
  try:
    channel.write signals --done-level=0
  finally:
    channel.disable-carrier
    channel.close
    pin.close
  return frames
