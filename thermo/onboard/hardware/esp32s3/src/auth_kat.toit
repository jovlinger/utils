// M2 known-answer test for Ed25519 C service.
import .auth

main:
  ok := kat-pico-unit-test
  if ok:
    print "M2 PASS: Ed25519 KAT matches TSL vector"
  else:
    print "M2 FAIL: signature mismatch"
    throw "kat failed"
