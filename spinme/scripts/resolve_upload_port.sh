#!/usr/bin/env bash
# Print USB serial port for Waveshare S3 upload. Prefer UPLOAD_PORT.
set -euo pipefail
if [[ -n "${UPLOAD_PORT:-}" ]]; then
  echo "$UPLOAD_PORT"
  exit 0
fi
# Espressif USB-JTAG / CDC often appears as cu.usbmodem*
shopt -s nullglob
ports=(/dev/cu.usbmodem* /dev/ttyACM* /dev/ttyUSB*)
if ((${#ports[@]} == 0)); then
  echo "no USB serial port; set UPLOAD_PORT" >&2
  exit 1
fi
# Prefer a single modem; if several, take the first sorted.
IFS=$'\n' sorted=($(printf '%s\n' "${ports[@]}" | sort))
echo "${sorted[0]}"
