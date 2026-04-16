# Research: Python Utilities for Home Assistant Connect ZBT-2

## What Is the ZBT-2?

The **Home Assistant Connect ZBT-2** (by Nabu Casa) is a USB-C Zigbee/Thread coordinator built around:

- **Wireless SoC:** Silicon Labs EFR32MG24 (Arm Cortex-M33 @ 78 MHz) — handles Zigbee 3.0 or Thread/Matter (not simultaneously)
- **USB bridge:** ESP32-S3 acting as USB-to-serial only (Wi-Fi/BT on ESP32 are disabled)
- **Baud rate:** 460,800 bps (faster than the predecessor ZBT-1/SkyConnect)
- **Protocol firmware:** Open-source EZSP (EmberZNet Serial Protocol) or RCP (Radio Co-Processor) for OpenThread

The stick is **not a standalone device** — it requires a host running Home Assistant (or a custom Python stack) to be useful. Think of it as an antenna/coordinator that your software drives.

---

## Programming Model

### The Closest Analogy: DNS / Service Discovery Broker

The ZBT-2 is most analogous to a **network coordinator** (like a wireless access point combined with a service registry):

| Concept | Zigbee equivalent |
|---|---|
| MAC address | IEEE 64-bit device address (EUI64) |
| IP address | 16-bit NWK short address (assigned by coordinator) |
| mDNS / DNS-SD service record | Zigbee Device Profile (ZDP) — `Simple_Desc_req` |
| Service/port | Cluster ID (e.g. `0x0006` = On/Off, `0x0402` = Temperature) |
| Read a DNS record | `read_attributes` on a cluster |
| Send a UDP packet | `cluster.command(...)` |
| DHCP server | Coordinator (ZBT-2) assigns short addresses |
| Network join / leave | Zigbee permit-join mechanism |

Compared to other paradigms:
- **Not like Samba** — there is no browseable filesystem or human-readable share name; identity is numeric.
- **Not like raw DNS** — discovery is event-driven (devices announce themselves on join) rather than query-driven.
- **Closest to BLE GATT** — you enumerate *services (clusters)* on a device and read/write *characteristics (attributes)*.

### Two Access Layers

```
 ┌─────────────────────────────────────────────────────────┐
 │  Tier 1 – Home Assistant REST / WebSocket API           │
 │  (high-level; requires running HA instance)             │
 │  Entity model: light.living_room, sensor.temp_kitchen   │
 └─────────────────────────────────────────────────────────┘
                          │
 ┌─────────────────────────────────────────────────────────┐
 │  Tier 2 – zigpy / bellows (direct radio control)        │
 │  (low-level; Python talks to ZBT-2 over /dev/ttyUSB0)   │
 │  Device model: EUI64 → endpoint → cluster → attribute   │
 └─────────────────────────────────────────────────────────┘
                          │
              Silicon Labs EZSP protocol (serial)
                          │
              EFR32MG24 on ZBT-2 dongle
```

---

## Available Python Libraries

### Tier 1 — Home Assistant API wrappers (requires running HA)

| Library | PyPI | Description |
|---|---|---|
| `homeassistant-api` | `pip install homeassistant-api` | Sync/async client wrapping REST + WebSocket |
| `python-homeassistant-client` | community | Thin REST wrapper |
| `hass-client` | `pip install hass-client` | Async WebSocket-first client |
| `websockets` | `pip install websockets` | Raw WebSocket; use directly against HA WS API |
| `requests` | `pip install requests` | Plain HTTP for HA REST API |

### Tier 2 — Direct Zigbee radio control (no HA required)

| Library | PyPI | Description |
|---|---|---|
| `zigpy` | `pip install zigpy` | Pure-Python Zigbee stack; coordinator-agnostic core |
| `bellows` | `pip install bellows` | zigpy radio driver for **Silicon Labs EZSP** (the ZBT-2 chip) |
| `zigpy-znp` | `pip install zigpy-znp` | zigpy driver for TI Z-Stack (CC2652 etc.) |
| `zigpy-deconz` | `pip install zigpy-deconz` | zigpy driver for Dresden Elektronik ConBee/RaspBee |
| `zigpy2mqtt` | — | Bridge zigpy to MQTT |

### Tier 3 — Thread / Matter (future / alternative firmware)

| Library | Notes |
|---|---|
| `python-matter-server` | Nabu Casa's own project; runs a Matter controller daemon |
| `chip-repl` (CHIP SDK) | Low-level Matter commissioning; complex setup |
| OpenThread Python bindings | For Thread border-router use cases |

---

## Pseudocode for Basic Tasks

The examples below are written at **both** tiers so you can choose the right entry point.

### 1. List All Devices

#### Via Home Assistant REST API (Tier 1)

```python
import requests

HA_URL = "http://homeassistant.local:8123"
TOKEN  = "ey..."   # Long-Lived Access Token from HA profile

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}

# Returns list of all entity state objects
states = requests.get(f"{HA_URL}/api/states", headers=headers).json()
for entity in states:
    print(entity["entity_id"], "->", entity["state"])

# Or use the device registry (groups entities by physical device)
import websockets, json, asyncio

async def list_devices():
    async with websockets.connect(f"ws://homeassistant.local:8123/api/websocket") as ws:
        await ws.recv()                                          # auth_required
        await ws.send(json.dumps({"type": "auth", "access_token": TOKEN}))
        await ws.recv()                                          # auth_ok

        await ws.send(json.dumps({"id": 1, "type": "config/device_registry/list"}))
        resp = json.loads(await ws.recv())
        for dev in resp["result"]:
            print(dev["id"], dev.get("name_by_user") or dev.get("name"), dev["manufacturer"])

asyncio.run(list_devices())
```

#### Via zigpy/bellows (Tier 2 — direct radio)

```python
import asyncio
import bellows.zigbee.application

DEVICE_PATH = "/dev/ttyUSB0"   # serial port the ZBT-2 is on

async def list_devices():
    app = await bellows.zigbee.application.ControllerApplication.new(
        config={"device": {"path": DEVICE_PATH}},
        auto_form=True,
    )
    for ieee, device in app.devices.items():
        print(f"IEEE: {ieee}  NWK: {device.nwk:#06x}  Model: {device.model}")
    await app.shutdown()

asyncio.run(list_devices())
```

---

### 2. Query a Device for State

#### Via HA REST API (Tier 1)

```python
import requests

entity_id = "sensor.kitchen_temperature"   # discovered entity

response = requests.get(
    f"{HA_URL}/api/states/{entity_id}",
    headers=headers
)
state = response.json()

print(f"State  : {state['state']}")
print(f"Unit   : {state['attributes'].get('unit_of_measurement')}")
print(f"Updated: {state['last_updated']}")

# Example output:
# State  : 21.4
# Unit   : °C
# Updated: 2026-04-16T04:00:00+00:00
```

#### Via zigpy (Tier 2 — read a Zigbee cluster attribute directly)

```python
import asyncio
import bellows.zigbee.application
from zigpy.zcl.clusters.measurement import TemperatureMeasurement

TARGET_IEEE = "00:11:22:33:44:55:66:77"   # EUI64 of device

async def read_temperature():
    app = await bellows.zigbee.application.ControllerApplication.new(
        config={"device": {"path": "/dev/ttyUSB0"}}, auto_form=True
    )
    device   = app.get_device(ieee=TARGET_IEEE)
    endpoint = device.endpoints[1]         # main endpoint is usually 1
    cluster  = endpoint.in_clusters[TemperatureMeasurement.cluster_id]  # 0x0402

    # read_attributes returns {attr_name: (status, value)}
    result = await cluster.read_attributes(["measured_value"])
    raw = result["measured_value"][1]      # value in units of 0.01 °C
    print(f"Temperature: {raw / 100:.1f} °C")

    await app.shutdown()

asyncio.run(read_temperature())
```

---

### 3. Control a Hypothetical Discovered Device

Scenario: we discovered a Zigbee smart plug named `switch.workshop_plug` in HA, or we know its EUI64 and it has an On/Off cluster (`0x0006`).

#### Via HA REST API — call a service (Tier 1)

```python
import requests, json

def control_switch(entity_id: str, turn_on: bool):
    service = "turn_on" if turn_on else "turn_off"
    resp = requests.post(
        f"{HA_URL}/api/services/switch/{service}",
        headers=headers,
        data=json.dumps({"entity_id": entity_id}),
    )
    print(resp.status_code, resp.json())

control_switch("switch.workshop_plug", turn_on=True)

# For a dimmable light with brightness:
requests.post(
    f"{HA_URL}/api/services/light/turn_on",
    headers=headers,
    data=json.dumps({
        "entity_id": "light.living_room",
        "brightness_pct": 50,
        "color_temp": 4000,  # Kelvin
    }),
)
```

#### Via HA WebSocket — call a service (Tier 1)

```python
import asyncio, websockets, json

async def toggle_device(entity_id: str):
    async with websockets.connect("ws://homeassistant.local:8123/api/websocket") as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": TOKEN}))
        await ws.recv()

        await ws.send(json.dumps({
            "id": 10,
            "type": "call_service",
            "domain": "homeassistant",
            "service": "toggle",
            "service_data": {"entity_id": entity_id},
        }))
        result = json.loads(await ws.recv())
        print("Success:", result["success"])

asyncio.run(toggle_device("switch.workshop_plug"))
```

#### Via zigpy — send a Zigbee command (Tier 2)

```python
import asyncio
import bellows.zigbee.application
from zigpy.zcl.clusters.general import OnOff

TARGET_IEEE = "00:11:22:33:44:55:66:77"

async def turn_on_device():
    app = await bellows.zigbee.application.ControllerApplication.new(
        config={"device": {"path": "/dev/ttyUSB0"}}, auto_form=True
    )
    device  = app.get_device(ieee=TARGET_IEEE)
    cluster = device.endpoints[1].in_clusters[OnOff.cluster_id]   # 0x0006

    # OnOff cluster commands: 0=off, 1=on, 2=toggle
    await cluster.command(OnOff.Command.on)
    print("Sent ON command")

    await app.shutdown()

asyncio.run(turn_on_device())
```

---

### 4. Bonus: Subscribe to Real-Time State Changes (Tier 1)

```python
import asyncio, websockets, json

async def watch_changes():
    async with websockets.connect("ws://homeassistant.local:8123/api/websocket") as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": TOKEN}))
        await ws.recv()                                         # auth_ok

        await ws.send(json.dumps({
            "id": 20,
            "type": "subscribe_events",
            "event_type": "state_changed",
        }))
        await ws.recv()                                         # subscription confirmed

        while True:
            msg = json.loads(await ws.recv())
            event = msg.get("event", {})
            data  = event.get("data", {})
            eid   = data.get("entity_id", "")
            new_s = (data.get("new_state") or {}).get("state")
            print(f"{eid}: {new_s}")

asyncio.run(watch_changes())
```

---

## Key Observations & Recommendations

1. **Start with Tier 1 (HA API)** unless you have a specific reason to drop to the radio layer. The HA entity model handles the hard parts (device pairing, firmware updates, cluster mapping) and exposes a clean service/state interface.

2. **Use `bellows` (not `zigpy-znp`)** for the ZBT-2. The EFR32MG24 speaks EZSP (EmberZNet Serial Protocol), which is the Silicon Labs proprietary serial framing that `bellows` implements.

3. **Pick your concurrency model early.** Both zigpy and the HA WebSocket API are async-first (`asyncio`). The REST API is sync-friendly via `requests` but misses push events.

4. **Thread vs Zigbee**: The ZBT-2 can run either Thread (for Matter devices) or Zigbee — not both. If targeting Matter appliances, the `python-matter-server` path is the right choice instead of `zigpy`.

5. **Authentication**: HA long-lived access tokens are the practical choice. Generate one under `Profile → Security → Long-Lived Access Tokens` in the HA UI.

---

## Further Reading

- [Home Assistant REST API](https://developers.home-assistant.io/docs/api/rest/)
- [Home Assistant WebSocket API](https://developers.home-assistant.io/docs/api/websocket/)
- [zigpy repository](https://github.com/zigpy/zigpy)
- [bellows (EZSP) repository](https://github.com/zigpy/bellows)
- [Nabu Casa ZBT-2 support page](https://support.nabucasa.com/hc/en-us/articles/31313065259421-About-Home-Assistant-Connect-ZBT-2)
- [Zigbee Cluster Library specification](https://zigbeealliance.org/solution/zigbee-cluster-library/)
- [python-matter-server](https://github.com/home-assistant-libs/python-matter-server)
