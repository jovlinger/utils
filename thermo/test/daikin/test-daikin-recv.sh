#!/usr/bin/env bash
# Test daikin-recv.py with a fake ir-ctl at head of PATH. Fake echoes a hardcoded
# Daikin 3-frame pulse/space sequence; we assert the decoder prints the expected frames.
set -e
TEST_DIR="$(cd "$(dirname "$0")" && pwd)"
THERMO_DIR="$(cd "$TEST_DIR/../.." && pwd)"
SCRIBBLE="$THERMO_DIR/scribble"
export PATH="${TEST_DIR}:${PATH}"
cd "$SCRIBBLE"

# Pipe fake ir-ctl into decoder (avoids subprocess stdout buffering issues in test env).
out="$("$TEST_DIR/ir-ctl" -d /dev/lirc1 --receive 2>/dev/null | python3 daikin-recv.py --stdin 2>/dev/null)" || true

if ! echo "$out" | grep -q "Daikin 3-frame:"; then
  echo "FAIL: expected 'Daikin 3-frame:' in decoder output" >&2
  echo "$out" >&2
  exit 1
fi
if ! echo "$out" | grep -q "F1:.*11 da 27 00 c5"; then
  echo "FAIL: expected F1 with header and 0xc5 in decoder output" >&2
  echo "$out" >&2
  exit 1
fi
if ! echo "$out" | grep -q "F2:.*11 da 27 00 42"; then
  echo "FAIL: expected F2 with header and 0x42 in decoder output" >&2
  echo "$out" >&2
  exit 1
fi
if ! echo "$out" | grep -q "F3:.*11 da 27 00 00"; then
  echo "FAIL: expected F3 with header in decoder output" >&2
  echo "$out" >&2
  exit 1
fi
if ! echo "$out" | grep -q "Frame3:.*power=ON.*mode=HEAT"; then
  echo "FAIL: expected Frame3 human-readable power=ON mode=HEAT" >&2
  echo "$out" >&2
  exit 1
fi

echo "PASS: daikin-recv.py decoded fake ir-ctl output to expected 3-frame Daikin"
