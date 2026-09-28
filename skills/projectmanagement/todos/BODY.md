# Writing a todo Body

status: living document - **normative owner** for what goes in `Body` vs a
Note vs a WorkItem vs a subtodo, and for how detailed to be

Load this ONLY when authoring or rewriting a `Body` (or a subtodo's Body). It
is not needed to mint, tier, decompose, reorder, or work a ticket -- those are
[`GROOMING.md`](GROOMING.md) and [`WORKING.md`](WORKING.md).

CLI syntax and schema -> [`IMPLEMENTATION.md`](IMPLEMENTATION.md)
Ticket design / decomposition -> [`GROOMING.md`](GROOMING.md)
Intent router -> [`SKILL.md`](SKILL.md)

---


## The Body is the implementation strategy

For an **implementation** todo -- the most common kind, not the only one -- the
Body is a strategy document, written for an agent about to build the thing:

- what is being built, and the build order
- the architectural decisions **every** WorkItem has to honour
- the invariants and constraints that make a wrong implementation wrong
- pointers to normative artifacts (a committed design doc, a generated
  inventory) rather than copies of them

Broad scope only. If a fact is needed by exactly one WorkItem, it belongs in
that WorkItem, not here.

The Body is **not**:

- a record of how a decision was reached. State the resulting RULE, not the
  case for it, not the alternatives that lost, not who ratified it when. "The
  currency lives in a sibling `<field>_currency` column; do not build a
  separate money table" is the rule. The paragraph explaining why the FK
  design was rejected is not strategy, it is minutes.
- a changelog of itself. No "CORRECTED <date>", no "this section used to
  say", no "kept here because". Git and the store's own history hold that; a
  reader executing the plan is not served by it.
- session narration. No "I verified", no "the agent found". Declarative only.
- a place for facts and findings. Those are Notes -- see below.

### Never mirror the WorkItems list in the Body

No objid roster. No build-order map. No per-item table. No "the plan, in list
order" section. `read` already prints the WorkItems in order, and that list IS
the plan.

WorkItems are live, mutable state: items get inserted, reordered, re-tiered,
split and obsoleted as a routine part of working a ticket. A Body copy of that
list is wrong the first time the plan moves, and a stale copy is WORSE than no
copy, because a reader cannot tell which of the two is current. The Body's job
is the constraints the plan must satisfy; it is not the plan.

Same for a cross-item ordering constraint that a dedicated Body section or a
WorkItem already owns. State a constraint exactly once, in the place that owns
it.

**The test: if I insert or reorder a WorkItem tomorrow, does this Body text
become false?** If yes, it does not belong in the Body.

Single-item pointers are fine and do not rot -- "owned by objid:0017", "the
verified hardcodes are in objid:0014". They attach a constraint to its owner
and survive any reordering. What rots is enumerating the set, or its sequence.

The same rule covers Notes: do not enumerate the notes in the Body. `read` and
the web viewer already list them, and `relto` already says which one bears on
what.

Other todo kinds shift the Body's job, and it is still one job: a research
todo's Body is the question plus what would count as an answer; a review
todo's Body is the scope plus the standard being applied. Same discipline --
what the reader must DO or DECIDE, not how you got here.

## Facts and findings are Notes, not Body

A **Note** is one fact, with no status: `{objid, raw, relto}`. It carries what
was FOUND -- a measurement, an inventory, a hazard someone hit, a constraint
discovered at cost, a decision ratified in chat -- while the Body carries what
to DO about it.

That split is the reason a Body can stay short. A finding written into the
Body has to be re-read by every agent on every descendant forever; the same
finding as a note is cited by the one thing it bears on.

| Write it as | When |
|-------------|------|
| **Body** | A rule every WorkItem must honour, an invariant, the build order, an externally-fixed contract |
| **Note** | Something discovered, measured, counted or ratified -- a fact that is TRUE rather than a thing to do |
| **WorkItem** | A step someone has to take, with a status and a disposition |
| **subtodo** | A step that needs its own branch, context and artifact |

A note has no status by construction. If what you are writing needs a
disposition -- done, blocked, obsolete -- it is a WorkItem, not a note.

Write a note the moment the fact exists, not at the end. `note-add` prints the
new objid, which is the handle everything else uses:

```bash
todo.py note-add <id> --raw="the 41 Decimal(str(...)) call sites are in ..."
todo.py relto-add <id> note:0 --target=objid:0017
```

### Citing a note: `relto`, and what travels

A `relto` element is `{objid, type, target}` and lives on `Body`, on a note,
and on a WorkItem. A target is always namespace-qualified: `objid:<hex>` for
an object in this record, `todo:<hex>` for a todo, `todo:<hex>/objid:<hex>`
for an object in another todo's record. Full grammar:
[`IMPLEMENTATION.md`](IMPLEMENTATION.md).

**`Body.relto` is what publishes a note to descendants.** `prompt` emits the
notes reachable from a record's `Body.relto`, transitively through those
notes' own `relto`, and nothing else: a target naming a WorkItem or a subtodo
emits nothing, and a cross-todo target is never chased -- it prints a
one-line pointer so the reader knows the fact exists.

So a note only reaches a fresh agent if the Body points at it, directly or
through another note it points at. Point the Body at the facts an agent MUST
have; leave the rest cited from the WorkItem they bear on, where a reader
following that step will find them.

**Doctor owns the `mention` type.** It reconciles `mention` entries against
each node's own editable prose -- `Body.raw`, a note's `raw`, a WorkItem's
`summary` -- adding one for a target the prose names and dropping one for a
target it no longer names. Every other type is yours and doctor never touches
it. So writing `objid:0017` into a Body sentence IS citing it; the relation
appears on the next doctor run without being asked for.

**Prose that SHOWS the grammar writes a placeholder.** `objid:<hex>`,
`todo:<hex>`. A well-formed target in prose is a citation, so an illustrative
example spelled out as a real four-hex target derives a relation to an object
that was never meant to exist, and then stands as a dangling-target finding
that nobody can explain later.

## WorkItems carry their own detail

A WorkItem is where the specifics live: the files, the line anchors, the
per-step test obligations, the escalation triggers for that step alone. A
WorkItem may be long. Length in a WorkItem costs the reader of that one step;
length in the Body costs every reader and every descendant.

## An item that spawns a subtodo carries the child's spec

The WorkItem that will `add-subtodo` must contain what the child's `Body`,
`AC` and opening `WorkItems` get written FROM. Not a gesture at it -- the
actual material, because of the propagation rule below.

## The propagation rule that makes this layout load-bearing

`todo.py prompt <id>` is how a fresh agent with zero context starts. It emits,
for each ancestor farthest-first and the target last:

```
===== <Summary.raw> [<id8>] =====
<Body.raw>

===== note [objid:<hex>] =====
<the raw of each note Body.relto reaches>
```

**Summary, Body, and the notes the Body cites. Nothing else.** Not `AC`. Not
`WorkItems`. Not `LongSummary`. Four consequences, and they are the whole
reason for the split above:

| Field | Reaches a descendant's `prompt`? | So |
|-------|----------------------------------|-----|
| Parent `Body` | Yes, automatically | State architecture ONCE, in the highest Body that needs it. Never restate it in a child -- that is the repetition this rule exists to kill. |
| A note the `Body` cites | Yes, transitively | Write a finding once and point at it. A note no Body reaches is still readable (`note-read`, the web viewer) but does not travel. |
| Parent `AC` | **No** | A child expected to satisfy a parent criterion never sees it. Restate it into the child at creation (`add-subtodo --ac`), or put the binding constraint in the Body. |
| Parent `WorkItems` | **No** | The spawning item's text does not travel, and neither does a note cited only from a WorkItem. Its material must be COPIED into the child at `add-subtodo` time, not referenced. |

A Body that says "acceptance criteria live in the `AC` field" is therefore a
dead pointer from a child's point of view. Fine for a human reading one
ticket; useless to a subtodo. If children must obey a criterion, the criterion
goes in the Body or into their own `AC`.

## Detail vs creative freedom

Be specific where vagueness produces silent wrongness, and only there:

| Specify exactly | Leave to the implementing agent |
|-----------------|--------------------------------|
| Invariants whose violation is silent and unrecoverable | How to factor the code |
| The single choke point, when there must be exactly one | Test names, file layout, helper shapes |
| Constraints discovered at real cost (a hazard, a footgun already hit) | Ordering inside one WorkItem |
| The externally-fixed: schema shape, wire contract, ratified product call | Anything a competent agent does as well or better with local context |

Rule of thumb: **specify the constraint, not the method** -- unless the method
was itself the decision. Over-specifying method is how a plan ages badly: the
tree moves, the prescribed steps stop matching, and the agent follows the
stale instruction instead of the live constraint.

---
