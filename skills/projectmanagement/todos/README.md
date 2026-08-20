# Todos

**TL;DR:** the by formalizing an agentic workflow (typically a programming or research task) into a structured object that
captures both state and supporting information, the command-line tool `todo.py` can effectively coordinate agents of
various capabilities, managing the information that each needs to do its task.  In turn, the intiating agent draws upon
a skill to use the todo tool.


## context

This is the (for me) logical end point of a note-taking tool-aided skill, and simultaneously an experiment in how to
integrate agents of various capabilities.  We have a choice of agents of various capabilities, in general on a spectrum
from smart and slow (Fable) to fast and stupid (Haiku).  At the very far end, there are plain programatic tools, like
grep and find.  This project has served as a case study of where to draw the line between smart agent, fast agent, and
tool (CLI command, normally), and how to integrate them.

I needed a low-interface tool to capture "let's work on this later" with minimal required context switch from the task
at hand. 

## What it became

A `todo` is a managed, structured, memory; managed by the `todo` tool. 
It supports facts for agentic read-write recallable memory, 
but the main use case is tool-managed workflow for coding and research tasks. 

It allows a high-capability (HICAP) agent (e.g. Claude/Fable) to create a durable implementation plan, which the user
can read and approve.  When it is in a good state, a MIDCAP agent can implement the plan, recording its progress in a
series of fine-grained steps. 

These steps are recorded as small-step git commits, that the todo tool captures and presents to the user in a web viewer. 
This provides observability into the development process. 

This is a hybrid system, where the agent uses a skill it interact with the tool - in effect treating the CLI tool
analogously to how python's C-FFI allows calls into a efficient language for constrained computational tasks.  The HICAP
agent uses the `todo` tool to build the document, and the implementing MIDCAP agent uses the tool to iterate through
steps to implement the solution.  At the end, the HICAP agent also reviews the results. 

This arrangement allows the highest impact for expensive tokens, and provides a backstop for lesser, 
cheaper agents' output to be verified against a written goal. The tool is mechanism, the agent is policy. 

Todos as tool-assisted PLAN.md work well.

## What is not yet there.

But the associative memory of fact-based todos to allow an agent to ask itself "what do I know about ESP32 controllers"
is not quite ready yet.  The facts are meant to be associatively retrievable via cosine angle vector embeddings, but I
put all my eggs into Apple's NLContextualEmbedding.  That was a very poor choice, as all vector-embeddings compressed
into a very narrow region, yielding no differentiation between very different search terms.

I'm searching for an effective embedder that can be easily installed locally. 

---

# Details

## Multi-agent roles

Todos are built for a split workforce, not one monolithic session.

| Role         | Who               | Job                                                                                             |
|--------------|-------------------|-------------------------------------------------------------------------------------------------|
| Groomer      | HICAP (sparingly) | Mint (create), decompose, write AC/Body/LongSummary, tag tiers, decide subtodo vs WorkItem      |
| Worker       | MIDCAP / LOCAP    | Execute one WorkItem at a time on the todo branch in a dedicated worktree                       |
| Orchestrator | Parent context    | Bookkeeping, child launch, synthesis after merge -- not necessarily the same model as the child |

The todo is a structured document, much like a highly worked jira ticket. With subtodos, sequence of steps to be worked
on this todo (both implementation and fork/join of subtodos), acceptance criteria, status, and also summary for parent
Todo (if any) to report in /its/ join step. 

**Capability tiers** Every piece of work is tagged with what level agent should implement it.  (`[HICAP] (Fable)`,
`[MIDCAP] (Opus/Sonnet)`, `[LOCAP] (Haiku)`) In general: planning and reviewing is HICAP, implementation is MIDCAP, and
reporting is LOCAP.

**Independent work** Once groomed (again, ticket analogy), a todo should be self-contained. The reason we burn HICAP
tokens for this is to predict questions that might arise during implementation and answer them proactively.

**Nested work** A todo can have a number of steps (WorkItems) that are inherently sequential.  One kind of WorkItem is
to spawn a sub-todo. Subtodos are conceptually independent, like subprocesses, and can run concurrently with the other
subtodos and the parent.  Often they are not. This is up to the instructions in the todo.  The spawn can specify
parallel (multi-processing) or sequential (sub-routine) behavior.  In all cases, the child is started with a prompt
generated by the tool, by combining the chain of parents' descriptions to give context. 


---

## Observability through frequent commits

The todo tool provides programmatic support to the agent so that its context can remain sparse. 
The tool logs all actions it takes, but this is mechanism, and doesn't much tell us about the agents' thoughts. 

To enable observability into agents' behavior, we rely on git.  After every step of implementation (so called WorkItem),
the implementing agent commits that step's work, records the SHA, and (for convenience) duplicates the commit message
into the WorkItem.  This allows the web UI to display a detailed log of the agent's actions. 

Each **WorkItem** is one of 4 kinds, and goes from a textual description to a structured result.

| kind            | records                                                               |
|-----------------|-----------------------------------------------------------------------|
| `code`          | a real commit (`work-item-done` captures branch HEAD + `-m` message)  |
| `checkpoint`    | a no-code step finished (`--checkpoint`, observational `at_sha`)      |
| `merge_subtodo` | child integrated on the parent branch (after **your** `git merge`)    |
| `start_subtodo` | child registered (`add-subtodo`)                                      |

The [`frequentcommits`](../frequentcommits/SKILL.md) policy goes into more detail. 

---

## Related todos

The most common use case for a relation between todos is parent/sub todos, which correspond to an asynchronous delegation
of implementation responsibility.  There can be other relations as well, such as the "these are related, but have
independent implementations".  Because foolish consistency is a hobgoblin, this info link is mapped as a parent/info
relation.  (we would be better served to allow both sides full freedom of naming the link). 

| Mechanism      | Merge obligation                                    | Use                                  |
|----------------|-----------------------------------------------------|--------------------------------------|
| `add-subtodo`  | yes -- git merge child branch, then `merge-subtodo` | tracked child work on its own branch |
| `set --parent` | no -- INFO backlink only                            | follow-only context link             |

The main difference is that the parent/info link is purely informational.  It does not imply any merge or orchestration. 
The parent/child subtodo however has a strong orchestration requirement, captured in the start/merge_subtodo actions.

---

## Viewer

`todo.py web [selector]` serves a local viewer (default `localhost:8765`). 
This allows a rudimentary URL-based (as opposed to Single Page App) browser for todos. 

```
http://localhost:8765/<todoid>/objid/<objid>
```

Each location in the todo has a perma-url, allowing the agent to post deeplinks into the todo for discussion and reference to
other agents.  (the cli tool is able to resolve these urls for agents without the web server running). 

---

## Management search

`todo.py search <terms...>` ranks the corpus for grooming, resume, and
associative memory ([`MEMORY.md`](MEMORY.md) -- policy for what to store is still
being written).

**Ranking** Should fuse two independent rankers (reciprocal rank fusion):

1. **Lexical IDF** -- always on. Tokenize fresh each search (cheap); IDF-weight
   full-text with discovered stopwords in `<todo-dir>/config.json`. Rare terms
   dominate; corpus-wide words are skipped unless the whole query is stopwords.
   This half works everywhere, offline, in CI.
2. **Vector embedders** -- when available. Default set is `apple`
   (NLContextualEmbedding sidecar on macOS 14+). Vectors backfill lazily on
   first search; nothing is computed on write (no `cheap` embedder since `hash`
   was retired).

But the apple embedder was a bust, so we are searching using a fairly naive IDF with stop words and basic stemming. 
This is insufficient for zero-shot tagging, which was supposed to be the killer feature of the embedder. 

Bah.


---

## Quick start

```bash
TODO=skills/projectmanagement/todos/todo.py

ID=$("$TODO" mint)
"$TODO" set "$ID" --summary="..." --body="..." --ac="..."
"$TODO" init --id "$ID" --stay-on-parent

# in the todo worktree:
"$TODO" prompt "$ID"
"$TODO" set "$ID" --state working
"$TODO" work-item-read "$ID"
# ... edit, commit ...
"$TODO" work-item-done "$ID" -m "why-per-file detail in the message"
```

Print resolved store path: `todo.py basedir`. List tickets: `todo.py ls`.
Doctor before finish: `todo.py doctor <id>`.

---

## Regrets, Apologies

The command language for the tool has clearly evolved, and could stand a re-design.  Luckily, the only consumer is the
SKILL, which lives in the same repo, so we are able to atomically upgrade both.  

As implemented, this is single-user. Not inherently, but there is no REST backend.  But this is not really meant to replace team-work tools. This is just a private repository and a mechanism for managing implementation workflow and retrospective observability.
