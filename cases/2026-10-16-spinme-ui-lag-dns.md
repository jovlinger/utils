# CASE: Spinme glass waits on Volumio hostname lookup

- Date: 2026-10-16
- Hosts / gear: Waveshare ESP32-S3-Knob-Touch-LCD-1.8, firmware `branch:4a26154c-device-ui`, Volumio host `miniDSP-SHD.local`
- Status: remediated

## 1. Symptoms

Volume turns take seconds to show on the glass. Starting playback on Volumio from somewhere else took about 10 seconds to show. During a turn there is no number change until well after the knob has stopped.

## 2. Evidences

- `service_deferred` drew the frame only after `refresh_player` and `flush_volume`.
- `volumio_get` built `http://miniDSP-SHD.local:3000/...` and called `http.end()` after every GET, so the next call resolved the name again.
- Arduino-esp32 2.0.17 `WiFiGenericClass::hostByName` waits on `WIFI_DNS_IDLE_BIT` for up to 16s and on `WIFI_DNS_DONE_BIT` for up to 15s. That wait is outside `HTTPClient::setTimeout` and outside the 5s default connect timeout.
- `HTTPClient::setTimeout(2500)` only bounds the read. `setConnectTimeout` was left at 5000.
- The follow poll interval is 2s. A 10s delay is one lookup, not five polls.
- Anti-evidence: the double buffer is still on (`panel_buffers_begin` allocates two PSRAM frames and `panel_present` pushes dirty spans). `kUiQuietMs` is 100ms. Neither one accounts for multi-second lag. A full-frame SPI push at 40 MHz is tens of milliseconds.

## 3. Analysis

The knob ISR still counts during the stall. The main loop does not paint until Volumio HTTP returns, and each of those calls starts with a hostname lookup that can sit in lwIP for many seconds. The optimistic volume is already in memory the whole time. The glass is late because it is scheduled behind that lookup, not because the framebuffer rewrite got heavier.

An external play/pause shows up on the same path: the 2s poll cannot update the frame until `getState` returns, and `getState` cannot start until the name resolves.

## 4. Remediation

Cache the resolved address and pass a literal IP into `HTTPClient::begin`, so later calls skip `hostByName`. Drop the cache only when `begin` fails or `GET` returns a negative code. Draw the dirty frame before `refresh_player` and `flush_volume`, then draw again if those calls change the state. A turn that is already in `gUnsent` is on the glass before the network round trip. The 100ms quiet window stays, so a spin is still not stalled on the panel.

## Discussion

The first lookup, during `connect_wifi`, can still block once. A connect timeout of 1s is there so a stale cached address fails quickly and the next call resolves again. The 2s player poll is unchanged; after the address is cached, an external transport change waits for that poll plus one HTTP GET, not for DNS.
