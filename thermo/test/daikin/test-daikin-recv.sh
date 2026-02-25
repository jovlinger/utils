#!/usr/bin/env bash
# Test daikin-recv.py with a fake ir-ctl at head of PATH.
# Test 1: 3-frame decode (ARC470A1-style via --stdin legacy path)
# Test 2: 2-frame ARC452A9 round-trip (dump -> loads)
set -e
TEST_DIR="$(cd "$(dirname "$0")" && pwd)"
THERMO_DIR="$(cd "$TEST_DIR/../.." && pwd)"
SCRIBBLE="$THERMO_DIR/scribble"
export PATH="${TEST_DIR}:${PATH}"
cd "$SCRIBBLE"

_timeout() { local s=$1; shift; perl -e 'alarm(shift @ARGV); exec @ARGV' "$s" "$@"; }

echo "DEBUG: TEST_DIR=$TEST_DIR"
echo "DEBUG: SCRIBBLE=$SCRIBBLE"

# --- Test 1: 3-frame decode via --stdin ---
echo "DEBUG: running 3-frame --stdin test..."
out="$(_timeout 10 bash -c '"$1/ir-ctl" -d /dev/lirc1 --receive 2>/dev/null | python3 daikin-recv.py --stdin 2>/dev/null' _ "$TEST_DIR" 2>&1)" || true

if [ -z "$out" ]; then
  echo "FAIL: no output from --stdin test (empty)" >&2
  exit 1
fi
echo "DEBUG: --stdin output:"
echo "$out"

if ! echo "$out" | grep -q "Daikin 3-frame:"; then
  echo "FAIL: expected 'Daikin 3-frame:' in decoder output" >&2
  exit 1
fi
if ! echo "$out" | grep -q "F1:.*11 da 27 00 c5"; then
  echo "FAIL: expected F1 with header and 0xc5 in decoder output" >&2
  exit 1
fi
if ! echo "$out" | grep -q "F2:.*11 da 27 00 42"; then
  echo "FAIL: expected F2 with header and 0x42 in decoder output" >&2
  exit 1
fi
if ! echo "$out" | grep -q "F3:.*11 da 27 00 00"; then
  echo "FAIL: expected F3 with header in decoder output" >&2
  exit 1
fi
if ! echo "$out" | grep -q "power=ON.*mode=HEAT"; then
  echo "FAIL: expected power=ON mode=HEAT in decoder output" >&2
  exit 1
fi

echo "PASS: test 1 — 3-frame --stdin decode"

# --- Test 2: ARC452A9 2-frame round-trip (dumps -> loads) ---
echo "DEBUG: running 2-frame ARC452A9 round-trip test..."
rt_out="$(_timeout 10 python3 -c "
import sys, os
sys.path.insert(0, os.path.join('..', 'onboard'))
from heatpumpirctl import State, Mode, Fan
from heatpumpirctl import ARC452A9 as proto

s = State().set_power(True).set_mode(Mode.HEAT).set_temp(22).set_fan(Fan.AUTO)
f1, f3 = proto.dump(s)
assert proto.round_trip_ok(s), 'byte round-trip failed: %s' % s

ir_text = proto.dumps(s)
s2 = proto.loads(ir_text)
assert s2.power == True, 'power mismatch: %s' % s2.power
assert s2.mode == Mode.HEAT, 'mode mismatch: %s' % s2.mode
assert s2.temp_c == 22, 'temp mismatch: %s' % s2.temp_c
assert s2.fan == Fan.AUTO, 'fan mismatch: %s' % s2.fan
assert s2.raw_ir is not None, 'raw_ir not stored'
assert not s2.truncated, 'should not be truncated'
print('round-trip summary:', s2.summary())

s3 = State().set_power(True).set_mode(Mode.COOL).set_temp(26).set_fan(Fan.SILENT).set_swing(True).set_econo(True)
assert proto.round_trip_ok(s3), 'complex round-trip failed'
print('complex summary:', s3.summary())
print('ALL_RT_PASS')
" 2>&1)" || {
  echo "FAIL: 2-frame round-trip python failed (exit $?)" >&2
  echo "DEBUG: output was: $rt_out" >&2
  exit 1
}

echo "DEBUG: round-trip output:"
echo "$rt_out"
if ! echo "$rt_out" | grep -q "ALL_RT_PASS"; then
  echo "FAIL: round-trip did not print ALL_RT_PASS" >&2
  exit 1
fi

echo "PASS: test 2 — ARC452A9 2-frame round-trip"

echo "ALL PASS"
