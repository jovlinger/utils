# `thermo/debuglogs/`

Scratch space for **local** log dumps (Pi, DMZ, containers). **Nothing here is committed** except this README and `.gitignore`.

## File naming

Use **UTC** timestamps so sorts match chronology:

`YYYY-MM-DDTHHMMSSZ_<source>_<topic>.txt`

Examples:

- `2026-03-22T230004Z_pizero-twoway-sticky-lolidk.txt`
- `2026-03-23T120000Z_dmz-zone-sensors-500.txt`

## Required header (first lines of every capture file)

Paste this block at the top of each new log file and fill in the bracketed parts. Lines are `#` comments so parsers can skip them if needed.

```
# thermo/debuglogs — debug capture
# -----------------------------------------------------------------------------
# TITLE:    [one line]
# WHAT:     [sources: e.g. docker logs thermo-onboard + tail onboard.log]
# WHY:      [symptom or hypothesis this supports or rules out]
# COLLECTED: [UTC ISO8601] from [hostname / ssh target / copy-paste source]
# RELATED:  [issue, commit, thermo/TODO.md §N, optional]
# -----------------------------------------------------------------------------
# RETAIN UNTIL: [event, e.g. “twoway dedupe fix merged”] OR [calendar date]
# OK TO DELETE AFTER: [concrete rule, e.g. “fix verified in prod ≥7d” or same date]
# NOT WORTH KEEPING WHEN: [e.g. “only relevant while DMZ was on Flask X”]
# -----------------------------------------------------------------------------
```

The **RETAIN / DELETE / NOT WORTH** lines are the retention contract: future you should be able to garbage-collect without re-reading the whole log.

## Pulling Pi logs (example)

See `thermo/onboard/DEBUG.md` and `thermo/onboard/install/README.md`. Redirect into a **new dated file** under this directory and add the header first.
