# Merged review: `skills/projectmanagement/todos/SKILL.md`

status: **HISTORICAL** -- the review that motivated the split, kept for its
rationale. Every `SKILL.md:Lnnn` citation below points into the 1,384-line
monolith that no longer exists; the line numbers are evidence of what was
wrong, not a map of anything current. The documents it proposed are now
[`SKILL.md`](../SKILL.md) (router), [`GROOMING.md`](../GROOMING.md),
[`WORKING.md`](../WORKING.md), and
[`IMPLEMENTATION.md`](../IMPLEMENTATION.md) -- read those for current
behavior. Not an agent-facing procedure; nothing routes here.

This is the GPT synthesis of two independent reviews: a GPT review and a Grok
review. Both evaluated the same current document in isolation before this
merge. They agree that the content is valuable but the 1,384-line monolith is
too large and internally inconsistent to remain the sole agent-facing skill.

## Consensus at a glance

| Dimension | GPT | Grok | Merged assessment |
|---|---:|---:|---|
| Usability for agent dispatch | 2/5 | 2/5 | 2/5 |
| Future evolution | 2/5 | 2/5 | 2/5 |
| Duplication control | 1/5 | 2/5 | 1.5/5 |
| Internal consistency | 1/5 | 2/5 | 1.5/5 |
| Navigability | 2/5 | 2/5 | 2/5 |
| Actionability | 2/5 | 3/5 | 2.5/5 |

**Decision: split it.** Keep `SKILL.md` as a <=200-line trigger/router and add
top-level sibling documents (not a nested `docs/` directory, to avoid
skill-discovery depth issues):

1. `GROOMING.md` -- create, clarify, size, and dispatch tickets.
2. `WORKING.md` -- the one normative runbook from worktree entry to handoff.
3. `IMPLEMENTATION.md` -- CLI contract, storage, schema, migrations,
   permalinks, doctor, compatibility, and planned features.

The entry skill should load only the safety rules, a compact domain model, a
few everyday commands, and an intent router. Each rule must have one normative
owner; other documents link to it instead of restating it.

## Author feedback incorporated after review

The SQLite and `.todo/storage` backends are product features, not concepts a
working agent normally needs. The dispatch skill should treat backend selection
as opaque: agents use `todo.py`, while the implementation reference owns the
backend contract and maintainer details.

Repository-local storage is supported, but it is a **very strong
anti-pattern** when its files are versioned beside the work: ordinary ticket
writes then create unrelated repository changes and merge pressure. This is a
warning and design concern, not a prohibition -- legitimate workflows may need
versioned local storage. The tool should be considered for a prominent warning
on every invocation when the resolved backend is inside the repository and is
not ignored; a future warning must identify the resolved path and explain the
intermingling risk without blocking the command.

## Additions from the independent Grok review

The detailed review below already establishes the primary migration map and
acceptance criteria. The second review independently identified these further
requirements, which the implementation must include:

- Reconcile concurrency with a precedence rule: work sequentially by default;
  parallel subtodos require an explicit user request or genuinely independent,
  context-heavy research. Rewrite "often one subagent each" so it does not
  override the default.
- Remove the Claude-only `/rewind` mandate. Preserve the durable-state
  principle while allowing the host agent to shed context by its own mechanism.
- Repair the incomplete WorkItem invariant numbering: define #2 and #4, and
  keep lifecycle and doctor references synchronized.
- Place every operational command in the implementation reference. In
  particular, add referenced `web` and `export-to-file` commands if they are
  implemented, and visibly separate the `ensure_worktree` stub from the manual
  worktree procedure.
- Do not place current agent-facing procedures below a nested `docs/`
  directory. Keep the three new documents adjacent to `SKILL.md`, then link
  them from the router.

## Implementation order

1. Verify every claimed command, state, and field against `todo.py` and its
   tests before copying it into the new current-contract documentation.
2. Create the three siblings and move content by ownership: grooming policy,
   working runbook, and implementation reference.
3. Resolve the correctness issues in the owning document, then remove all
   duplicate normative prose.
4. Replace `SKILL.md` with the compact router and safety card.
5. Validate links and examples, and confirm each intent path can be followed
   without loading unrelated mechanism or history.

The document below is the GPT review that supplied the line-level evidence,
migration map, and acceptance criteria; it is retained as the detailed merged
plan.

## Verdict

Split it. Keep `SKILL.md` as a short dispatch entry point, then move the
normative material into three documents:

1. `grooming.md` -- creating and decomposing a ticket.
2. `working.md` -- operating a ticket safely from start through handoff.
3. `implementation.md` -- CLI, storage, schema, migrations, and deferred design.

The current 1,384-line skill is simultaneously a trigger, agent policy,
runbook, CLI reference, schema specification, implementation diary, and
roadmap. That makes it expensive to load and difficult to execute reliably.
More importantly, duplicated lifecycle rules have drifted into contradictions.
The split should establish one normative owner for every rule rather than copy
the same rule into each new document.

## Scorecard

Scores use 5 = excellent and 1 = unsafe or unusable without substantial
interpretation.

| Dimension | Score | Evidence |
|---|---:|---|
| Usability for agent dispatch | 2/5 | The trigger promises that the "full workflow, CLI, and schema" load together (`SKILL.md:L3-L10`), while the authoritative driver loop does not appear until `L1193-L1276`. A dispatched agent must traverse storage, migrations, all commands, permalinks, and schema details before reaching the operational loop. |
| Future evolution | 2/5 | Current behavior, future sketches, historical notes, and deferred work share the same level: a stub is in the command table (`L354`), worktree automation is "future" (`L1141-L1147`), notification designs are speculative (`L1114-L1124`), and deferred features are mixed into current state/schema (`L829-L830`, `L1369-L1383`). The stale "Coming" note at `L1337-L1340` describes objids/permalinks that are already documented as present at `L417-L497` and `L785-L804`. |
| Duplication control | 1/5 | The no-direct-JSON rule appears at `L8-L10`, `L332-L337`, and `L675-L689`; explicit selectors at `L21-L23`, `L342`, `L384-L396`, `L671-L673`, and `L759-L764`; creation at `L341-L353`, `L725-L759`, and `L1199-L1208`; worktree policy at `L499-L647`, `L649-L669`, and `L1203-L1207`; finishing at `L1239` and again at `L1244-L1258`. |
| Internal consistency / contradictions | 1/5 | The document alternately defines the store as shared `.todo/` with `TODO.json` import-only (`L18-L23`, `L252-L278`) and as a branch-local `TODO.json` (`L33-L34`, `L167-L169`, `L513-L515`, `L639-L640`, `L766-L769`). Other operational contradictions are listed below. |
| Navigability | 2/5 | Headings help locally, but closely related normative rules are far apart: subtodo operation spans `L69-L201`, `L991-L1124`, and `L1231-L1269`; worktree setup spans four sections. There is no contents/routing table and no quick path by user intent ("make", "work", "resume", "finish", "handoff", "inspect"). |
| Actionability | 2/5 | Many commands are concrete, but key sequences are incomplete or disagree. The authoritative finish sequence omits mandatory worktree teardown (`L1244-L1258` versus `L593-L600`), and `wait-and-merge` can be read as replacing the required git merge (`L82-L83`, `L370-L371`, `L1104-L1112`, `L1234-L1238`). |

Overall: **1.7/5**. The content contains substantial useful operational
knowledge, but its current structure does not provide a single safe execution
path.

## Highest-priority correctness issues

### 1. Keep storage backend opaque; remove branch-local `TODO.json` language

The opening model says records live in a shared store and legacy `TODO.json` is
import-only (`L18-L23`). Storage and placement repeat that model
(`L252-L278`, `L499-L508`). In conflict:

- "CWD is a TODO branch" requires `gitroot` to hold `TODO.json` (`L33-L34`).
- Subtodos are described as branches "with their own `TODO.json`"
  (`L165-L169`).
- The lifecycle says "`TODO.json` lives with the branch" (`L513-L515`).
- Worktree discovery again relies on `TODO.json` (`L639-L640`).
- Record shape says one ticket per `TODO.json` (`L766-L769`).

Precise change: make "ticket record addressed through `todo.py`" the agent
model; do not expose SQLite or json-dir backend details in the dispatch skill.
The implementation reference may define the resolved-store contract and
backend features. Replace every current-tense `TODO.json` statement with
store terminology, and put legacy import behavior in one boxed compatibility
note. Do not teach agents to infer ticket presence from a file.

Repository-local versioned storage deserves a loud anti-pattern warning, not a
ban: it intermingles ticket churn with working-tree changes, but it remains a
supported feature for intentional workflows. A future per-invocation tool
warning should name the resolved path and explain the risk whenever that
condition is detected.

### 2. Make the worktree lifecycle executable end to end

Terminal states supposedly require removal of the live worktree
(`L586-L600`), and the state table says entering `done` tears it down
(`L825-L827`). However, `set` is explicitly store-only (`L357`), and the
authoritative finish sequence ends immediately after `set ... --state done`
(`L1244-L1258`). Thus the documented sequence necessarily leaves an invariant
violation.

Precise change: in `working.md`, define one finish procedure:

1. In the todo worktree: verify clean tree, `is-done`, `doctor`, and
   `last-sha`; synthesize `ActualSummary`.
2. Save the worktree path and leave it.
3. Set terminal state through the CLI.
4. Remove that exact worktree and verify it no longer appears in
   `git worktree list`.
5. Perform branch handoff/retirement only under its separate gate.

Clarify whether state transition occurs before or after removal and what to do
if either half fails. The same procedure should be linked, not restated, by the
state and lifecycle references.

### 3. Disambiguate `wait-and-merge` from an actual git merge

The hard rule requires the child branch to be merged before
`merge-subtodo` bookkeeping (`L76-L83`), and the dispatch table says
"git-merge the child, then `merge-subtodo`" (`L1231-L1235`). Yet
`wait-and-merge` is described as polling and then running merge bookkeeping
(`L370-L371`, `L1104-L1112`), while the blocked-child dispatch offers it without
an explicit git merge (`L1238`).

Precise change: verify the implementation, then document one of these contracts
unambiguously:

- If it performs git integration, name the checkout, target branch, merge
  strategy, conflict behavior, and post-merge verification.
- If it only waits and updates records, say **it does not merge git branches**
  wherever the command is introduced, and rename it in a later compatibility
  change to avoid implying otherwise.

Until then, `working.md` should require explicit git integration and
verification before any merge-bookkeeping command.

### 4. Resolve command-signature drift for subtodo creation

The command table specifies
`add-subtodo <parent> --from-json=...` (`L355`), while the lifecycle dispatch
uses `add-subtodo <parent-id> --summary=...` (`L1233`), and the normal loop
provides neither seed form (`L85-L90`). These are not interchangeable examples
for an agent.

Precise change: put the complete, verified invocation in the implementation
reference. In grooming/working docs, link to that syntax and show exactly one
minimal valid example. If both seed modes are supported, list both explicitly
with required fields.

### 5. Stop hard-coding `master` after declaring multiple defaults

Placement allows `master`, `main`, or `dev` according to repository default
(`L501-L505`), but the verification procedure repeatedly requires literal
`master` (`L550-L568`, `L580-L585`, `L651-L660`). This makes the "hard rule"
wrong for repos whose default branch is `main` or `dev`.

Precise change: define `DEFAULT_BRANCH` once from a reliable local/remote
source, with an explicit fallback and error case. Every check should compare
against that value. Avoid prose saying "master" when the invariant is "the
repository's configured default branch."

### 6. Replace stale or invalid schema examples

- The minimal skeleton uses `State: {"init": {}}` (`L1342-L1358`), but `init`
  is documented as the former name of current `ready` (`L818-L822`) and is not
  settable (`L840-L855`).
- The same skeleton includes `Scope.path_to_project` (`L1351-L1353`), while
  migration v6 says that field is stripped (`L291-L294`); the Scope table then
  advertises it again (`L943-L952`).
- WorkItem examples use an `id` field (`L1056-L1083`), while every nested
  object is required to carry `objid` (`L785-L804`) and unknown fields are to
  be rejected (`L771-L773`).
- "Coming" objids/permalinks (`L1337-L1340`) contradicts the current permalink
  and objid sections (`L417-L497`, `L785-L804`).

Precise change: generate or validate examples against the current schema in
documentation tests. Delete historical field names from current examples.
Move migration history to `implementation.md` and label it historical.

### 7. Put destructive branch retirement behind a verifiable gate

The branch-retirement section recommends `git branch -D` based on work being
merged, cherry-picked, or having "equivalent-content absorption"
(`L605-L621`). The last condition is not mechanically defined, and force
deletion is presented as a routine consequence.

Precise change: separate worktree teardown (reversible) from branch deletion
(destructive). Require explicit handoff evidence recorded on the ticket, a
clean worktree, a pushed durable ref where applicable, and explicit user
authorization before force-deleting a branch. Specify that remote deletion is
out of scope unless separately requested.

## Proposed document architecture and migration map

### `SKILL.md`: trigger and router only (target: 120-180 lines)

Retain:

- Frontmatter and trigger semantics from `L1-L12`, rewritten to say that
  detailed references are loaded on demand.
- A corrected six-line domain model distilled from `L18-L49`.
- Non-negotiable safety rules: CLI-only ticket access, explicit selector,
  resolved-store model, dedicated worktree for code work, and no parent
  completion before tracked children are integrated.
- An intent router:
  - make/groom/plan/decompose -> `grooming.md`
  - start/resume/work/wait/finish/handoff -> `working.md`
  - command/schema/storage/migration/debugging -> `implementation.md`
- A five-command quick start that links to the authoritative working flow.

Remove all full command tables, schema field tables, implementation history,
future sketches, and duplicated lifecycle prose from the entry point.

### `grooming.md`: ticket design and dispatch policy

Move and reconcile:

- Two-phase make-versus-work semantics: `L711-L759`.
- Summary, Body, AC, and Scope requirements: `L943-L962`, after resolving
  `path_to_project`.
- Subtodo versus WorkItem decision policy: `L101-L110`, `L165-L201`, and
  `L1266-L1269`.
- Capability tiers and escalation: `L203-L250`.
- Work-plan editing policy (not low-level field syntax): `L1126-L1139`.

Add:

- A single decision table: local WorkItem vs sequential subtodo vs parallel
  subtodos.
- Required grooming outputs: Summary, Body, AC, Scope, tiered WorkItems, child
  independence/integration plan, and unresolved user decisions.
- A "ready to init" checklist. Keep CLI syntax linked to
  `implementation.md` rather than duplicated.

The sequential-default rule (`L101-L110`) must be the top-level default.
Parallel examples (`L171-L191`) and the HICAP fan-out language (`L246-L250`)
must be explicitly subordinate exceptions, not competing defaults.

### `working.md`: one normative operational runbook

Move and reconcile:

- Startup context and parent linkage needed by workers: `L129-L163`.
- Recursive completion rules: `L69-L99`.
- Corrected worktree setup/teardown and branch handoff:
  `L499-L647`.
- The authoritative lifecycle and dispatch loop: `L1193-L1276`.
- Chat/result reporting: `L1278-L1335`.

Organize by operator intent:

1. Start or resume.
2. Poll and execute one WorkItem.
3. Split/delegate.
4. Wait and integrate child work.
5. Handle `userneeded`/`stopped`.
6. Finish and remove the worktree.
7. Handoff to parent or PR.
8. Report the result.

There must be exactly one normative command sequence for each operation.
Other documents should link to anchors in this runbook. Move the explanatory
"why main stays..." material (`L517-L529`) to a short rationale after the rule,
not before the commands.

### `implementation.md`: mechanism and maintainer reference

Move:

- Store resolution/layout: `L252-L278`.
- Schema migrations and startup health checks: `L280-L321`.
- Full CLI reference: `L323-L382`.
- Selectors/path primitives and permalinks: `L384-L497`.
- JSON access mechanics and id generation: `L675-L723`.
- Record schema, state metadata, PR reconciliation, filters, embeddings,
  objids, and WorkItems: `L766-L1124`.
- Doctor checks: `L1149-L1191`.
- Corrected minimal schema example: `L1342-L1358`.
- Related/deferred work: `L1361-L1383`.

Separate this document internally into:

- **Current public contract** -- commands and record schema agents may rely on.
- **Maintainer internals** -- DSN resolution, migration registry, embedding
  behavior, health detection.
- **Compatibility/history** -- legacy `TODO.json`, renamed fields/states.
- **Deferred proposals** -- clearly non-normative and absent from current
  schemas/command tables.

Do not put planned commands or states in current tables. Use separate
"planned" tables so `STUB`, `deferred`, and implemented behavior cannot be
mistaken for equivalent capabilities.

## Precise editing plan

1. Freeze terminology: **ticket**, **record**, **resolved store**, **todo
   branch**, **todo worktree**, **tracked subtodo**, and **INFO backlink**.
   Define each once; eliminate "ticket file" and current-tense `TODO.json`.
2. Create the three destination documents with stable anchors, then move
   sections without rewriting behavior.
3. Deduplicate by assigning an owner:
   - lifecycle/worktrees/subtodo integration -> `working.md`
   - decomposition/model targeting -> `grooming.md`
   - exact command/schema/storage behavior -> `implementation.md`
4. Resolve the seven correctness issues above against the implementation and
   tests before shortening the router.
5. Replace repeated prose in non-owning documents with a one-sentence link.
   In particular, JSON access, selector rules, creation, worktree checks, and
   finish rules each need one normative source.
6. Add an implementation-backed documentation check for:
   - command names/options shown in fenced shell blocks,
   - current state names and metadata flags,
   - JSON examples against the current record validator,
   - links/anchors among the four documents.
7. Add a short "current versus planned" lint rule or review checklist:
   planned/stub/deferred features cannot appear in current dispatch tables.
8. After migration, read each intent path independently. An agent responding
   to "make a todo" should need the router plus `grooming.md`; an agent
   responding to "work todo X" should need the router plus `working.md`;
   neither should load migration internals or embedding incident history.

## Acceptance criteria for the restructure

- The entry skill is under 200 lines and routes by intent.
- Every current operational rule has one normative owner.
- No current section says a branch/worktree contains `TODO.json`.
- The documented start, child-integration, finish, and PR-handoff paths are
  complete command sequences with no missing side effects.
- All command examples match the implemented parser.
- All JSON examples validate against the current schema.
- Current, compatibility, and deferred behavior are visually and structurally
  distinct.
- A repository using `main` or `dev` as its default branch can follow the
  worktree checks without editing commands.
