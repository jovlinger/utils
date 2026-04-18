# Home DMZ: Pi 1B outside LAN NAT (RouterBOARD)

This document fixes the **network intent** for the thermo DMZ Pi: how it sits relative to the home router and the public internet. RouterOS (or other firmware) **export scripts** may live here later; this file is the **design reference** so we do not re-derive it each time.

## RouterOS target

- **Version:** **6.49.19** (long-term). Any **`.rsc`** snippets for this project should use **RouterOS v6** CLI (`/ip firewall filter`, `/ip firewall nat`, `chain=forward`, etc.), not v7-only paths or syntax.
- Re-check before paste/import if the router is ever upgraded to **v7** (firewall and some defaults differ).

## What “DMZ” means here

- The Pi 1B is **not** on the same IPv4 subnet as trusted LAN hosts (workstations, onboard Pis, etc.). That **limits blast radius**: a compromise on the DMZ host does not grant direct L2/L3 neighbor access to the inside LAN.
- The Pi is placed **outside the NAT that serves the LAN**. From an internal machine, the DMZ Pi is **not** “another host on my LAN”; it is reached like **any other host on the internet** (public hostname/IP, same port semantics as from outside). This matches the classic home/SOHO pattern (e.g. OpenWRT “DMZ” / isolated segment): **one routed segment for insiders behind masquerade, another for the exposed server without sharing that inside subnet.**

## Traffic we want

- **Inbound from the internet:** TCP **5000** on the Pi → Flask **`app.py`** (default listen port when **`PORT`** is unset in the chroot environment; see **`app.py`**).
- **DNS:** **DuckDNS** hostname **`jovlinger.duckdns.org`** tracks the home connection’s **changing public IP** (update the DuckDNS token/panel when the ISP address changes). Users and services use **`http://jovlinger.duckdns.org:5000`** (or HTTPS later if terminated on the Pi or elsewhere; see **`HTTPS-TRUSTED-CERT.md`**).
- The home router (here: **RouterBOARD**, DMZ attachment on **ether9** in the current plan) must **forward** or **allow forward** from WAN to the Pi’s address on the DMZ segment for **tcp/5000** (and any other ports we explicitly decide later).

## Pi addressing

- The Pi’s **`eth0`** is configured from **`install/network.conf`** on the boot FAT (`ADDR/CIDR` + gateway). That address must live on the **DMZ subnet** the router assigns or routes—not on **`192.168.88.0/24`** (or whatever the LAN uses).
- **Rescue / docs examples** that mention **`192.168.88.x`** are for **recovery on a lab cable** or a MikroTik default LAN; they are **not** the production DMZ subnet by definition.

## Related repo docs

- **`README.md`** (parent): Pi image boot chain and **`network.conf`** editing.
- **`Pi1b.md`** (under **`thermo/consumed/`**): SSH and hardening—**do not** expose maintenance SSH on the WAN/DMZ side; use internal access, serial, or a deliberate jump path.
- **Onboard** ([`thermo/onboard/install/README.md`](../../onboard/install/README.md)): **`DMZ_URL`** must point at this service; from the LAN that may be **`http://jovlinger.duckdns.org:5000`**, a **hairpin NAT** rule, or another path—whatever makes the onboard host reach the DMZ as if it were “the internet” for routing purposes.

## What this document does *not* specify yet

- Concrete **RouterOS** firewall lines, NAT exception list, or **hairpin** rules (implementation checklist belongs in a follow-up export or section).
- **IPv6**, **TLS** on 5000 vs reverse proxy, or extra ports.

When those are decided, extend this file or add a small **`*.rsc`** next to it and reference it here.
