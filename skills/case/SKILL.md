---
name: case
description: >-
  Read and write troubleshooting CASE files before inventing a diagnosis.
  Auto-apply when asked to diagnose errors, failures, stack traces, CI/pytest
  failures, setup failures, or repeated-looking symptoms. Also use when the
  user says CASE skill, CASE file, cases/, RCA, symptoms/evidences, or after
  a troubleshooting session that should not live only in chat.
disable-model-invocation: false
---

# CASE skill

Two corpora in this repo. Scan both before guessing. This skill is a cheap
dispatcher; verbose material lives in the files below.

| Corpus | Path | Shape |
|--------|------|--------|
| Playbooks | `troubleshooting/` | `CASE:*.md` + `troubleshooting/TROUBLE.md` |
| Incident RCA | `cases/` | `YYYY-MM-DD-short-slug.md` + `cases/TEMPLATE.md` |

Human index for RCA: `cases/README.md`.

## Cheap scan

Start with filenames (`CASE:*` and `cases/*.md`, skip templates). Then metadata:

```sh
rg -i "^(Summary|Keywords):" ./troubleshooting
rg -i "^(# CASE:|- Hosts|- Status)" ./cases
```

Search a few keywords from the failure (error text, host, service, tool). Keep
playbook keyword categories cheap:

`testing`, `ci`, `pytest`, `python2`, `python3`, `celery`, `docker`, `iamlazy`,
`cursor`, `frontend`, `angular`, `react`, `node`, `npm`, `aws`, `kms`, `nginx`,
`certs`.

## Workflow

1. Search both trees for distinctive error text, hosts, ports, filenames, commands, or tools.
2. If a CASE matches, follow it as prior art. Re-verify evidence on the live system (IPs and mounts rot).
3. After the incident is understood, write or update. Prefer updating an existing CASE over a near-duplicate.
4. Point the user at the file. Do not paste the RCA back into chat if they asked you not to.
5. Do not start a CASE for a one-line typo fix.

## Write: playbook (`troubleshooting/`)

- Path: `troubleshooting/CASE:<brief-symptom>.md` (see `TROUBLE.md` glossary)
- Start from `_CASE:template.md` when it exists
- Cheap header: `Summary:` and `Keywords:`
- Mandatory sections: `# Symptoms` and `# Solutions` (synonyms ok). Optional `# Solved`.
- Targeted at machine consumption; human discussion may precede those sections.

## Write: incident RCA (`cases/`)

The CASE file has four parts, then discussion:

1. **Symptoms** — the external issues that led us here.
2. **Evidences** — corroboration, and **anti-evidence**.
3. **Analysis** — facts for the layman (mechanism, not a war diary). Example: symptom — body is cold and unresponsive; evidence — retrieved floating face down on a lake; analysis — medical facts of drowning, and also CPR.
4. **Remediation** — what to do and **why**, so the next agent can vary details (seaweed in the trachea: remove it, then CPR).

Rules:

- Path: `cases/YYYY-MM-DD-short-slug.md`
- Add one line to the table in `cases/README.md`
- No chat dumps, no tool traces, no “then I ran ss.” Facts and mechanism only.
- Status in the header: `open` | `remediated` | `wontfix`
- Anti-evidence is mandatory. Name the tempting wrong theory and the fact that kills it.
- Remediation must say **why**.

## Anti-patterns

- Symptoms that are actually analysis (“CIFS was stale”).
- Evidence that is only “I think.”
- Remediation that is a command list with no why.
- Filing operator mood or the investigation timeline as the mechanism.
- Skipping the corpus search and inventing a fresh theory for a repeated-looking failure.
