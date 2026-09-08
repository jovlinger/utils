# Music controller -- high-level UX and stack map

status: living -- maps user experience to concrete firmware/actions

status: living -- **NOT LOCKED** (2026-09-07). Expect edits; WorkItems are preliminary.

**Parallel implementation tracks** (parent `todo:4a26154c`):

| Track | Todo | Scope |
|-------|------|-------|
| Device UI | `todo:f8a5c5fc` (`branch:4a26154c-device-ui`) | Waveshare WiFi / LVGL / encoder / touch |
| Audio control | `todo:c475b79b` (`branch:4a26154c-audio-control`) | Python zone library + Flask harness; port later |

Ratchet: small slices, lock learnings with tests/docs, then next level. On-device
integration of both tracks stays on the parent after merge.

**Hardware (RATIFIED 2026-09-07):** Waveshare ESP32-S3-Knob-Touch-LCD-1.8
(ESP32-S3 half; device-end Type-C). Round 360x360 touch LCD + rotary encoder
**without** a hardware push-click. Touch replaces "click" for discrete actions.
Elecrow CrowPanel (push-dial) is sibling research only -- see
`hardware/elecrow-crowpanel-1.28/`.

**Targets:** Sonos S1 (LAN UPnP) and Volumio (LAN HTTP). No cloud Sonos Control
API for MVP.

---

## 1. Core model: zones as system/endpoint pairs

**Open Q (user proposal, adopted for MVP):** flatten ecosystems into one list of
**zones**, where each zone is a pair:

```text
zone := (system, endpoint)
```

| Field | Meaning | Examples |
|-------|---------|----------|
| `system` | Protocol / ecosystem | `sonos_s1`, `volumio` |
| `endpoint` | Controllable unit id on that system | Sonos room UUID or IP+UDN; Volumio host (`miniDSP-SHD.local`) |
| `display_name` | UI label | `Kitchen`, `Office`, `SHD` |
| `volume_regime` | How volume commands are interpreted | see section 5 |

**Pair == zone.** The controller never asks "which ecosystem?" as a separate
step in normal use: the user picks a **zone** from one list. Ecosystem is an
implementation detail of that zone's drivers.

Discovery may populate candidate endpoints; the hand-edited config decides which
pairs are real zones and how their volume works. Autodiscovered-but-unconfigured
endpoints can appear as "unconfigured" for later hand-edit, or be ignored until
listed in config (MVP: **config is the allowlist**).

---

## 2. UX states and flows

### 2.1 Idle / follow (default)

The controller **passively follows** the **active zone**:

- transport: playing / paused / stopped (and buffering if cheap to obtain)
- now playing: title, artist, album when the system provides them
- volume: current level **only if** the zone's regime exposes a readable volume

Screen shows: zone name, transport glyph, track line(s), volume affordance
(arc or bar) when applicable.

No continuous user input required. Poll or subscribe (see section 4) at a
modest rate; backoff when idle.

### 2.2 Volume (knob rotation)

**Rotate** the encoder while not in a modal picker:

- Map detents to volume up/down (or absolute steps) according to the active
  zone's `volume_regime`.
- Debounce / coalesce rapid ticks into fewer network calls.
- Update the on-screen volume widget optimistically; reconcile on next state
  poll.

If the regime is `noop` or `fixed_external`, rotation is ignored or shows a
brief "volume not on this zone" hint (touch-dismiss).

### 2.3 Select active zone (on-device UI)

Waveshare has **no dial click**. Zone change is **touch-driven**:

1. Tap zone name (or a dedicated "Zones" control) -> open zone list (LVGL list /
   roller).
2. Tap a zone -> set active; return to follow view; start following that zone.
3. Optional: swipe / secondary button for cancel.

Encoder while the list is open: scroll the list (highlight); **tap** confirms
(because there is no click). Alternative MVP: list is touch-only; encoder always
volume when follow view is showing.

### 2.4 Out of scope for MVP

- Config UI on device
- Grouping / stereo pair editing
- Source browsing / queue edit
- Spotify / cloud accounts
- Elecrow-specific click gestures (may map later: click = open zone list)

---

## 3. Action map (UX -> firmware)

| User / system event | Firmware action | Stack primitive |
|---------------------|-----------------|-----------------|
| Boot | Load config from flash (SPIFFS/LittleFS); WiFi STA; run discovery refresh | NVS/FS + WiFi + mDNS/SSDP |
| Discovery refresh | Scan Sonos + Volumio; merge with config allowlist into zone table | SSDP + mDNS + HTTP |
| Enter follow view | Subscribe or poll active zone transport + metadata + volume | Sonos SOAP / Volumio REST |
| Knob rotate (follow) | Apply volume delta via zone driver | RenderingControl or Volumio `volume` |
| Tap zone chrome | Push LVGL zone-list screen | LVGL |
| Tap zone row | `active_zone = id`; pop UI; restart follow | app state |
| OTA config upload | Write new config file; reload zone table | ArduinoOTA / HTTPUpdate + FS |
| OTA firmware | Dual-slot update (factory image already has `app0`/`app1`) | ArduinoOTA or esp_ota |

---

## 4. Discovery and control frameworks

### 4.1 Sonos S1

**Discovery:** SSDP M-SEARCH UDP multicast to `239.255.255.250:1900` with
`ST: urn:schemas-upnp-org:device:ZonePlayer:1`. Optionally follow with
`ZoneGroupTopology.GetZoneGroupState` on port **1400** for room names and group
coordinators.

**Control / state:** HTTP POST SOAP to `http://<ip>:1400/...`:

| Need | Service | Typical actions |
|------|---------|-----------------|
| Play/pause/skip | `AVTransport` | `Play`, `Pause`, `GetTransportInfo`, `GetPositionInfo` |
| Volume/mute | `RenderingControl` | `GetVolume`, `SetVolume`, `GetMute`, `SetMute` |
| Topology | `ZoneGroupTopology` | `GetZoneGroupState` |

**Eventing (preferred when stable):** UPnP GENA `SUBSCRIBE` on AVTransport /
RenderingControl for push updates; fallback to poll every 1-2 s.

**Libraries / references (ESP32):**

- Arduino: [tmittet/sonos](https://github.com/tmittet/sonos) /
  [javos65/Sonos-ESP32](https://github.com/javos65/sonos) (UPnP scan + SOAP)
- Protocol notes: [sonos.svrooij.io](https://sonos.svrooij.io/sonos-communication),
  [sonoscli spec](https://sonoscli.sh/spec.html) (topology + SOAP shapes)
- Host-side Python SoCo is **reference only** (not on-device)

Transport commands must target the **group coordinator** when the endpoint is
in a group; volume may still be per-member depending on bonding -- encode in
`volume_regime` / config notes.

### 4.2 Volumio

**Discovery:** mDNS for hosts advertising Volumio (and/or configured hostnames
like `miniDSP-SHD.local`). Existing spinme host probe: REST on port **3000**.

**Control / state:** HTTP GET (Volumio REST):

| Need | Endpoint |
|------|----------|
| State / track | `/api/v1/getState` |
| Volume | `/api/v1/commands/?cmd=volume&volume=plus\|minus\|<0-100>` |
| Transport | `/api/v1/commands/?cmd=play\|pause\|toggle\|...` |

**Libraries:** ESP32 `HTTPClient` or `esp_http_client`; optional Arduino
Json (`ArduinoJson`) for `getState`. No mandatory third-party Volumio library.
Docs: [Volumio REST API](https://developers.volumio.com/api/rest-api).

### 4.3 Unified zone driver interface (firmware-shaped)

```text
ZoneDriver {
  discover() -> candidates[]
  get_transport(endpoint) -> playing|paused|stopped
  get_now_playing(endpoint) -> title, artist, album?
  get_volume(endpoint) -> 0..100 | unavailable
  set_volume_delta(endpoint, delta) | set_volume_abs(...)
}
```

`sonos_s1` and `volumio` implement this. The UX layer only talks to drivers via
the active zone's pair.

---

## 5. Per-zone volume regimes (heterogeneous house)

Systems are not uniform. Config selects a **regime** per zone:

| Regime | Behavior | Example |
|--------|----------|---------|
| `native` | Read/write volume on this endpoint | Sonos Kitchen; Volumio SHD playing from NAS |
| `fixed_feed` | Do **not** change this endpoint's volume; rotation is no-op or routes elsewhere | Office Sonos locked feeding Volumio/S/PDIF path |
| `delegate` | Rotation adjusts a **different** endpoint (named in config) | Office: UI follows Sonos metadata but volume hits Volumio or a DSP |
| `noop` | Follow-only zone; no volume | Rare / debug |

MVP: regimes implemented as a small switch in the Volumio/Sonos drivers; no
plugin system.

---

## 6. Config file (hand-edited, OTA upload)

No on-device config UI for MVP. Ship a file on LittleFS/SPIFFS, replace via OTA
file push or firmware data partition update.

Illustrative shape (exact schema TBD in a later `CONFIG.md`):

```json
{
  "wifi": { "ssid": "...", "pass": "..." },
  "active_zone": "kitchen",
  "zones": [
    {
      "id": "kitchen",
      "display_name": "Kitchen",
      "system": "sonos_s1",
      "endpoint": { "room": "Kitchen" },
      "volume_regime": "native"
    },
    {
      "id": "office",
      "display_name": "Office",
      "system": "sonos_s1",
      "endpoint": { "room": "Office" },
      "volume_regime": "delegate",
      "volume_target": { "system": "volumio", "host": "miniDSP-SHD.local" }
    },
    {
      "id": "shd",
      "display_name": "SHD",
      "system": "volumio",
      "endpoint": { "host": "miniDSP-SHD.local" },
      "volume_regime": "native"
    }
  ]
}
```

Discovery helps the human author fill `endpoint` fields; the device does not
require rediscovery to operate if config already has IPs/hosts (mDNS refresh
still useful).

---

## 7. On-device UI framework

| Layer | Choice | Role |
|-------|--------|------|
| App language | C++ Arduino (PlatformIO) on ESP32-S3 | Matches Waveshare factory / demos |
| Widgets | **LVGL** | Follow view, zone list, volume arc, touch hit-targets |
| Panel | ST77916 via ESP32_Display_Panel / esp_lcd (as in factory) or LovyanGFX if simpler | 360x360 square FB in round bezel |
| Touch | CST816S -> LVGL pointer indev | Zone select, open list |
| Encoder | GPIO ISR/poll -> volume delta or list scroll | No push switch on this hardware |
| FS / OTA | LittleFS + ArduinoOTA (slots already in factory partition table) | Config + firmware |

**Drawing current state:** LVGL labels for zone + track; LVGL arc/bar for
volume; LVGL image or symbol for play/pause. Partial buffers preferred (360x360
+ PSRAM; factory already stresses LVGL alloc).

---

## 8. End-to-end narratives

### Discover available zones

On boot or "refresh", the Sonos driver SSDP-scans ZonePlayers and reads
topology for room names; the Volumio driver mDNS-resolves configured hosts (and
any `_http` / Volumio advertisements we choose to trust). Results are matched to
config `zones[]`. Only configured pairs become selectable zones.

### Display current zone activity

For `active_zone`, the matching driver fetches transport + metadata (Sonos
`GetTransportInfo` / `GetPositionInfo` or GENA events; Volumio `getState`).
LVGL follow screen binds those fields. Poll/subscribe loop keeps the view fresh
while idle.

### Dial rotated

Encoder delta -> active zone's `volume_regime` -> `native`/`delegate` driver
`set_volume_*` (Sonos `RenderingControl.SetVolume` or Volumio volume command).
UI arc updates.

### Select zone

Touch opens LVGL list of config zones; touch selects; follow rebinds to that
pair's driver.

---

## 9. Open questions (user / later tickets)

1. Exact config schema and OTA file path/tooling (`pio` upload vs HTTP multipart).
2. Whether unconfigured discoveries appear in UI or stay log-only.
3. Sonos group volume vs member volume defaults for bonded rooms.
4. Encoder-while-list-open: scroll+tap vs touch-only list.
5. Minimum poll interval vs GENA subscription complexity on ESP32.
6. Whether `fixed_feed` zones still show a volume number from the delegate target.

---

## 10. Doc / code pointers in this tree

| Path | Content |
|------|---------|
| `hardware/waveshare-knob-touch-lcd-1.8/` | Board identity, USB orientations, OTA partitions, display |
| `firmware/waveshare-knob-touch-lcd-1.8/` | PlatformIO scaffold |
| `docs/docs-volumio-probe-2026-09-07.md` | Host REST probe (`miniDSP-SHD.local`) |
| `hardware/elecrow-crowpanel-1.28/` | Sibling board (not MVP target) |
