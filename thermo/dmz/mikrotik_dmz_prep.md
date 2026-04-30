# MikroTik RB2011 — DMZ prep on ether10 (RouterOS 6)

**Intent:** Put the thermo DMZ Pi on a separate L3 segment on **ether10**, per [`install/ROUTERBOARD-DMZ.md`](install/ROUTERBOARD-DMZ.md) (TCP **5000**).

Snippets use **[RFC 5737](https://datatracker.ietf.org/doc/html/rfc5737)** TEST-NET addresses (**`192.0.2.0/24`**). Replace **`WAN_IF`**, **`LAN_BR`**, **`DMZ_ETHER`**, **`GW_ON_DMZ`**, **`DMZ_NET`**, **`PI_DMZ_IP`** using **`/interface print`** and **`/ip address print`**. Thermo **`network.conf`** DMZ subnets are **`10.`…`/24`**-style (**see ROUTERBOARD**) — **do not** paste real IPs, **`network.conf`**, ISP WANs, or public DNS labels into **public** repos.

---

## RouterOS caveat — `print … where …`

Many RouterOS 6 setups return **only** the **`Flags:`** line (no rows) for **`print where …`** on **NAT**, **filter**, **route** — even when rules exist.

**Use full tables:** **`/ip firewall nat print`**, **`/ip firewall filter print`**, **`/ip route print`** (**`print numbers`** helps). Find **`dst-port`**, **`comment`**, **`0.0.0.0/0`** manually.

---

## Placeholders

- **WAN_IF** — WAN for NAT (often **ether1-gateway**).
- **LAN_BR** — LAN bridge (often **bridge-local**).
- **DMZ_ETHER** — DMZ port 10 (**ether10-slave-local** or similar).
- **GW_ON_DMZ**, **DMZ_NET**, **PI_DMZ_IP** — examples use **192.0.2.1**, **192.0.2.0/24**, **192.0.2.2** — **yours differs**.

---

## 1) SSH

```bash
ssh admin@<ROUTER_LAN_IP>
```

(Use **your** LAN management address, often **192.168.xx.1**-style.)

---

## 2) Backup / discover

```text
/export file=pre-dmz-ether10-backup
/interface print
/interface bridge port print
/ip address print
/ip route print
/interface ethernet poe print
```

---

## 3–4) Keys, PoE (optional)

Import admin SSH key; set **ether10** **poe-out=off** for non-PoE cabling. Details in ROUTERBOARD + standard RouterOS docs.

---

## 5) ether10 off LAN bridge

```text
/interface bridge port remove [find interface~"ether10"]
```

---

## 6) Router address on DMZ

```text
/ip address add address=192.0.2.1/24 interface=ether10-slave-local comment="thermo DMZ gw"
```

Substitute **GW_ON_DMZ**, **DMZ_ETHER**.

---

## 7) Optional DHCP

```text
/ip pool add name=pool-dmz ranges=192.0.2.10-192.0.2.50
/ip dhcp-server add name=dhcp-dmz interface=ether10-slave-local address-pool=pool-dmz disabled=no
/ip dhcp-server network add address=192.0.2.0/24 gateway=192.0.2.1 dns-server=1.1.1.1 comment="thermo DMZ"
```

---

## 8) Default route (Pi)

Pi default gateway = **GW_ON_DMZ**.

```text
/ip route print where dst-address=0.0.0.0/0
```

If **where** prints nothing, full **`/ip route print`** and find **0.0.0.0/0** (**same caveat**).

---

## 9) NAT — tcp/5000 + SNAT DMZ→WAN

```text
/ip firewall nat add chain=dstnat protocol=tcp dst-port=5000 in-interface=ether1-gateway action=dst-nat to-addresses=192.0.2.2 to-ports=5000 comment="thermo DMZ inbound :5000"
/ip firewall nat add chain=srcnat src-address=192.0.2.0/24 out-interface=ether1-gateway action=masquerade comment="thermo DMZ SNAT to WAN"
```

Replace **ether1-gateway** → **WAN_IF**; replace **192.0.2.*** throughout **§§6–11** if subnets differ.

### WAN → tcp/22 (SSH)

1. Dedupe **:22** with full **`/ip firewall nat print`** and **`/ip firewall filter print`** — **not** **where**-only (**caveat above**).
2. Remove bad rows: **`… print numbers`**, **`… remove numbers=N`**.

```text
/ip firewall nat add chain=dstnat protocol=tcp dst-port=22 in-interface=ether1-gateway action=dst-nat to-addresses=192.0.2.2 to-ports=22 comment="thermo DMZ inbound :22"
```

Forward **accept** must sit **before** (**lower rule number than**) the WAN **new** **forward** **drop** (**connection-nat-state=!dstnat**, **in-interface=WAN_IF**).

```text
/ip firewall filter add chain=forward in-interface=ether1-gateway out-interface=ether10-slave-local protocol=tcp dst-address=192.0.2.2 dst-port=22 action=accept comment="thermo WAN to DMZ :22" place-after=[find chain=forward comment~"thermo WAN to DMZ :8090 UI"]
```

If **place-after=[find …]** fails, **`/ip firewall filter print numbers`**, re-add with **place-before=N** on the WAN **new/drop** rule (one snapshot had **rule 8**).

**Pi image:** **sshd** only after **`sh /root/sshd.sh`** merges **install/rescue_authorized_keys** → **/root/.ssh/authorized_keys** (card + apkovl mirror).

**Hairpin** SSH from LAN (public DNS / loopback) — not §9; mirror §11 (**:5000** / UI) if needed.

**Lab** **install/sshd.sh** path is **not** the production WAN dst-nat target.

---

## 10) Forward — DMZ ⇄ LAN shape

Replace **bridge-local** with **LAN_BR** if needed.

```text
/ip firewall filter add chain=forward action=accept connection-state=established,related comment="thermo DMZ prep: forward est/rel" place-before=0
/ip firewall filter add chain=forward in-interface=ether10-slave-local out-interface=bridge-local action=drop comment="thermo DMZ block to LAN"
/ip firewall filter add chain=forward in-interface=ether1-gateway out-interface=ether10-slave-local protocol=tcp dst-address=192.0.2.2 dst-port=5000 action=accept comment="thermo WAN to DMZ :5000"
```

**Optional** LAN→DMZ drops complicate hairpins — **`/ip firewall filter print`** before merge.

---

## 11) Hairpin (LAN → **http://YOUR_PUBLIC_DNS:5000**)

If UI targets a **public hostname:port** from inside LAN, hairpin **dst-nat**/**src-nat** may be required — environment-specific; **ROUTERBOARD** hairpin section.

---

## 12) Persist

```text
/system backup save name=post-dmz-ether10
```

---

## Notes

- Prior art sometimes used **ether9**; this doc standardizes **ether10** (RB2011 PoE-out).
- Extend when production filter/NAT freeze; see **ROUTERBOARD-DMZ.md**.
