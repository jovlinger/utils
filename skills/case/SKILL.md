---
name: case
description: >-
  The CASE skill. Read and write agent-oriented troubleshooting CASE files
  under github.com/jovlinger/utils/cases/. Use when the user says CASE skill,
  CASE file, cases/, RCA, symptoms/evidences, or after a troubleshooting
  session that should not live only in chat.
---

# CASE skill

Archive: `utils/cases/` (this repo). Human index: `cases/README.md`.
Template: `cases/TEMPLATE.md`.

The CASE file has four parts, and then discussion. 1. symptoms (the external issues that led us here). 2. evidences (to corroborate, and also anti-evidence), 3. analysis (facts for the layman. eg: symptom: body is cold and unresponsive, evidence: body was retrieved floating face down on a lake. 3: discussion about the medical facts of drowning, and also CPR.  4. remendiation: administer CPR.  but now that we know WHY we do it, we are more flexible about details (e.g there might be seaweed in the trachea. we can deduce on our own to remove it).

## When

- **Read** before inventing a theory that might already be filed (search `cases/*.md` by host, service, symptom).
- **Write or update** when a session produced a real RCA — especially if the user said not to recap in chat.
- Do not start a CASE for a one-line typo fix.

## File rules

- Path: `cases/YYYY-MM-DD-short-slug.md`
- Add one line to the table in `cases/README.md`
- No chat dumps, no tool traces, no “then I ran ss.” Facts and mechanism only.
- Status in the header: `open` | `remediated` | `wontfix`
- Anti-evidence is mandatory. Name the tempting wrong theory and the fact that kills it.
- Remediation must say **why**, so the next agent can change the recipe.

## Workflow

1. Glob `cases/*.md` (skip `TEMPLATE.md`). Grep hosts, ports, error strings.
2. If a CASE matches, treat its analysis as prior art; re-verify evidence on the live system (IPs and mounts rot).
3. After the incident is understood, write the four parts + discussion. Prefer updating an existing CASE over a near-duplicate.
4. Point the user at the file. Do not paste the RCA back into chat if they asked you not to.

## Anti-patterns

- Symptoms that are actually analysis (“CIFS was stale”).
- Evidence that is only “I think.”
- Remediation that is a command list with no why.
- Filing operator mood or the investigation timeline as the mechanism.
