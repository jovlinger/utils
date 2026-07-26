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

Mutating commands (`sendcommand`, `setvar`) refuse multi-match sets.

## Subcommands

`help`, `logs`, `version`, `deviceinfo`, `sendcommand`, `setvar`

Each prints an `undo:` line on stderr.

## Run

```bash
cd thermo/onboard/onboardctl
./onboardctl help
./onboardctl logs office
./onboardctl sendcommand kitchen   # defaults: cool / auto / on / 22c
```

Tests: `make -C thermo/onboard test-local` (includes `test/test_onboardctl_*.py`).
