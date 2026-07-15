// Ed25519 via custom-envelope C service (Monocypher).
// Service id: thermo.jovlinger/ed25519
// RPC FN_SIGN=0: request seed[32]||message[*] -> signature[64]

import system.external
import encoding.base64
import crypto.sha show Sha256

SERVICE-ID ::= "thermo.jovlinger/ed25519"
FN-SIGN ::= 0

class Ed25519Signer:
  client_/external.Client? := null
  seed_/ByteArray

  constructor seed/ByteArray:
    if seed.size != 32: throw "Ed25519 seed must be 32 bytes"
    seed_ = seed

  open -> none:
    if client_: return
    client_ = external.Client.open SERVICE-ID

  close -> none:
    if client_:
      client_.close
      client_ = null

  /**
  Sign $message with the seed. Returns 64-byte signature.
  */
  sign message/ByteArray -> ByteArray:
    open
    request := ByteArray (32 + message.size)
    request.replace 0 seed_
    request.replace 32 message
    response := client_.request FN-SIGN request
    if response.size != 64: throw "bad signature length $(response.size)"
    return response

  /**
  Build DMZ signing payload and return standard-base64 signature (88 chars).
  */
  sign-headers method/string path/string body/ByteArray zone-name/string epoch-seconds/int -> Map:
    hasher := Sha256
    hasher.add body
    body-hash := hasher.get
    hex := ""
    body-hash.do: | b |
      hex += "$(%02x b)"
    payload := "$method\n$path\n$epoch-seconds\n$hex"
    signature := sign payload.to-byte-array
    return {
      "signature_b64": base64.encode signature,
      "timestamp": "$epoch-seconds",
      "zone_name": zone-name,
    }

/**
Known-answer test from TSL auth/vectors.tspec.json.
Returns true if signature matches expected.
*/
kat-pico-unit-test -> bool:
  // seed all 0x01
  seed := ByteArray 32: 1
  signer := Ed25519Signer seed
  try:
    headers := signer.sign-headers
        "POST"
        "/zone/test/sensors"
        "{}".to-byte-array
        "test"
        1_700_000_000
    expected := "+CJV/yQGEXdJF5N5GSDQLX20Q1OKtVUJYzwR01RrCxlq9FLMY0MY5AUzkjG4drqVR/prmwu006rnnheOAxf4BQ=="
    return headers["signature_b64"] == expected
  finally:
    signer.close
