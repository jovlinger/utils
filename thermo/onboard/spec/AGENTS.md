# Agent Notes -- Thermo Spec Language (TSL)

TSL human overview, grammar, and file map: [`README.md`](README.md).

## Hard constraints

- JSON only. Do not add YAML.
- Every spec JSON keeps `"$tsl": "1.0"` and a string `"kind"`.
- File names use `*.tspec.json`.
- This tree is non-executable; do not add `.py`, `.toit`, `.rs` under `spec/` (except agent instruction markdown files).

## Translation rules

1. Treat each `*.tspec.json` file as declarative input only.
2. Generate or maintain target firmware from TSL kinds, never the reverse.
3. Keep goldens and vectors aligned with `thermo/onboard/hardware/pico2w/src/` tests unless marked manual.
4. For command freshness, apply commands only when `response.command.created_dt` is non-empty and lexicographically strictly greater than last applied.
5. If TSL conflicts with target code, correct TSL first, then re-translate.

## Agent workflow

1. Spec author edits TSL JSON in this directory.
2. Implementer reads TSL and emits target code.
3. Grader checks target behavior against TSL vectors and goldens.

Related instruction markdown: [`AGENT_IMPLEMENT_TOIT.md`](AGENT_IMPLEMENT_TOIT.md), [`AGENT_GRADE.md`](AGENT_GRADE.md).
