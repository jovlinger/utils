---
description: Auto-apply when asked to diagnose errors, failures, stack traces, CI failures, pytest failures, setup failures, or repeated-looking symptoms. Check the repo's known CASE troubleshooting corpus before guessing.
user-invocable: false
---

# Troubleshooting Cases

Before inventing a fresh diagnosis for a repeated-looking failure, check the repo's known case corpus:

`./troubleshooting/`

This skill is intentionally a cheap dispatcher. The verbose material lives in `TROUBLE.md` and
individual `CASE:*.md` files.

## Cheap Scan

Start with filenames. `CASE:*` names should usually be sufficient for a quick scan.

For a slightly richer index, scan only metadata:

```sh
rg -i "^(Summary|Keywords):" ./troubleshooting
```

Then search for a small number of relevant keywords from the failure:

```sh
rg -i "pytest|python2|test-group|collection" ./troubleshooting
```

Allowed keyword categories are intentionally restricted so this stays cheap:

`testing`, `ci`, `pytest`, `python2`, `python3`, `celery`, `docker`, `iamlazy`, `cursor`,
`frontend`, `angular`, `react`, `node`, `npm`, `aws`, `kms`, `nginx`, `certs`.

## Workflow

1. Search the troubleshooting directory for distinctive error text, filenames, commands, or tools from the failure.
2. Read matching `CASE:*.md` files and `TROUBLE.md` if you need the case format.
3. Follow the matching case's diagnosis steps before proposing a new theory.
4. If no case matches and you diagnose the problem, add or refine a `CASE:*.md` file with `# Symptoms` and `# Solutions`.
