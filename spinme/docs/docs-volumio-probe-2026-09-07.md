# Volumio host probe (2026-09-07)

| Target | Result |
|--------|--------|
| `http://volumio.local/api/v1/getState` | DNS timeout (no resolve) |
| `http://127.0.0.1:3000/api/v1/getState` | Connection refused |
| `http://miniDSP-SHD.local/api/v1/getState` | **OK** -- JSON state (paused track reported) |
| `http://shd.local/...` | DNS timeout |

Use **`miniDSP-SHD.local`** as the Volumio HTTP base on this LAN until mDNS
`volumio.local` is fixed or a static IP is chosen.
