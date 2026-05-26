# Onboard Forensics (2026-03-19)

Host investigated via `ssh pizero.local` after reboot due to report:
- no mDNS from host
- no HTTP from `onboard/app.py`

## SSH Success

Successfully connected and executed commands remotely.

```bash
ssh pizero.local 'hostname; date; uptime'
```

Observed:
- hostname: `pizero`
- uptime at collection time: `up 8:45`

## Network and mDNS State

Commands:

```bash
ssh pizero.local 'ip -4 addr show wlan0; ip route'
ssh pizero.local 'systemctl is-active avahi-daemon; systemctl status avahi-daemon --no-pager -n 20'
```

Observed:
- `wlan0` had IPv4 address `192.168.88.54/24`
- default route via `192.168.88.1`
- `avahi-daemon` was `active (running)` and registered hostname `pizero.local`
- avahi logs showed join/register on `wlan0` and `docker0`

## Onboard Service and Container State

Commands:

```bash
ssh pizero.local 'systemctl is-enabled onboard; systemctl is-active onboard; systemctl status onboard --no-pager -n 80'
ssh pizero.local 'docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"'
```

Observed:
- `onboard` systemd unit reported `inactive`
- container `thermo-onboard` reported `Up 9 hours`

## HTTP Reachability Checks (on host)

Commands:

```bash
ssh pizero.local 'ss -ltnp'
ssh pizero.local 'curl -sv --max-time 5 http://127.0.0.1:8080/'
ssh pizero.local 'curl -sv --max-time 5 http://127.0.0.1:5000/'
```

Observed:
- host listening sockets included `0.0.0.0:8080` and `0.0.0.0:5000`
- `http://127.0.0.1:8080/` returned `HTTP/1.0 200 OK` with Thermo HTML page
- `http://127.0.0.1:5000/` returned `HTTP/1.1 404 NOT FOUND` (Werkzeug), indicating Flask/Werkzeug was reachable but `/` route absent for that service
- `docker inspect thermo-onboard --format "{{json .HostConfig.PortBindings}}"` returned `{}` (no explicit published container ports in `HostConfig`)

## Logs Collected

Long-lived copies of multi-source pulls belong under **`thermo/debuglogs/`** (gitignored, dated filenames, retention header — see `thermo/debuglogs/README.md`).

Commands:

```bash
ssh pizero.local 'docker logs --tail 200 thermo-onboard'
ssh pizero.local 'journalctl -u onboard -u avahi-daemon -b --no-pager -n 200'
ssh pizero.local 'journalctl -b -p err --no-pager -n 200'
```

Observed:
- container logs included:
  - `starting app`
  - `* Serving Flask app 'app'`
- no obvious onboard/avahi crash in the sampled logs
- sampled boot errors were Bluetooth-plugin related (not clearly tied to onboard HTTP/mDNS symptoms)

## Immediate Forensic Takeaways

- At collection time, `pizero.local` DNS/mDNS identity was healthy from the Pi side (`avahi-daemon active`).
- Onboard HTTP was reachable locally on the Pi (`127.0.0.1:8080` returned UI).
- There is a state mismatch between `systemd onboard` (`inactive`) and a running `thermo-onboard` container (`Up`), suggesting container lifecycle may currently be decoupled from the `onboard` unit.
