#!/bin/sh
# Deploy a Pico2W room target attached to this host.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PICO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO="${REPO_PATH:-$(cd "$PICO_DIR/../../../.." && pwd)}"
THERMO_ROOT="$REPO/thermo"
export THERMO_ROOT

log() { echo "[pico2w-deploy] $*"; }

if [ ! -d "$REPO" ]; then
	log "Repo not found: $REPO. Set REPO_PATH."
	exit 1
fi

: "${THERMO_ENV_FILE:?set THERMO_ENV_FILE e.g. export THERMO_ENV_FILE=config/kitchen-pico2w.env}"

PICO2W_DEPLOY_ACTION_OVERRIDE="${PICO2W_DEPLOY_ACTION:-}"
PICO2W_UF2_PATH_OVERRIDE="${PICO2W_UF2_PATH:-}"
PICO2W_UF2_VOLUME_OVERRIDE="${PICO2W_UF2_VOLUME:-}"

if [ -f "$THERMO_ROOT/config/source-thermo-env.sh" ]; then
	set -a
	# shellcheck source=/dev/null
	. "$THERMO_ROOT/config/source-thermo-env.sh"
	set +a
fi

: "${ONBOARD_DEPLOY_BACKEND:?set ONBOARD_DEPLOY_BACKEND=pico2w in $THERMO_ENV_FILE}"
if [ "$ONBOARD_DEPLOY_BACKEND" != "pico2w" ]; then
	echo "ONBOARD_DEPLOY_BACKEND=$ONBOARD_DEPLOY_BACKEND does not match pico2w" >&2
	exit 1
fi

: "${PICO2W_IMPLEMENTATION:=rust}"
if [ "$PICO2W_IMPLEMENTATION" != "rust" ]; then
	echo "PICO2W_IMPLEMENTATION=$PICO2W_IMPLEMENTATION is not supported by this deploy script" >&2
	exit 1
fi

PICO2W_PRIV_ENV="${PICO2W_PRIV_ENV:-$THERMO_ROOT/priv/pico2w/${ZONE_NAME:-pico2w}.env}"
if [ -f "$PICO2W_PRIV_ENV" ]; then
	set -a
	# shellcheck source=/dev/null
	. "$PICO2W_PRIV_ENV"
	set +a
	log "loaded private Pico2W env: $PICO2W_PRIV_ENV"
else
	log "WARN: private Pico2W env missing: $PICO2W_PRIV_ENV"
	log "      Put PICO2W_WIFI_PASSWORD there before flashing real firmware."
fi

MAKE=${MAKE:-make}
CARGO=${CARGO:-"$HOME/.cargo/bin/cargo"}
if [ ! -x "$CARGO" ]; then
	CARGO=cargo
fi
ELF2UF2=${ELF2UF2:-"$HOME/.cargo/bin/elf2uf2-rs"}
if [ ! -x "$ELF2UF2" ]; then
	ELF2UF2=elf2uf2-rs
fi
PICO2W_TARGET="${PICO2W_TARGET:-thumbv8m.main-none-eabihf}"
if [ -n "$PICO2W_DEPLOY_ACTION_OVERRIDE" ]; then
	PICO2W_DEPLOY_ACTION="$PICO2W_DEPLOY_ACTION_OVERRIDE"
fi
if [ -n "$PICO2W_UF2_PATH_OVERRIDE" ]; then
	PICO2W_UF2_PATH="$PICO2W_UF2_PATH_OVERRIDE"
fi
if [ -n "$PICO2W_UF2_VOLUME_OVERRIDE" ]; then
	PICO2W_UF2_VOLUME="$PICO2W_UF2_VOLUME_OVERRIDE"
fi
PICO2W_DEPLOY_ACTION="${PICO2W_DEPLOY_ACTION:-check}"
if [ "${THERMO_DEPLOY_EXECUTE:-0}" != "1" ] && [ "$PICO2W_DEPLOY_ACTION" = "flash" ]; then
	log "check only: --deploy=true not provided, so flash is disabled"
	PICO2W_DEPLOY_ACTION=check
fi
PICO2W_UF2_VOLUME="${PICO2W_UF2_VOLUME:-/Volumes/RP2350}"
PICO2W_UF2_PATH="${PICO2W_UF2_PATH:-$PICO_DIR/target/$PICO2W_TARGET/release/ledw_status_rp2350.uf2}"

if [ -z "${PICO2W_ZONE_PRIVATE_KEY_B64:-}" ] && [ -n "${ZONE_PRIVATE_KEY:-}" ]; then
	PICO2W_ZONE_PRIVATE_KEY_B64="$ZONE_PRIVATE_KEY"
	export PICO2W_ZONE_PRIVATE_KEY_B64
fi

if [ "$PICO2W_DEPLOY_ACTION" = "flash" ] && [ -z "${PICO2W_ZONE_PRIVATE_KEY_B64:-}" ] && [ -z "${ZONE_PRIVATE_KEY:-}" ]; then
	ZONE_PRIVATE_KEY_PATH="${ZONE_PRIVATE_KEY_PATH:-$THERMO_ROOT/priv/zone/priv.pem}"
	if [ -f "$ZONE_PRIVATE_KEY_PATH" ]; then
		if [ -z "${PYTHON_BIN:-}" ]; then
			if [ -x "$THERMO_ROOT/onboard/.venv/bin/python" ]; then
				PYTHON_BIN="$THERMO_ROOT/onboard/.venv/bin/python"
			else
				PYTHON_BIN=python3
			fi
		fi
		PICO2W_ZONE_PRIVATE_KEY_B64="$("$PYTHON_BIN" - "$ZONE_PRIVATE_KEY_PATH" <<'PY'
import base64
import sys
from cryptography.hazmat.primitives import serialization

path = sys.argv[1]
with open(path, "rb") as f:
    key = serialization.load_pem_private_key(f.read(), password=None)
der = key.private_bytes(
    encoding=serialization.Encoding.DER,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
)
print(base64.b64encode(der).decode())
PY
)"
		export PICO2W_ZONE_PRIVATE_KEY_B64
		log "loaded zone private key from: $ZONE_PRIVATE_KEY_PATH"
	fi
fi

if [ "$PICO2W_DEPLOY_ACTION" = "flash" ]; then
	: "${PICO2W_WIFI_PASSWORD:?set PICO2W_WIFI_PASSWORD in $PICO2W_PRIV_ENV}"
	: "${PICO2W_ZONE_PRIVATE_KEY_B64:?set ZONE_PRIVATE_KEY_PATH or PICO2W_ZONE_PRIVATE_KEY_B64 in private env}"
fi

log "repo=$REPO env=$THERMO_ENV_FILE action=$PICO2W_DEPLOY_ACTION target=$PICO2W_TARGET"
case "${PICO2W_DEPLOY_ACTION:-check}" in
check)
	"$MAKE" -C "$PICO_DIR" CARGO="$CARGO" PICO2W_TARGET="$PICO2W_TARGET" build
	;;
firmware-check)
	"$MAKE" -C "$PICO_DIR" CARGO="$CARGO" PICO2W_TARGET="$PICO2W_TARGET" firmware-check
	;;
flash)
	"$MAKE" -C "$PICO_DIR" CARGO="$CARGO" PICO2W_TARGET="$PICO2W_TARGET" build firmware-build
	PICO2W_ELF_PATH="$PICO_DIR/target/$PICO2W_TARGET/release/ledw_status"
	if [ -f "$PICO2W_ELF_PATH" ]; then
		"$ELF2UF2" "$PICO2W_ELF_PATH" "$PICO2W_UF2_PATH"
		"${PYTHON_BIN:-python3}" - "$PICO2W_UF2_PATH" <<'PY'
import struct
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = bytearray(path.read_bytes())
if len(data) % 512 != 0:
    raise SystemExit(f"UF2 size is not block aligned: {path}")
for offset in range(0, len(data), 512):
    magic0, magic1, flags = struct.unpack_from("<III", data, offset)
    if magic0 != 0x0A324655 or magic1 != 0x9E5D5157:
        raise SystemExit(f"bad UF2 magic at block {offset // 512}")
    if flags & 0x00002000:
        struct.pack_into("<I", data, offset + 28, 0xE48BFF59)
path.write_bytes(data)
PY
	fi
	: "${PICO2W_UF2_PATH:?set PICO2W_UF2_PATH to the built .uf2 before PICO2W_DEPLOY_ACTION=flash}"
	if [ ! -f "$PICO2W_UF2_PATH" ]; then
		echo "PICO2W_UF2_PATH not found: $PICO2W_UF2_PATH" >&2
		exit 1
	fi
	if [ ! -d "$PICO2W_UF2_VOLUME" ]; then
		echo "Pico boot volume not mounted: $PICO2W_UF2_VOLUME" >&2
		echo "Hold BOOTSEL while plugging in the Pico2W, then retry." >&2
		exit 1
	fi
	if cp -X "$PICO2W_UF2_PATH" "$PICO2W_UF2_VOLUME/" 2>/dev/null; then
		:
	else
		cp "$PICO2W_UF2_PATH" "$PICO2W_UF2_VOLUME/"
	fi
	log "Copied $(basename "$PICO2W_UF2_PATH") to $PICO2W_UF2_VOLUME"
	log "After reboot, open USB serial debug before trusting WiFi/DHCP:"
	log "  ls /dev/cu.usbmodem*"
	log "  screen /dev/cu.usbmodemXXXX 115200"
	;;
*)
	echo "unsupported PICO2W_DEPLOY_ACTION=${PICO2W_DEPLOY_ACTION}" >&2
	exit 1
	;;
esac
log "Deploy complete."
