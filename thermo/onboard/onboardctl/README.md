# onboardctl

Direct onboard debug CLI -- sibling *role* to `thermo/dmz/manage`, but talks to
boards on their local HTTP debug port (default `:5000`) and **bypasses the DMZ**.

```text
onboardctl <subcommand> <zonespec> [extraargs...]
```

## vs manage

| | manage | onboardctl |
|--|--------|------------|
| Target | DMZ (`DMZ_URL`) | Board (`zone.env` -> host/:5000) |
| Auth | Zone Ed25519 to DMZ | None (LAN debug) |
| Use | production command/sensors | sync bring-up / debug |

## zonespec

- `zone:office` or bare `office` (default kind)
- `hardware:esp32` (fuzzy; matches esp32s3) / `hardware:esp32s3` / `pico2w` / `pizero`
- `dialect:midea` / `daikin` / ...
- `type:ac` / `heatpump` / `heat` / `led`
- `ALL` -- every `zones/*/zone.env` target (read-only multi; mutating cmds still refuse)

Mutating commands (`sendcommand`, `setvar`) refuse multi-match sets.

## Subcommands

`help`, `logs`, `version`, `healthz`, `deviceinfo`, `sendcommand`, `setvar`

Each prints an `undo:` line on stderr.

`healthz ALL` probes `/healthz` on each configured zone (short timeout, default 3s)
and prints one connectivity line per zone plus a JSON summary; exit 1 if any fail.

## Run

With `binlinks/` on `PATH` (`make binlinks`):

```bash
onboardctl help
onboardctl healthz ALL
onboardctl logs office
onboardctl sendcommand kitchen   # defaults: cool / auto / on / 22c
```

Or from the package dir:

```bash
cd thermo/onboard/onboardctl
./onboardctl help
```

Tests: `make -C thermo/onboard test-local` (includes `test/test_onboardctl_*.py`).
