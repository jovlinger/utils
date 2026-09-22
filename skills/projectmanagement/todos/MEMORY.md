# Todos as associative memory

The mechanism exists: todos are vector-embedded and `todo.py search` ranks
them against a free-text query. Had we stored "esp32s3 flashed with
Toit/Jaguar, device esp32s3-office at 192.168.88.73" as a note, a later
session asking "what is the state of the esp32?" would have found it in one
query instead of an agent-transcript excavation. What is missing is policy:
what to write, when to write and read, and how to keep the store from silting
up.

## What to store

Store conclusions, not process. A note is worth writing when it (a) cost real
effort to establish (a debugging session, a hardware bring-up, a failed
approach), (b) is not derivable from the repo in one obvious read (READMEs and
code stay the source of truth for anything they already say), and (c) a future
session would plausibly ask for it. Good: "picopi thermo-office unplugged
since 2026-06-27; office zone DMZ data is stale leftovers." Bad: raw logs,
step transcripts, anything that changes weekly and lives in `manage zones`
anyway. One fact-cluster per note, phrased with the searchable words a future
query would use (device names, IPs, milestone names).

## Notes are not todos

Mark memory entries as notes -- same sqlite storage and embedding path, but a
distinct kind so they never appear in work queues, `is-done` checks, or
spawn/merge graphs, and so search results can label them. A note has no
acceptance criteria and no cursor; it has a body, a timestamp, and ideally a
pointer to its source (branch, ticket id, transcript). Reusing the todo store
keeps one index and one search command; the only mechanism change is the kind
flag plus a `search --kind=note|todo|all` filter.

## When to write, when to read

Write at the moments a session crystallizes knowledge: end of a bring-up or
debugging arc, ticket close (distill the outcome into a note rather than
letting it live only in a done todo), and whenever the user states a durable
fact the repo does not capture. Practical trigger: if a completion summary
contains a fact you did not know at session start, that fact is a note
candidate. Read at session start and at points of ignorance: before excavating
transcripts or probing hardware to answer "what is the state of X?", run one
`todo search` with the natural-language question. Lookups are nearly free and
misses are silent, so search early and often; treat a hit as a lead to verify,
not ground truth.

## Eviction and staleness

Prefer supersession over deletion: when a new note contradicts an old one,
update it, or write the new note and tombstone the old. Every note carries its
written-date; search should surface age so readers can weigh freshness, and a
periodic `doctor`-style pass can flag notes past some horizon for review.
Phrase volatile facts with their observation date ("as of 2026-07-14,
esp32s3-office holds 192.168.88.73") so even a stale hit tells the reader what
to re-check.

## Mechanism updates, summarized

Add a note kind to the schema and an `init --note` (summary + body, no work
items); add `search --kind` filtering and show kind + age in results; exempt
notes from doctor's todo-health checks but add a staleness report; optionally
a `supersedes` field so note chains stay navigable. Storage, embedding, and
ranking stay as is.
