# Agent Notes -- ESP32-S3 onboard (MicroPython)

Runtime is **MicroPython** under `mp/`. Toit/Jaguar is retired for this board.

Human plan history: [`PLAN.md`](PLAN.md) (Appendix B is now the primary path).

## Bootstrap goals (current)

1. Flash MicroPython once (SPIRAM / N16R8 build).
2. Upload `install/upload.manifest` (Midea canned on/off; Daikin omitted).
3. Fire IR: `GET /ir/on` and `GET /ir/off` (or `main.py --ir-on` / `--ir-off`).

Host dry-run (no board):

```bash
make -C thermo/onboard/hardware/esp32s3 test
```

## Development cycle (bench)

Once USB serial is present (`ESP32S3_FLASH_PORT` / `$PORT`):

```bash
export PORT=/dev/cu.wchusbserialXXX
cd thermo/onboard/hardware/esp32s3/mp

# A) Edit on host, run once on device (fastest; no main.py required on flash)
mpremote connect $PORT mount . run main.py -- --ir-on
mpremote connect $PORT mount . run main.py -- --ir-off

# B) Interactive REPL with host tree mounted at /remote
mpremote connect $PORT mount . repl
# >>> import sys; sys.path.insert(0, '/remote')
# >>> import ir_canned, ir_tx
# >>> ir_tx.transmit_mark_space(ir_canned.timings_us(True))

# C) Persist upload (survives reset); soft-reset runs main.py accept loop
THERMO_ENV_FILE=onboard/zones/office/zone.env ESP32S3_FLASH_PORT=$PORT \
  ../install/deploy.sh
# After WiFi later: curl http://<ip>:5000/ir/on
```

Cycle: edit host file -> `mpremote mount . run ...` -> observe IR / serial -> repeat.
No firmware reflash between Python edits.

## REPL basics

```bash
ls /dev/cu.wchusbserial* /dev/cu.usbmodem* 2>/dev/null
export PORT=/dev/cu.wchusbserial110
mpremote connect $PORT repl
mpremote connect $PORT exec "print(1+1)"
```

## Host tests

```bash
make -C thermo/onboard/hardware/esp32s3 test
```

Legacy Rust scaffold under `src/*.rs` is host-only reference; live path is `mp/`.

## Flash MicroPython (once per board) -- needs board plugged in

Erase Jaguar/Toit, then write ESP32-S3 SPIRAM (octal / N16R8) from
https://micropython.org/download/ESP32_GENERIC_S3/

```bash
esptool --chip esp32s3 --port $PORT erase_flash
esptool --chip esp32s3 --port $PORT --baud 460800 write_flash -z 0x0 ESP32_GENERIC_S3-*.bin
```
