---
name: bookmark-management
description: >-
  Write, sync, resume, and delete BOOKMARK.md (and optional EVIDENCE.md) when
  pausing mid-task or before context loss; preserve costed findings for fresh
  sessions; keep TODOs.md Next aligned. Supersedes write-bookmark and
  project-bookmark. Use when walking away from messy state, resuming
  interrupted work, writing a bookmark, handoff, or resume note, before clearing
  context, or when the user mentions pause, resume, or continue where we left
  off.
disable-model-invocation: true
---

# Bookmark Management

status: living document

A bookmark is a **cache of expensive knowledge plus a resume pointer**, written
for a reader with zero history of the writing session. It has two jobs:

1. **CONTINUE** -- enough context to pick work back up and know the exact next
   action.
2. **DON'T RE-PAY** -- enough recorded findings that the next session never
   re-derives what this one already discovered. Write the answer, not the
   question.

Works in any repo; often paired with `project-lifecycle` and `TODOs.md`.

This skill is a living document: more process sources may extend it over time.
Prefer updating this file over duplicating bookmark protocol elsewhere.

## When to use what

| Mechanism | Use when |
|-----------|----------|
| `TODOs.md` **Next** section | Next step is one clear todo with no partial state |
| `BOOKMARK.md` | Mid-todo, multi-file partial state, several open todos, long investigation to preserve, or before context compaction |

If both exist, keep **Next** and `BOOKMARK.md` synchronized.

Also write a bookmark when:

- Ending a session with work unfinished.
- Blocked and parking work for the user or a later session.
- Findings must survive context loss.

Skip `BOOKMARK.md` when the next step is already a single unlocked todo in
**Next** with no partial state.

## Hard rules

- **Write for a no-history reader.** No "as discussed", no pronouns pointing at
  chat history. Name every thing fully (full paths, IDs, URLs).
- **Reference by path, never by memory.** Point to files, dirs, or `file:line`.
- **Record the answer, not just the question.** Verbatim: IDs, endpoints, config
  values, timestamps, working commands, root cause.
- **Record dead ends.** What was tried that did NOT work and why.
- **Distinguish KNOWN from UNKNOWN.** Mark solved facts as solved; mark open
  questions as open.
- **Separate CONTINUE from EVIDENCE when forensic detail is large.** Keep the
  bookmark skimmable; push raw logs, tables, transcripts into sibling
  `EVIDENCE.md` or `FINDINGS.md` and link it.
- **Secrets by reference.** Point at env vars or a secret store; never inline.

## Writing `BOOKMARK.md`

Create at the root of the work directory (same directory as `TODOs.md` when
present). Pair with `EVIDENCE.md` / `FINDINGS.md` when forensic detail is
large.

```markdown
# Bookmark -- <effort name>; <one-line status / BLOCKED on X> (<date>)

created: <ISO-8601 UTC>
created-by: <agent-id>

Handoff to a FRESH session (no history). Read this first, then EVIDENCE.md if
present, then the ledger/code/config it points to.

<one line: what this effort is, its goal, key config/paths>

## Where we are

- <done / works / produced>

## The blocker (if any)  [class: logic | env/infra | external dep | awaiting-human]

<plain statement> -- evidence: <path/section>. <what is ruled out>.

## How it blocks the goal

<why progress stops> ; NOT blocked: <what can still progress>.

## Next steps

0. Re-verify the blocker still holds: <exact command/check>.
1. <next concrete action> ...

## Costed knowledge (do NOT re-derive)

- <exact IDs / endpoints / file:line / values>
- re-run: <exact command that produced finding X>
- dead ends: <what was tried and failed>

## Operating notes

- <approvals, gotchas, conventions, auth/recovery, tooling decisions>
- Active files, branch/commit, partial todos, environment notes
- Locks: note `lockedby` / `lockeduntil` if pausing on a locked todo

## Last instruction

As soon as you have read this BOOKMARK file and have confirmed the environment
is ready to continue work, **DELETE** this file (and optional EVIDENCE.md if
fully absorbed). Update the `state:` line in `TODOs.md` to include
`resumed <date>` when present.
```

The **Last instruction** block is mandatory. Do not omit delete-on-resume.

Also update `TODOs.md` **Next** to match the first post-verify step in **Next
steps** (usually step 1 after step 0 passes).

After writing, tell the user the path and that context is safe to clear.

## Anti-patterns

- Vague status with no concrete state.
- Naming a problem without findings ("there is a 500" with no cause or pointer).
- Making the reader re-run crawls or re-read large dumps to learn what you
  already know.
- Burying the next action in prose; keep numbered **Next steps** near the top.
- Letting the bookmark drift stale; fix superseded claims, do not append
  contradictions.

## Resuming

1. Read `BOOKMARK.md` (if present), optional `EVIDENCE.md`, and `TODOs.md`.
2. Confirm environment (branch, deps, services, cwd).
3. Run **Next steps** step 0 (re-verify blocker / assumptions).
4. **Delete** `BOOKMARK.md` (and `EVIDENCE.md` when no longer needed).
5. Set `TODOs.md` header e.g. `state: IMPL draft | resumed 2026-06-20`.
6. Update **Next** to match reality.
7. Continue from the top eligible unlocked todo, or from step 1 onward.

Do not follow bookmark next steps until environment checks and step 0 pass.

## Stale bookmarks

If `BOOKMARK.md` predates the latest doc approvals (`GOAL.md`, `PLAN.md`,
`IMPL.md` when present), confirm with the user before following it.

If **Next** and `BOOKMARK.md` disagree, treat the bookmark as stale unless the
user says otherwise; reconcile both after confirmation.

## Related

- `project-lifecycle` - GOAL / PLAN / IMPL phases and `TODOs.md` conventions
