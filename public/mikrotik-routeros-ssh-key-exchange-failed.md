# MikroTik RouterOS 6.49 SSH — connection drops before password prompt

## Clickbait

A MikroTik RouterBOARD running RouterOS 6.49.19 (long-term) refuses every SSH connection
from a modern macOS or Linux client. The client connects, negotiates algorithms, then the
**server** sends `Disconnect (code 3): KEY_EXCHANGE_FAILED` — immediately after the client
sends its Diffie-Hellman public value. You never see a password prompt. No error message
explains what went wrong. The root cause is a **1024-bit DH prime** that RouterOS uses by
default for group-exchange, which modern SSH clients require to be at least 2048 bits. A
secondary cause is the **old RSA host key** (also generated at 1024 bits) that can no
longer sign the KEX reply once strong-crypto mode is enabled. Both are fixed with two
clicks in WebFig and no client configuration changes.

---

## Environment

| Component | Value |
|-----------|-------|
| Router | MikroTik RB2011 (or any RouterBOARD) |
| RouterOS | 6.49.19 long-term |
| SSH client | OpenSSH 9.9p2 / LibreSSL 3.3.6 (macOS) |
| SSH client also tested | paramiko 4.0.0 (Python) |

---

## Symptoms

- `ssh admin@tik` hangs briefly then exits with no useful message.
- With `-v`: connection reaches `SSH2_MSG_KEX_DH_GEX_INIT sent` then immediately:
  ```
  Received disconnect from 192.168.88.1 port 22:3:
  Disconnected from 192.168.88.1 port 22
  ```
- The disconnect code `3` is `SSH_DISCONNECT_KEY_EXCHANGE_FAILED`.
- No password prompt is ever shown.
- `ssh-keyscan` and `ssh-audit` appear to succeed (they scan without completing the full
  DH exchange), which misleads you into thinking the server is healthy.
- IP access control is **not** the issue — the client IP is within the allowed subnet.

---

## Diagnosis

**Phase 1 — default config (`strong-crypto=no`)**

`ssh -vvv` reveals the server's KEXINIT offers only `diffie-hellman-group-exchange-sha256`
and friends. The client requests a DH group with `min=2048, preferred=7680–8192`. The
server sends back a **1024-bit prime** (`Got server p (1024 bits)`). Modern OpenSSH
enforces a minimum of 2048 bits; when paramiko (which is more lenient) accepts the
1024-bit group and sends the DH init anyway, RouterOS itself disconnects with code 3 —
it apparently cannot complete the exchange with its own undersized group.

```
debug1: SSH2_MSG_KEX_DH_GEX_REQUEST(2048<7680<8192) sent
debug1: SSH2_MSG_KEX_DH_GEX_GROUP received      # server sends 1024-bit prime
debug1: SSH2_MSG_KEX_DH_GEX_INIT sent
Received disconnect from 192.168.88.1 port 22:3:
```

**Phase 2 — after `strong-crypto=yes` (2048-bit prime, still fails)**

With `strong-crypto=yes` the server now sends a 2048-bit prime and offers only
`hmac-sha2-256`. The client accepts the group and sends GEX_INIT. The server still
disconnects with code 3. The 2048-bit DH math itself is fine; the server cannot
**sign** the KEX reply because the existing RSA host key was generated at 1024 bits
(before strong-crypto was enabled) and is now incompatible.

---

## Fix

Apply in order via **WebFig → IP → SSH**:

1. **Enable Strong Crypto**: set `strong-crypto = yes`
   (upgrades the GEX DH prime from 1024-bit to 2048-bit, switches MAC from SHA1 to SHA256)

2. **Regenerate Host Key**: click the "Regenerate Host Key" button
   (creates a fresh 2048-bit RSA key that can actually sign the KEX reply)

Or from a RouterOS terminal (Winbox / serial console):

```
/ip ssh set strong-crypto=yes
/ip ssh regenerate-host-key
```

After both steps, plain `ssh admin@tik` reaches the password prompt with no client-side
changes required.

---

## Why `ssh-audit` did not reveal the problem

`ssh-audit` probes each algorithm by receiving the server's KEXINIT and (for GEX
algorithms) the `KEX_DH_GEX_GROUP` packet to measure the prime size — but it does **not**
complete the full exchange by sending `KEX_DH_GEX_INIT`. So it reports a valid 1024-bit
(then 2048-bit) group without ever triggering the server-side signing failure. The scan
looks green while every real SSH client fails.
