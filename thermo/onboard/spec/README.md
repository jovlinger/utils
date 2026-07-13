# Thermo Spec Language (TSL) 1.0

TSL is the single non-executable source of truth for thermo onboard behavior.
All firmware backends are translations of TSL, not parallel specs.

## Hard constraints

- JSON only. Do not add YAML.
- Every spec JSON keeps `"$tsl": "1.0"` and a string `"kind"`.
- File names use `*.tspec.json`.
- This tree is non-executable; do not add `.py`, `.toit`, `.rs` under `spec/` (except agent instruction markdown files).

## Formal grammar

### Document grammar

```text
tsl_document := object {
  "$tsl": "1.0",
  "kind": <kind_name>,
  ...kind-specific fields...
}
```

### Kind registry

The canonical kind registry is `tsl-schema.tspec.json`.

| kind | Required fields beyond `"$tsl"` and `"kind"` |
| --- | --- |
| `manifest` | `name`, `documents`, `translation_targets` |
| `tsl_schema` | `name`, `global_requirements`, `kinds` |
| `controller` | `name`, `startup`, `poll_loop`, `on_ir_command_applied` |
| `command_freshness` | `name`, `source`, `rule`, `cases` |
| `dmz_request` | `method`, `path_template`, `headers`, `signing`, `response_parse` |
| `dmz_golden` | `name`, `source`, `expected_body_json` |
| `auth_vectors` | `source`, `sha256_hex`, `sign_headers` |
| `ir_protocol` | `name`, `source`, `carrier_hz`, `timing_microseconds`, `encoding`, `transmit_sequence`, `golden_frames` |
| `profile` | `zone_name`, `backend`, `hardware_profile`, `ir_protocol` |

## Translation rules

1. Treat each `*.tspec.json` file as declarative input only.
2. Generate or maintain target firmware from TSL kinds, never the reverse.
3. Keep goldens and vectors aligned with `thermo/onboard/hardware/pico2w/src/` tests unless marked manual.
4. For command freshness, apply commands only when `response.command.created_dt` is non-empty and lexicographically strictly greater than last applied.
5. If TSL conflicts with target code, correct TSL first, then re-translate.

## File map

| File | kind | Purpose |
| --- | --- | --- |
| `manifest.tspec.json` | `manifest` | Index and translation workflow |
| `tsl-schema.tspec.json` | `tsl_schema` | TSL meta-schema and kind requirements |
| `controller.tspec.json` | `controller` | Poll loop, startup, post body rules |
| `command_freshness.tspec.json` | `command_freshness` | Freshness decision vectors |
| `dmz/request.tspec.json` | `dmz_request` | HTTP contract, headers, signing payload |
| `dmz/golden_cold_start.tspec.json` | `dmz_golden` | Exact cold-start POST body |
| `dmz/golden_command_freshness.tspec.json` | `dmz_golden` | Golden freshness gate vectors |
| `auth/vectors.tspec.json` | `auth_vectors` | SHA256 and Ed25519 known-answer vectors |
| `ir/midea24_coolix.tspec.json` | `ir_protocol` | IR timing and frame vectors |
| `profiles/esp32s3_office.tspec.json` | `profile` | Office ESP32-S3 profile |
| `profiles/pico2w_office.tspec.json` | `profile` | Office Pico2W reference profile |

## Agent workflow

1. Spec author edits TSL JSON in this directory.
2. Implementer reads TSL and emits target code.
3. Grader checks target behavior against TSL vectors and goldens.
