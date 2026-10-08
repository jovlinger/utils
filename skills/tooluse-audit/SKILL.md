---
name: tooluse-audit
description: Audit Agent Skills for places where deterministic helper programs can replace or support agent judgment. Use when explicitly invoked to scan skill directories and write a tool-use improvement report, especially `/tmp/tooluse.md`.
disable-model-invocation: true
---

# Tooluse Audit

## Purpose

Audit skills for work that should be delegated to deterministic tools: parsing JSON/YAML/CSV, searching text, formatting code, listing files, querying APIs, counting matches, validating schemas, or generating repeatable summaries. The agent should focus on command, control, and judgment.

## Output

Write `/tmp/tooluse.md` with a markdown table:

```markdown
| Path | Score | Notes | What Can Improve |
|---|---:|---|---|
| path/to/SKILL.md | 4 | Short diagnosis. | Concrete helper command, script, or instruction improvement. |
```

Use one row per skill file. Score is an opportunity score:

- `0`: Already tool-forward and deterministic; no obvious improvement.
- `1`: Minor wording could make tool use more explicit.
- `2`: Some manual scanning/parsing could be replaced by commands.
- `3`: Repeated agent-heavy work should be supported by exact commands or scripts.
- `4`: The skill regularly asks the agent to do deterministic parsing, formatting, lookup, or aggregation manually.
- `5`: The skill's core workflow should be backed by a helper script, schema, or exact command sequence.

## Scan Procedure

1. Resolve scan roots from the user. If none are given, scan known personal and repo-local skill roots.
2. Find skills with:

```bash
rg --files <roots...> | rg '(^|/)SKILL\.md$'
```

3. Prioritize likely issues with targeted searches:

```bash
rg -n -i 'manual|by hand|inspect|parse|summari[sz]e|count|table|json|yaml|csv|logs|format|sort|filter|grep|search|query|diff|schema|validate|MCP|tool|script|jq|rg|gh|psql|pytest|black|ruff|pylint' <skill-files...>
```

4. Read each skill enough to judge whether the workflow gives deterministic commands or leaves routine work to the agent.
5. For each row, recommend the smallest useful improvement: an exact shell command, `jq` filter, `rg` pattern, validation script, formatter, API/MCP tool call shape, or report template.

## Review Heuristics

Look for these opportunities:

- "Use a tool" without exact invocation. Improve with command form, arguments, expected output, and failure handling.
- JSON/YAML/log parsing in prose. Improve with `jq`, `yq`, `rg`, or a checked-in helper script.
- Formatting instructions for code or docs. Improve with the project formatter command.
- File discovery by agent reading. Improve with `rg --files`, glob patterns, or known paths.
- Tables, counts, grouping, sorting, or deduplication. Improve with deterministic command pipelines or scripts.
- MCP/API workflows. Improve with the exact server, tool name, required schema-discovery step, and minimal arguments.
- Repeated multi-step workflows. Improve with a helper script that emits structured output for the agent to interpret.

Do not mark a skill down just because it uses agent judgment. The score should reflect missed deterministic support, not the inherent need for judgment.

## Final Response

After writing `/tmp/tooluse.md`, say how many skills were scanned, give the path to the report, and mention the highest-score themes. Keep the chat summary short.
