# MikroTik RB2011UiAS-2HnD Router Configuration for DMZ

RouterOS v6.49.19. This config exposes the Pi 1B to the internet on port 80 while keeping LAN and DHCP unchanged.

## Topology

```
                    RB2011UiAS-2HnD
    Internet -------- ether1 (WAN)
                          |
        +-----------------+-----------------+
        |                                   |
   ether2-4 (bridge-lan)              ether5 (DMZ)
        |                                   |
   LAN devices + DHCP                  Pi 1B (static IP)
```

- **ether1**: WAN (public IP from ISP)
- **ether2–4**: LAN bridge, DHCP server for internal devices
- **ether5**: DMZ, Pi 1B only (static IP)

**DHCP**: Yes. The router keeps providing DHCP on the LAN bridge. The Pi uses a static IP on the DMZ interface.

## Interface Setup

**WebFig**: IP → Addresses; Interfaces → Bridge; Interfaces → Bridge → Ports

**Check current config:**
```routeros
/ip address print
/interface bridge print
/interface bridge port print
```

**Expected**: WAN (ether1) has an address or DHCP client; LAN bridge exists with ports; bridge has 192.168.88.1 or similar. **Bad sign**: ether1 has no IP (no internet); bridge-lan missing or empty; wrong subnet on LAN.

Adjust interface names if your layout differs. Typical RB2011: ether1 = WAN, ether2–5 = switch/ports.

```routeros
# WAN (ether1) - get IP via DHCP from ISP, or set static
/ip address
add address=0.0.0.0/0 interface=ether1 comment="WAN - set via DHCP client or static"

# LAN bridge (ether2, ether3, ether4)
/interface bridge
add name=bridge-lan
/interface bridge port
add bridge=bridge-lan interface=ether2
add bridge=bridge-lan interface=ether3
add bridge=bridge-lan interface=ether4

/ip address
add address=192.168.88.1/24 interface=bridge-lan comment="LAN"

# DMZ (ether5) - Pi 1B
/ip address
add address=192.168.77.1/24 interface=ether5 comment="DMZ"
```

## DHCP on LAN (unchanged)

**WebFig**: IP → DHCP Server; IP → DHCP Server → Networks; IP → Pool

**Check current config:**
```routeros
/ip pool print
/ip dhcp-server print
/ip dhcp-server network print
```

**Expected**: A pool (e.g. `dhcp-lan` or `default`) with a range; a DHCP server bound to your LAN interface/bridge; a network entry with gateway matching your LAN IP. **Bad sign**: No DHCP server, or server bound to wrong interface (e.g. ether1/WAN).

```routeros
/ip pool
add name=dhcp-lan ranges=192.168.88.10-192.168.88.254

/ip dhcp-server network
add address=192.168.88.0/24 gateway=192.168.88.1 dns-server=192.168.88.1

/ip dhcp-server
add name=dhcp-lan interface=bridge-lan address-pool=dhcp-lan disabled=no
```

## Port Forward: 80 → Pi

**WebFig**: IP → Firewall → NAT

**Check current config:**
```routeros
/ip firewall nat print
```

**Expected**: A `dstnat` rule for TCP port 80 with `to-addresses` and `to-ports`; a `srcnat` masquerade rule for outbound. **Bad sign**: No dstnat for 80; `to-addresses` points to wrong subnet or unreachable host; masquerade missing (LAN won't reach internet).

```routeros
/ip firewall nat
add chain=dstnat action=dst-nat protocol=tcp dst-port=80 in-interface=ether1 \
    to-addresses=192.168.77.10 to-ports=80 comment="DMZ Pi HTTP"

# Masquerade for outbound (if not already present)
add chain=srcnat action=masquerade out-interface=ether1
```

Replace `192.168.77.10` with the Pi’s actual DMZ IP.

## Firewall (recommended)

**WebFig**: IP → Firewall → Filter Rules

**Check current config:**
```routeros
/ip firewall filter print
```

**Expected**: `forward` chain rules: accept established/related; accept dstnat; drop DMZ→LAN; accept LAN outbound. **Bad sign**: No accept for `connection-nat-state=dstnat` (port forward will fail); DMZ→LAN not blocked (Pi could reach internal hosts); overly restrictive rules dropping LAN traffic.

Allow forwarded traffic for the NAT rule and restrict DMZ→LAN:

```routeros
/ip firewall filter
# Allow established/related
add chain=forward action=accept connection-state=established,related comment="established"

# Allow dst-nat (port forward) traffic
add chain=forward action=accept connection-nat-state=dstnat comment="port forward"

# Drop DMZ → LAN (Pi cannot reach internal network)
add chain=forward action=drop in-interface=ether5 out-interface=bridge-lan \
    comment="block DMZ to LAN"

# Default forward policy (adjust as needed)
add chain=forward action=accept comment="allow LAN outbound" in-interface=bridge-lan
add chain=forward action=drop comment="default drop"
```

## Optional: DHCP on DMZ

If you want the Pi to get its IP via DHCP instead of static:

```routeros
/ip pool
add name=dhcp-dmz ranges=192.168.77.10-192.168.77.20

/ip dhcp-server network
add address=192.168.77.0/24 gateway=192.168.77.1 dns-server=192.168.88.1

/ip dhcp-server
add name=dhcp-dmz interface=ether5 address-pool=dhcp-dmz disabled=no
```

Then use a DHCP lease or static DHCP binding so the port-forward target IP is stable.

## Summary

| Item | Value |
|------|-------|
| LAN subnet | 192.168.88.0/24 |
| LAN gateway | 192.168.88.1 |
| LAN DHCP | Yes (bridge-lan) |
| DMZ subnet | 192.168.77.0/24 |
| DMZ gateway | 192.168.77.1 |
| Pi IP | 192.168.77.10 (static) |
| Port forward | WAN:80 → 192.168.77.10:80 |

The Pi listens on 8080; its iptables redirect 80→8080 applies to traffic arriving at the Pi. The router forwards WAN port 80 to the Pi’s port 80, so the Pi must listen on 80 or perform the redirect. Our setup uses iptables on the Pi to redirect 80→8080, so the router forwards to the Pi’s port 80 and the Pi redirects to 8080 internally.
