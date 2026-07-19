// Office onboard debug server: local /healthz /logs /gpio /ir/ping /dmz/ping.
// Ed25519 via custom-envelope C service (auth.toit). Midea IR via ir.toit.
// NTP via pkg-ntp so X-Zone-Timestamp is a real wall clock.

import encoding.json
import esp32 show adjust-real-time-clock
import gpio
import net
import net.tcp
import ntp

import .auth
import .ir as irlib
import .secrets as secrets

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
// Believable wall clock for Ed25519 zone timestamps (DMZ rejects skew).
MIN-CREDIBLE-EPOCH ::= 1_700_000_000
NTP-ATTEMPTS ::= 5

boot-us_ := Time.monotonic-us
auth-ed25519-ready_/bool := false
ntp-ok_/bool := false
dmz-signer_/Ed25519Signer? := null

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
  while buf.size < 2048:
    chunk := socket.in.read
    if not chunk: break
    buf += chunk
    text := buf.to-string-non-throwing
    if text.contains "\r\n\r\n" or text.contains "\n\n":
      return text
    if text.contains "\n":
      return text
  if buf.size == 0: return null
  return buf.to-string-non-throwing

request-path text/string -> string:
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

/**
Send Midea power-on FAN F5 (hi) via RMT on IR TX.
Returns list of hex frame strings transmitted.
*/
send-ir-fan-hi logs/LogRing -> List:
  command := irlib.HeatpumpCommand --power --mode="FAN" --fan="F5" --temp-c=24
  frames := irlib.transmit-midea IR-TX-GPIO command
  hexes := []
  frames.do: | frame/ByteArray |
    hexes.add (irlib.hex-frame frame)
  logs.add "ir midea power=on mode=FAN fan=F5 frames=$(hexes.size)"
  return hexes

slice-prefix text/string max/int -> string:
  if text.size <= max: return text
  return text[..max]

read-http-response socket/tcp.Socket -> string:
  buf := #[]
  while chunk := socket.in.read:
    buf += chunk
    if buf.size > 65536:
      // Keep memory bounded: this endpoint is for debug, not bulk transfer.
      break
  return buf.to-string-non-throwing

parse-status-code response/string -> int:
  first-nl := response.index-of "\n"
  line := first-nl >= 0 ? (response[..first-nl].trim --right "\r") : response
  parts := line.split " "
  if parts.size < 2: return 0
  // status token is e.g. "200"
  token := parts[1]
  out := 0
  token.do: | ch/int |
    if ch < '0' or ch > '9': return 0
    out = out * 10 + (ch - '0')
  return out

response-body response/string -> string:
  p := response.index-of "\r\n\r\n"
  if p >= 0: return response[p + 4..]
  q := response.index-of "\n\n"
  if q >= 0: return response[q + 2..]
  return response

build-dmz-body pin-up/gpio.Pin pin-down/gpio.Pin -> ByteArray:
  // Keep the debug body small -- full log rings blow RAM during long-poll.
  body := json.encode {
    "sensors": {
      "temp_centigrade": 1.0,
      "humid_percent": 1.0,
    },
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
    "debug_gpio": {
      "pullup_gpio": DEBUG-PULLUP-GPIO,
      "pulldown_gpio": DEBUG-PULLDOWN-GPIO,
      "pullup_level": pin-up.get,
      "pulldown_level": pin-down.get,
    },
  }
  return body

/**
One signed POST to DMZ sensors. Caps wait so the debug HTTP server is not wedged
by the long-poll hold; timeout after send usually means DMZ accepted the signature.
*/
dmz-ping-once logs/LogRing pin-up/gpio.Pin pin-down/gpio.Pin network/net.Interface --max-wait/Duration=(Duration --s=45) -> Map:
  if not dmz-signer_:
    throw "dmz signer unavailable"
  body := build-dmz-body pin-up pin-down
  epoch := Time.now.s-since-epoch
  headers := dmz-signer_.sign-headers "POST" secrets.DMZ-PATH body ZONE-NAME epoch
  signature := headers["signature_b64"]
  timestamp := headers["timestamp"]
  zone-name := headers["zone_name"]

  // Cap connect + write + response so a hung DNS/TCP path cannot wedge :5000.
  response/string := ""
  exception := catch:
    with-timeout max-wait:
      socket := network.tcp-connect secrets.DMZ-HOST secrets.DMZ-PORT
      try:
        request-head := "POST $(secrets.DMZ-PATH) HTTP/1.1\r\n"
            + "Host: $(secrets.DMZ-HOST):$(secrets.DMZ-PORT)\r\n"
            + "Content-Type: application/json\r\n"
            + "Content-Length: $body.size\r\n"
            + "Connection: close\r\n"
            + "X-Zone-Signature: $signature\r\n"
            + "X-Zone-Timestamp: $timestamp\r\n"
            + "X-Zone-Name: $zone-name\r\n"
            + "\r\n"
        socket.out.write request-head
        socket.out.write body
        response = read-http-response socket
      finally:
        socket.close
  if exception:
    logs.add "dmz ping wait timeout=$(max-wait) epoch=$epoch err=$exception"
    return {
      "ok": false,
      "status": 0,
      "timed_out": true,
      "timestamp_sent": "$epoch",
      "dmz_host": secrets.DMZ-HOST,
      "dmz_path": secrets.DMZ-PATH,
      "body_excerpt": "timeout during DMZ connect/send/wait (signed headers ready)",
    }

  status := parse-status-code response
  body-text := response-body response
  excerpt := slice-prefix body-text 400
  logs.add "dmz ping status=$status body=$(slice-prefix excerpt 120)"
  if status == 401 and epoch < MIN-CREDIBLE-EPOCH:
    logs.add "dmz ping likely clock-skew: epoch=$epoch (need NTP)"
  return {
    "ok": status == 200,
    "status": status,
    "timed_out": false,
    "timestamp_sent": "$epoch",
    "dmz_host": secrets.DMZ-HOST,
    "dmz_path": secrets.DMZ-PATH,
    "body_excerpt": excerpt,
  }

handle socket/tcp.Socket logs/LogRing pin-up/gpio.Pin pin-down/gpio.Pin network/net.Interface -> none:
  exception := catch --trace:
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
          "epoch_seconds": Time.now.s-since-epoch,
          "wifi_ready": true,
          "ntp_ok": ntp-ok_,
          "auth_ed25519_ready": auth-ed25519-ready_,
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
      hexes := send-ir-fan-hi logs
      body := json.encode {
        "ok": true,
        "action": "ir_midea_fan_hi",
        "gpio": IR-TX-GPIO,
        "protocol": IR-PROTOCOL,
        "command": {
          "power": true,
          "mode": "FAN",
          "fan": "F5",
          "temp_c": 24,
        },
        "frames_hex": hexes,
      }
      send-json socket 200 body
    else if path == "/dmz/ping":
      result := dmz-ping-once logs pin-up pin-down network
      send-json socket 200 (json.encode result)
    else:
      body := json.encode {"ok": false, "error": "not_found", "path": path}
      send-json socket 404 body
  if exception:
    logs.add "handler error: $exception"
    catch: socket.close
  else:
    socket.close

/**
Sync wall clock via NTP when epoch is not yet credible.
Returns true when Time.now is past MIN-CREDIBLE-EPOCH.
*/
sync-ntp logs/LogRing --network/net.Interface -> bool:
  epoch := Time.now.s-since-epoch
  if epoch >= MIN-CREDIBLE-EPOCH:
    logs.add "ntp already credible epoch=$epoch"
    return true
  for attempt := 1; attempt <= NTP-ATTEMPTS; attempt++:
    logs.add "ntp sync attempt $attempt/$NTP-ATTEMPTS"
    result := ntp.synchronize --network=network
    if result:
      adjust-real-time-clock result.adjustment
      epoch = Time.now.s-since-epoch
      logs.add "ntp adjusted epoch=$epoch accuracy=$(result.accuracy)"
      if epoch >= MIN-CREDIBLE-EPOCH:
        return true
    else:
      logs.add "ntp sync failed attempt=$attempt"
    sleep (Duration --s=2)
  logs.add "ntp give up epoch=$(Time.now.s-since-epoch)"
  return false

main:
  logs := LogRing
  logs.add "thermo-esp32s3 debug boot"

  // Encryption library (Monocypher Ed25519 via custom envelope).
  dmz-signer_ = Ed25519Signer secrets.ZONE-SEED
  auth-ed25519-ready_ = true
  logs.add "auth ed25519 ready"

  pin-up := gpio.Pin.in DEBUG-PULLUP-GPIO --pull-up
  pin-down := gpio.Pin.in DEBUG-PULLDOWN-GPIO --pull-down
  logs.add "gpio pullup=$DEBUG-PULLUP-GPIO pulldown=$DEBUG-PULLDOWN-GPIO"

  network := net.open
  ntp-ok_ = sync-ntp logs --network=network

  server := network.tcp-listen HTTP-PORT
  logs.add "listen :$HTTP-PORT"
  print "esp32s3-office listening :$HTTP-PORT healthz|logs|gpio|ir/ping|dmz/ping"

  while true:
    socket := server.accept
    if not socket:
      continue
    task::
      handle socket logs pin-up pin-down network
