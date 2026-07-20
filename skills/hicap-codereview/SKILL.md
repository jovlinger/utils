---
name: hicap-codereview
description: >-
  Quality/token guidance for code review with high-capability models.
  Default invocation: `/multi-model-review` (parallel adversarial reviewers,
  synthesized verdict). Special case: single expensive model (strategy 1 below).
  Also covers filing review follow-ups as a parent-linked child todo. Use when
  the user asks for hicap / multi-model / adversarial codereview, or how to
  package a review prompt for max quality per token (including todo-backed work).
disable-model-invocation: true
---

# High-capability code review (quality / tokens)

status: living document

How to **package** a review for an expensive model so quality stays high and
both input and output tokens stay low. This skill is policy for the review
*call*; it does not replace Bugbot, PR CI, or local tests.

## Goal

Maximize **defect signal per token**: the model should judge whether the change
meets stated acceptance criteria (AC), not narrate the diff or rewrite the code.

## Review packaging (input)

Three common strategies, ranked for goal-oriented review:

| # | Strategy | When | Quality / tokens |
|---|----------|------|------------------|
| 1 | Present intent/AC + **final result only** (net tree or `base..HEAD`) | Default | Best: intent paid once; catches integration and AC gaps |
| 2 | Present intent/AC + **each commit in isolation** (loop) | Selective follow-up on large/risky commits, or when final pass flags something commit-local | Higher cost (~N calls); often wastes budget on superseded interim states |
| 3 | Present **each commit alone**, no AC, no siblings, clear context between | Mechanical craft-only audits with no goal | Worst for "is this done correctly": strips the definition of correct; still pays N calls |

**Default:** strategy **1**.

**Hybrid under a cost cap:** run (1) once; then (2) only on the 1-2 fattest or
riskiest commits if the final pass needs a blame-local follow-up. If using (2),
pass a **short AC excerpt**, not a full chat history or long body dump.

Why (1) wins for expensive models:

- Quality scales with **relevant context + manageable diff**, not with more narrative.
- Cross-cutting bugs, shared API shape, and tests that only pass together show up in the end state.
- Per-commit loops re-pay preamble tokens and often flag intermediate commits that were correctly superseded.

When to avoid dumping the entire final diff into one call: if `base..HEAD` is
huge enough to thrash context, split by **subsystem or path**, still against the
same AC -- not by every historical commit unless blame matters.

## Output (minimize tokens)

Prefer **findings-only** with a tight fixed schema over open-ended English prose.

Open prose complaints beat praise + patches + file dumps, but free-form text
still burns tokens on hedges and duplication. Cheapest high-signal pattern:

1. **Negative-only:** list defects vs AC; if none, reply exactly `OK`.
2. **Hard cap:** max N findings; one line each.
3. **No fixes / no code** unless asked -- suggested diffs dwarf the complaints.
4. **Defer bulk:** cite `path` + symbol or line; quote at most one line of code.

Suggested line format:

```text
severity | path[:line] | issue
```

Example prompt fragment:

```text
List defects vs the AC only. Max 10 findings. One line each:
severity | path[:line] | issue
No praise, no summaries, no patches, no code quotes longer than one line.
If none: OK
```

Structured short lines usually beat paragraphs for **output** tokens; plain
English is fine if each finding is one sentence and praise/summaries are banned.

## Multi-model adversarial review (default)

**Invocation:** `/multi-model-review` (Cursor command). This is the **general
case**; everything below applies unless the user explicitly asks for a
single-model pass.

### Flow

1. **Scope:** user paths/diff, else `git diff main...HEAD`, else unstaged+staged,
   else conversation context.
2. **Intent:** one paragraph -- what the change is trying to accomplish.
3. **Pick models:** AskQuestion with Task-tool model slugs (multi-select). Skip
   only when the user already named models unambiguously.
4. **Launch reviewers in parallel:** one Task subagent per model (`generalPurpose`,
   readonly), **same turn, same prompt** -- never sequential. Each reviewer gets
   intent + diff/material and returns structured findings:
   `severity (critical|warning|nit) | location | evidence | optional fix`.
5. **Parent synthesizes:** consensus (2+ models), lone-model findings, dedupe,
   categorize (act on / consider / noted / dismissed). Do **not** auto-apply fixes
   unless asked.

Diversity comes from models, not from different personas or prompts.

### Single-model review (special case)

When the user asks for **one** expensive model only (or picks exactly one in
multi-model flow), use the packaging and output rules in **Review packaging**
and **Output** above -- strategy **1** (intent + AC + final result) by default.

Assume every step in the multi-model flow except step 4 collapses to one reviewer:
same scope, intent, adversarial posture, finding schema, and synthesis categories.
Do not re-run per-commit loops unless strategy 2 applies.

## Filing review follow-ups as a child todo

After synthesis, when the user wants tracked fix work (not immediate edits):

**Use `mint` + `init --parent`, not `add-subtodo`.** `add-subtodo` creates a
**mergeable** child the parent must `merge-subtodo`; review follow-ups are
**informationally linked** work on a sibling branch.

### Shape

| Field | Content |
|-------|---------|
| `Body` | Global concerns: review rubric, dismissed items, cross-file themes |
| `WorkItems` | **One task per source file**; summary lists that file's findings **critical -> warning -> nit** |
| `Parent` | Parent todo Id + Branch (set before `init`) |
| Parent `Subtodos` | Follow-only **`INFO`** back-link (via `doctor` after init) |

### Commands (from repo root on `master`)

```bash
ID=$(todo mint)
todo set --id "$ID" \
  --summary="..." \
  --ac="..."
todo set-json-path "$ID" Body.raw --file=body.json    # JSON string file
todo set-json-path "$ID" Parent --file=parent.json    # [{"Id":"...","Branch":"..."}]
todo set-json-path "$ID" WorkItems --file=wi.json     # one task per file
todo set-json-path "$ID" Scope.path_from_root --file=path.json  # e.g. "vox2stl"
todo init --id "$ID" --branch=<kebab-branch> --stay-on-parent
todo doctor "$ID"   # establishes INFO back-link on parent
```

On the child branch, re-apply `Body`/`Parent`/`WorkItems` with `set-json-path self`
if promote dropped pre-init fields, then `todo doctor self` again.

## Related skills

| When | Use |
|------|-----|
| Branch-bound ticket + WorkItems trail | `todos` |
| Chunk sizing / frequent commits | `frequentcommits` |
| Cursor Bugbot-style local review | review-bugbot (Cursor skill) |

---

## Appendix: Applying to todos

A todo record is, for review purposes, just a **container**:

| Field | Role in review |
|-------|----------------|
| `AC` | Definition of done -- primary rubric for the model |
| `Body` / `Summary` | Intent and constraints; trim aggressively for the review call |
| `BaseSha` + branch commits / WorkItems | The code modifications under review |
| WorkItems | Trail of chunked commits; useful for selective (2), not required for (1) |

### Default todo review (strategy 1)

1. Load the todo's **AC** (and a short summary if AC alone is opaque).
2. Diff or tree from `BaseSha` (or equivalent base) to the todo branch HEAD / last work-item sha.
3. Ask for capped negative-only findings vs AC (see Output above).
4. Do **not** paste the full todo prompt chat, embeddings, or unrelated WorkItem narrative.

Gates already expressed as programmatic AC (pytest, `make test`, batch emacs, etc.)
should be **run**, not re-litigated in prose, unless the review is checking that
the suite/assertions themselves are weak or missing.

### When to loop WorkItems (strategy 2)

Use only if:

- one work-item commit is disproportionately large or risky, or
- the final-result review needs commit-local blame.

For each such item: AC excerpt + that commit's diff only. Skip cleared /
superseded intermediate commits that no longer affect HEAD.

### Avoid for todos (strategy 3)

Do not clear context and review each work item without AC. Without AC, the model
cannot judge todo completion -- only local craft -- which is the wrong question
for ticket review.

### Todo as WLOG container

Any other system that stores **AC + intent text + a bounded set of code
modifications** uses the same packaging rules; `todo.py` / `TODO.json` is one
concrete mechanism, not a special review theory.
