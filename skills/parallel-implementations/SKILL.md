---
name: parallel-implementations
description: Run multiple implementations of the same task in parallel using worktree-isolated subagents
disable-model-invocation: true
---

When invoked, run N parallel implementations of a task, each in its own
isolated worktree. Arguments: `/parallel-implementations [N] [prompt]`

## Process

1. Parse arguments. If N or the prompt is missing, ask the user.
   Default N to 3 if not specified.

2. Check `git status`. If there are uncommitted changes, ask the user
   if they want to commit first (a clean checkpoint makes comparison
   easier).

3. Launch N subagents using the Agent tool. Each subagent gets:
   - `isolation: "worktree"` — its own copy of the repo
   - `run_in_background: true` — all agents run concurrently
   - A prompt that includes the user's task PLUS these instructions:
     "When you are done, copy your primary output file(s) back to the
     main project directory (the skill resolves the path at runtime)
     with a `-variant-{N}` suffix
     (e.g., `dashboard-variant-1.html`). This is critical — the
     worktree will be cleaned up after you finish, so files must be
     copied back to survive."

   Launch ALL agents in a single message so they run concurrently.

4. As agents complete, report progress to the user. When all are done,
   list the variant files in the main directory.

5. If the output files are HTML, open them in the browser for visual
   comparison. Present a summary table: which files each variant
   produced, line counts, and any notable differences.

6. Ask the user to pick a winner (or none). Rename the winner's files
   to their final names (remove the variant suffix). Delete the other
   variant files.

## Rules
- Always use `isolation: "worktree"` — never modify the main directory
  directly from a subagent
- Always use `run_in_background: true` — agents should run concurrently
- Each subagent must copy output back to the main directory as its
  final step — worktrees are auto-cleaned when agents finish
- If a subagent fails, report it and continue with the others
