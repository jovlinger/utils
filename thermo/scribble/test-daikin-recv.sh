#!/usr/bin/env bash
# Test daikin-recv.py with a fake ir-ctl at head of PATH. Fake echoes a hardcoded
# Daikin 3-frame pulse/space sequence; we assert the decoder prints the expected frames.
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export PATH="${SCRIPT_DIR}/tests:${PATH}"
cd "$SCRIPT_DIR"

out="$(python3 daikin-recv.py 2>/dev/null)" || true
# Recv runs until fake ir-ctl exits (after printing the sequence); decoder then flushes.

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
