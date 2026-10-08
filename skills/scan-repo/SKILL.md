---
name: scan-repo
description: Run the local CLI code scanner on the current repo (the cwd) and report metrics, complexity, smells, docs coverage, and a quality score. Invoke ONLY when the user explicitly asks for "scan-repo" or explicitly asks to run the code scanner on the current/this repo. Do not trigger automatically.
---

# scan-repo

Runs the standalone code scanner on the **current repository** (the current
working directory) and summarizes the result.

## Scanner location and command line

- Binary (chmod +x executable): `/Users/ovlingej/webinar/scanner/bin/scanner`
- Invoke the executable directly. Never use `python -m` (repo rule).

Run exactly this, scanning the cwd and writing reports to a per-repo temp dir:

```
SCANNER=/Users/ovlingej/webinar/scanner/bin/scanner
OUT="/tmp/scan-$(basename "$PWD")"
"$SCANNER" . --out "$OUT"
```

This writes `$OUT/results.json` (canonical JSON, the schema source of truth)
and `$OUT/report.md` (human-readable report), and prints the headline score.

## Optional flags (pass through only if the user asks)

- `--complexity-threshold N` : cyclomatic complexity threshold (default 10).
- `--format json,md`         : restrict output formats (default both).
- `--out DIR`                : override the output directory.

## Steps

1. Confirm the scanner binary exists at the path above. If it is missing, tell
   the user it is not installed at the expected location instead of guessing.
2. Run the command line above from the current working directory.
3. Read `$OUT/results.json` and report a concise summary: headline score +
   grade, the sub-score breakdown, file/LOC/language counts, the top complexity
   offenders, smell counts by kind, and documentation coverage.
4. Point the user to `$OUT/results.json` and `$OUT/report.md` for full detail.

## Notes

- Deep analysis (complexity, smells, docs) is Python-only; other languages get
  metrics with heuristic, best-effort function/class counts (flagged in output).
- `ast.parse` may emit harmless `SyntaxWarning`s on files that use non-raw regex
  strings; the files are still parsed and analyzed.
- Keep all output ASCII only.
