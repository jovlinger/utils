# Raspberry Pi Zero 2 W Wi-Fi connectivity loss — diagnosis and fix

## Clickbait

A Raspberry Pi Zero 2 W running Raspbian GNU/Linux 12 (Bookworm), kernel 6.1.0,
with the BCM43430/1 Wi-Fi chip and the `brcmfmac` driver was intermittently losing all
network connectivity and becoming completely unreachable by SSH and ping. No watchdog was
running, so every incident required a physical power cycle. The device sits on a network
with multiple access points sharing the same SSID on different channels. The root cause
was **Wi-Fi power save mode enabled by default in the `brcmfmac` driver**, which caused
the chip to sleep between beacon intervals and silently drop incoming ARP requests. This
made the device invisible to the rest of the network even though it held a valid DHCP
lease and believed itself connected. A secondary known issue — the BCM43430 firmware
autonomously roaming between access points every ~60 seconds — was a contributing factor.
Both problems are fixed with three small configuration changes, no kernel or firmware
upgrade required.

---

## Environment

| Component | Version |
|-----------|---------|
| Hardware | Raspberry Pi Zero 2 W Rev 1.0 |
| SoC / Wi-Fi chip | BCM2835 / BCM43430/1 |
| Wi-Fi driver | `brcmfmac` |
| Wi-Fi firmware | BCM43430/1 `wl0` version 7.45.96.s1 (Jun 14 2023) |
| OS | Raspbian GNU/Linux 12 (Bookworm) |
| Kernel | `6.1.0-rpi7-rpi-v7` (Raspbian 1:6.1.63-1+rpt1, 2023-11-24) |
| `wpa_supplicant` | v2.10 (package `2:2.10-12`) |
| `iw` | 5.19-1 |
| `watchdog` daemon | 5.16-2~rpt2 |
| Network management | standalone `wpa_supplicant` + `dhclient` (no NetworkManager on wlan0) |
| Docker | 28.5.2 |

---

## Symptoms

- The device ran normally for hours, generating outbound HTTP traffic every 5 seconds to a
  remote server. Traffic stopped abruptly and never resumed.
- The device was **completely unreachable**: no response to `ping`, SSH gave
  `no route to host` or timed out.
- The device had **not rebooted**: uptime on recovery was consistent with the time since
  last power cycle.
- The device came back **spontaneously** once, ran for ~4 hours, then died again.
- After a physical power cycle the device returned to normal immediately.
- Once back, `ifconfig` / `ip addr` showed a **valid DHCP address** on `wlan0`. The
  device believed itself connected.
- Signal strength on the AP was healthy (-51 to -53 dBm). No hardware faults.

---

## What we checked and ruled out

### Thermal overheating — ruled out

`vcgencmd measure_temp` read **38.6 °C** at the time of recovery. The soft temperature
limit on this chip is ~70 °C. The device runs a low-frequency polling loop; sustained
CPU load is minimal.

`vcgencmd get_throttled` returned **`0x0`** — no under-voltage, no thermal throttling,
no frequency capping had occurred since the last boot. If overheating or PSU brown-out
had been the cause, bits 16–19 of that register would be non-zero (they are sticky
since-boot flags).

### PSU under-voltage — ruled out for this incident

The `throttled=0x0` result above also rules out the PSU as the cause here. This is worth
re-checking after longer uptime; bits 16 (`under_voltage_occurred`) and 18
(`throttled_occurred`) accumulate over time and survive until the register is read or the
board reboots.

### brcmfmac firmware hard crash — not observed, but a real risk

The `brcmfmac` driver on BCM43430 is known to crash hard (`brcmf_fw_crashed: Firmware has
halted or crashed`) or lock up the SDIO bus (`mmc1: Controller never released inhibit bit(s)`)
under specific conditions, requiring a hard reboot to recover. `dmesg` on recovery showed
none of these messages in this incident. However, the 60-second roaming cycle described
below is a documented trigger path for this crash, so mitigating roaming also reduces this
risk.

### Multi-AP roaming crash — partially contributing

The network has several access points with the **same SSID** on different channels. The
`brcmfmac` driver does autonomous firmware-driven roaming between them, and this is a
documented bug trigger (see [raspberrypi/firmware #2019](https://github.com/raspberrypi/firmware/issues/2019)).
The device was connected to BSSID `1a:e8:29:91:fe:2c` (2437 MHz / channel 6) at recovery.
We cannot confirm or deny whether a roaming event preceded the lockup, but disabling
firmware roaming is a standard mitigation and was applied.

---

## Root cause

**Wi-Fi power save mode was enabled by default.**

When `brcmfmac` initialises, the kernel logs:

```
brcmfmac: brcmf_cfg80211_set_power_mgmt: power save enabled
```

In power save mode the Wi-Fi chip periodically enters a low-power sleep state between
AP beacon intervals. While asleep it does not process incoming frames, including **ARP
requests**. From the perspective of every other device on the network, the Pi stopped
responding to ARP and therefore became unreachable at layer 2 — even though it held a
valid IP and could still initiate outbound connections during the brief wake windows.

This perfectly explains all observed symptoms:

- Valid DHCP address retained ✓
- Initiated outbound traffic until it stopped ✓  
- Completely invisible to ping and SSH from the network ✓
- Spontaneous recovery (the chip occasionally woke and responded) ✓
- Power cycle restores everything ✓

The immediate manual fix confirmed the diagnosis:

```
sudo /usr/sbin/iw wlan0 set power_save off
```

Laptop ping succeeded within one second of running that command.

---

## Anti-symptoms: things that did NOT help diagnose it faster

- `ip addr` and `ifconfig` show a valid IP regardless. Do not use them to conclude
  the device is "connected" — they reflect the kernel's view, not the AP's.
- `ping google.com` from the Pi itself may succeed even while the Pi is invisible
  from the outside, because outbound ARP is different from answering inbound ARP requests.
- The `brcmfmac: power save enabled` kernel log line appears on every healthy boot too.
  You have to query the live state with `iw wlan0 get power_save` to know if it is
  currently on or off.

---

## Dangerous dead end: live module reload over SSH

While investigating, we attempted to reload the driver live:

```
sudo modprobe -r brcmfmac && sudo modprobe brcmfmac
```

**Do not do this over SSH.** When `brcmfmac` is unloaded, `wpa_supplicant` loses its
interface and calls `nl80211: deinit ifname=wlan0`. When the module comes back,
`NetworkManager` (if running) re-discovers the hardware, but `wpa_supplicant` has
already torn itself down. The result is: the kernel has a Wi-Fi device, nobody is
managing it, and SSH never returns. The journal showed:

```
wpa_supplicant[544]: nl80211: deinit ifname=wlan0 disabled_11b_rates=0
wpa_supplicant[544]: ioctl[SIOCSIWENCODEEXT]: Invalid argument
```

A physical power cycle was required both times this was attempted. The fix (disabling
power save) does not require a module reload; it takes effect immediately with a single
`iw` command.

---

## Diagnostic commands (copy-paste)

Run these immediately after a recovery before anything resets:

```bash
# Throttle/UV flags — sticky since boot; 0x0 = clean
vcgencmd get_throttled

# SoC temperature
vcgencmd measure_temp

# Current Wi-Fi power save state
/usr/sbin/iw wlan0 get power_save

# brcmfmac module parameters (roamoff should be Y or 1 after fix)
cat /sys/module/brcmfmac/parameters/roamoff

# brcmfmac/MMC/voltage events in dmesg
dmesg -T | grep -E 'brcmf|mmc1|voltage|throttl|thermal|oom|Under'

# Current Wi-Fi link info
/usr/sbin/iw dev wlan0 link

# ARP table — if default gateway is missing, layer 2 is broken
ip neigh show
```

---

## Fix: three configuration changes

All three survive reboots. Apply them in order.

### 1. Disable Wi-Fi power save — the actual fix

Create `/etc/systemd/system/wifi-powersave-off.service`:

```ini
[Unit]
Description=Disable WiFi power save on wlan0
After=wpa_supplicant.service
Wants=wpa_supplicant.service

[Service]
Type=oneshot
ExecStart=/usr/sbin/iw wlan0 set power_save off
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

Enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable wifi-powersave-off
sudo systemctl start wifi-powersave-off
```

Verify:

```bash
/usr/sbin/iw wlan0 get power_save
# Expected: Power save: off
```

**Note on NetworkManager:** If your system uses NetworkManager to manage `wlan0`, you can
alternatively create `/etc/NetworkManager/conf.d/wifi-powersave-off.conf`:

```ini
[connection]
wifi.powersave = 2
```

However, on stock Raspbian Bookworm, `wlan0` is managed by standalone `wpa_supplicant` +
`dhclient`, not by NetworkManager. The NM conf file will silently have no effect in that
configuration. Use the systemd service above instead.

### 2. Disable brcmfmac firmware roaming — reduces crash risk

Create `/etc/modprobe.d/brcmfmac.conf`:

```
options brcmfmac roamoff=1 feature_disable=0x82000
```

`roamoff=1` stops the firmware from autonomously switching APs.  
`feature_disable=0x82000` disables SAE (WPA3-adjacent) and SWSUP (firmware-offloaded
authentication), both of which are known brcmfmac crash triggers on this chip.

This takes effect on the next (clean) reboot. Verify afterwards:

```bash
cat /sys/module/brcmfmac/parameters/roamoff
# Expected: Y  (or 1)
```

### 3. Enable the BCM2835 hardware watchdog — recovery safety net

Without a watchdog, any future firmware crash or hard hang requires a physical power cycle.
With it, the board automatically resets after ~15 seconds.

Add to `/boot/firmware/config.txt` (Raspbian Bookworm path; older Raspbian uses
`/boot/config.txt`):

```
dtoverlay=watchdog
```

Install and configure the watchdog daemon:

```bash
sudo apt install -y watchdog

sudo tee /etc/watchdog.conf <<'EOF'
watchdog-device  = /dev/watchdog
max-load-1       = 24
watchdog-timeout = 15
EOF

sudo systemctl enable watchdog
sudo systemctl start watchdog
```

The `dtoverlay=watchdog` line requires a reboot to activate the hardware device; the
daemon will start petting `/dev/watchdog` from the moment it runs. Verify after reboot:

```bash
ls /dev/watchdog              # device must exist
systemctl is-active watchdog  # must be: active
```

---

## State after applying fixes

```
$ vcgencmd get_throttled
throttled=0x0

$ /usr/sbin/iw wlan0 get power_save
Power save: off

$ cat /sys/module/brcmfmac/parameters/roamoff
Y

$ systemctl is-active wifi-powersave-off watchdog wpa_supplicant
active
active
active

$ ls /dev/watchdog
/dev/watchdog
```

---

## References

- [raspberrypi/firmware #2019](https://github.com/raspberrypi/firmware/issues/2019) — 60-second BCM43430 disassociation cycle (open as of 2026-03)
- [raspberrypi/firmware #1973](https://github.com/raspberrypi/firmware/issues/1973) — Zero 2 W WiFi/SSH unusable
- [raspberrypi/firmware #1723](https://github.com/raspberrypi/firmware/issues/1723) — BCM43430/1 WiFi issues; `over_voltage` workaround
- [raspberrypi/linux #3849](https://github.com/raspberrypi/linux/issues/3849) — `brcmf_fw_crashed`
- [raspberrypi/linux #5770](https://github.com/raspberrypi/linux/issues/5770) — SDIO `mmc1` inhibit bit lockup
- [blog.wijman.net](https://blog.wijman.net/make-raspberry-pi-zero-2w-wifi-work-correctly/) — `brcmfmac.conf` fix
- [diode.io](https://diode.io/blog/running-forever-with-the-raspberry-pi-hardware-watchdog) — hardware watchdog setup
