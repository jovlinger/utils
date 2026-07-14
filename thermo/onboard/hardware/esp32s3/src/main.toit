// Minimal office onboard debug server.
// No encryption, no third-party packages: stdlib net + gpio only.
// Serves /healthz and /logs on TCP port 5000 for direct LAN access.

import encoding.json
import gpio
import net
import net.tcp
import rmt

ZONE-NAME ::= "office"
BACKEND ::= "esp32s3"
HARDWARE-PROFILE ::= "esp32s3_aht20_ir"
IR-PROTOCOL ::= "midea24_coolix"
IR-TX-GPIO ::= 17
IR-RX-GPIO ::= 6
DEBUG-PULLUP-GPIO ::= 4
DEBUG-PULLDOWN-GPIO ::= 5
HTTP-PORT ::= 5000
LOG-CAPACITY ::= 32

boot-us_ := Time.monotonic-us

class LogRing:
  lines_/List := []

  add line/string -> none:
    stamp := (Time.monotonic-us - boot-us_) / 1000
    entry := "$(%d stamp)ms $line"
    lines_.add entry
    print entry
    while lines_.size > LOG-CAPACITY:
      lines_.remove lines_.first

  newest-first -> List:
    out := []
    i := lines_.size - 1
    while i >= 0:
      out.add lines_[i]
      i--
    return out

read-request socket/tcp.Socket -> string?:
  buf := #[]
  // Read until we have the request line + headers end, or give up.
  while buf.size < 2048:
    chunk := socket.in.read
    if not chunk: break
    buf += chunk
    text := buf.to-string-non-throwing
    if text.contains "\r\n\r\n" or text.contains "\n\n":
      return text
    if text.contains "\n":
      // Have at least the request line.
      return text
  if buf.size == 0: return null
  return buf.to-string-non-throwing

request-path text/string -> string:
  // "GET /healthz HTTP/1.1\r\n..."
  first-nl := text.index-of "\n"
  line := first-nl >= 0 ? (text[..first-nl].trim --right "\r") : text
  parts := line.split " "
  if parts.size < 2: return "/"
  path := parts[1]
  q := path.index-of "?"
  return q >= 0 ? path[..q] : path

send-json socket/tcp.Socket status/int body-bytes/ByteArray -> none:
  status-text := status == 200 ? "OK" : "Error"
  headers := "HTTP/1.0 $status $status-text\r\n"
      + "Content-Type: application/json\r\n"
      + "Content-Length: $body-bytes.size\r\n"
      + "Connection: close\r\n"
      + "\r\n"
  socket.out.write headers
  socket.out.write body-bytes
  socket.out.close

send-ir-ping logs/LogRing -> none:
  // Short ~38 kHz burst on IR TX for direct bench testing (not a full Midea frame).
  pin := gpio.Pin IR-TX-GPIO
  channel := rmt.Out pin --resolution=1_000_000
  // ~13 us high / 13 us low ~= 38 kHz; 80 edges ~= 1 ms burst.
  pulse := rmt.Signals 80
  for i := 0; i < 80; i++:
    pulse.set i --level=(i % 2 == 0 ? 1 : 0) --period=13
  channel.write pulse --done-level=0
  channel.close
  pin.close
  logs.add "ir ping gpio$IR-TX-GPIO 38kHz ~1ms"

handle socket/tcp.Socket logs/LogRing pin-up/gpio.Pin pin-down/gpio.Pin -> none:
  try:
    text := read-request socket
    if not text:
      logs.add "empty request"
      return
    path := request-path text
    logs.add "req $path"
    if path == "/healthz":
      uptime-s := (Time.monotonic-us - boot-us_) / 1_000_000
      body := json.encode {
        "ok": true,
        "service": "onboard-app",
        "hardware_backend": BACKEND,
        "deployment": {
          "zone_name": ZONE-NAME,
          "hardware_profile": HARDWARE-PROFILE,
          "send_behavior": "ir_heatpump",
          "report_behavior": "sensor_readings",
          "sensor_driver": "aht20",
          "ir_transport": "esp32s3_rmt",
          "ir_device": "gpio$IR-TX-GPIO",
          "ir_protocol": IR-PROTOCOL,
          "backend": BACKEND,
          "status_led_driver": "log_only",
        },
        "network": {
          "local_ip": "192.168.88.73",
          "onboard_url": "http://192.168.88.73:$HTTP-PORT",
        },
        "esp32s3": {
          "uptime_seconds": uptime-s,
          "wifi_ready": true,
          "debug_pullup_gpio": DEBUG-PULLUP-GPIO,
          "debug_pulldown_gpio": DEBUG-PULLDOWN-GPIO,
          "debug_pullup_level": pin-up.get,
          "debug_pulldown_level": pin-down.get,
          "ir_tx_gpio": IR-TX-GPIO,
          "ir_rx_gpio": IR-RX-GPIO,
        },
        "log_buffer": {
          "capacity": LOG-CAPACITY,
          "returned": logs.newest-first.size,
          "lines": logs.newest-first,
        },
      }
      send-json socket 200 body
    else if path == "/logs":
      body := json.encode {
        "lines": logs.newest-first,
        "path": null,
      }
      send-json socket 200 body
    else if path == "/gpio":
      body := json.encode {
        "pullup_gpio": DEBUG-PULLUP-GPIO,
        "pulldown_gpio": DEBUG-PULLDOWN-GPIO,
        "pullup_level": pin-up.get,
        "pulldown_level": pin-down.get,
      }
      send-json socket 200 body
    else if path == "/ir/ping":
      send-ir-ping logs
      body := json.encode {
        "ok": true,
        "action": "ir_ping",
        "gpio": IR-TX-GPIO,
        "note": "short 38kHz burst; not a full midea frame",
      }
      send-json socket 200 body
    else:
      body := json.encode {"ok": false, "error": "not_found", "path": path}
      send-json socket 404 body
  finally:
    socket.close

main:
  logs := LogRing
  logs.add "thermo-esp32s3 debug boot"
  pin-up := gpio.Pin.in DEBUG-PULLUP-GPIO --pull-up
  pin-down := gpio.Pin.in DEBUG-PULLDOWN-GPIO --pull-down
  logs.add "gpio pullup=$DEBUG-PULLUP-GPIO pulldown=$DEBUG-PULLDOWN-GPIO"

  network := net.open
  server := network.tcp-listen HTTP-PORT
  logs.add "listen :$HTTP-PORT"
  print "esp32s3-office listening http://0.0.0.0:$HTTP-PORT/healthz|/logs|/gpio"

  while true:
    socket := server.accept
    if not socket:
      continue
    handle socket logs pin-up pin-down
