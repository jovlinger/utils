# RECIPE: Research spike (ResearchSpike)

Research spikes produce **insight artifacts** (documents, analysis, methodology),
not runnable code. The todo structure adapts: WorkItems become discrete research
tasks, and acceptance criteria measure understanding rather than functional
correctness.

## When to use

- Investigating a domain, market, or technology before committing to a design.
- Collecting and synthesizing data from multiple external sources.
- Producing a summary document that a future agent or human can extend.
- The primary deliverable is written analysis, not a working system.

Do NOT use for implementation work disguised as research. If the end goal is
merged code, use the normal `todos` lifecycle with research WorkItems as
precursors to implementation WorkItems.

---

## How research spikes differ from programming / SW engineering design

| Dimension | Programming / Design | Research spike |
|-----------|----------------------|----------------|
| **Primary deliverable** | Runnable code, tests, merged PR | Document (markdown, spreadsheet), methodology notes, raw data archive |
| **WorkItem granularity** | One reviewable commit (~50-200 LOC delta) | One discrete research question or data-gathering step |
| **Acceptance criteria** | Tests pass; linter clean; behavior matches spec | Question answered with cited evidence; methodology documented for reproduction |
| **Done signal** | `is-done` via last code WorkItem | Summary document exists and answers the original questions |
| **Blocking condition** | Compile/test failure, API gap | Inaccessible data source, paywalled content, ambiguous question |
| **Merge semantics** | Git merge of branch into parent | Document committed to repo (or handed off out-of-band); no functional integration test |
| **Capability tier default** | MIDCAP (pattern-following code) | MIDCAP (data gathering); HICAP (synthesis, ambiguous interpretation) |

### Structural guidance

1. **WorkItems are research tasks, not code commits.** Each item should answer a
   single question, scrape a single source, or produce a single data artifact.
   Mark them done with `--checkpoint` (no code change) or commit the resulting
   document fragment.

2. **Synthesis is explicit.** Reserve a final WorkItem (often `[HICAP]`) for
   combining the gathered data into the summary deliverable. Do not treat
   synthesis as implicit -- it is the most judgment-heavy step.

3. **Methodology is a deliverable.** Research spikes should leave behind enough
   process documentation that a MIDCAP agent can replicate or extend the work
   to new markets, sources, or parameters without re-deriving the approach.

4. **External sources need provenance.** For each data point, record source URL,
   access date, and any rate-limit or authentication notes. A future extension
   must know where the numbers came from and whether the source is still accessible.

5. **Blockers surface early.** If a required data source is paywalled, requires
   credentials, or returns inconsistent data, surface via `userneeded` before
   burning tokens on workarounds the user may not want.

---

## Shape

### Grooming outputs (before `init`)

| Output | Research spike adaptation |
|--------|---------------------------|
| `Summary.raw` | The research question(s) in human terms |
| `Body.raw` | Context, motivation, known constraints, pointers to prior art |
| `AC` | Concrete questions that must be answered; deliverable format (e.g. "markdown table with columns X, Y, Z") |
| `Scope` | Repository path where deliverable lives; may include external URLs as context |
| Tiered WorkItems | One per data source or sub-question; synthesis item at the end |

### WorkItem kinds for research

| `kind` | Use |
|--------|-----|
| `checkpoint` | Pure research step: reading, querying, summarizing -- no code artifact |
| `code` | Committing a document fragment, data file, or script that collects data |
| `start_subtodo` | Fan-out to parallel research domains (e.g., different geographic markets) |

### Example WorkItems sequence

```text
[MIDCAP] Collect Zillow listing data for Harwich Port MA (10 properties)
[MIDCAP] Collect VRBO seasonal rate data for Harwich Port MA
[MIDCAP] Collect comparable purchase prices from public records
[MIDCAP] Repeat data collection for Little Sebago ME
[MIDCAP] Repeat data collection for Location 3
[MIDCAP] Repeat data collection for Location 4
[HICAP] Synthesize summary table: purchase price vs expected rental income
[MIDCAP] Document methodology for extension to other markets
```

### Deliverable structure

Research spike deliverables typically include:

1. **Summary table** -- the main finding, formatted for quick consumption.
2. **Background / context** -- domain knowledge needed to interpret the table.
3. **Methodology** -- step-by-step process a future agent can follow.
4. **Raw data appendix** -- the underlying numbers, with provenance.
5. **Limitations / caveats** -- what the analysis does not cover.

---

## Data collection guidance

### Web scraping / headless browsers

- Prefer structured APIs (Zillow API, MLS feeds) when available.
- For scraping, document rate limits and robots.txt compliance.
- Use `playwright-mcp` or `bun` headless for JavaScript-heavy sites.
- Cache responses locally to avoid re-fetching during iteration.
- Record access timestamps -- real estate data changes daily.

### Public data sources (examples)

| Domain | Sources |
|--------|---------|
| Property values | Zillow, Redfin, county assessor records, MLS (if accessible) |
| Rental income | VRBO, Airbnb (via AirDNA or scraping), local property managers |
| Costs | Insurance quotes, mortgage calculators, property tax records |
| Comparables | "Similar properties" features on listing sites; manual radius search |

### Handling missing or inconsistent data

- Record what was NOT found, not just what was found.
- Note discrepancies between sources (e.g., Zillow estimate vs actual sale).
- If a critical source is inaccessible, surface via `userneeded` with options.

---

## Finishing a research spike

1. **Commit the deliverable document** to the repository at the path in `Scope`.
2. **Mark synthesis WorkItem done** (`work-item-done <id>` with the commit sha).
3. **`is-done`** should now return true.
4. **Set state done** with `--actual-summary` describing what was learned.
5. **Worktree teardown** per normal `WORKING.md` section 6.

The deliverable document is the durable artifact. Chat summaries and WorkItem
messages are pointers; the document stands alone.

---

## Parallel research subtodos

When a research spike covers multiple independent domains (e.g., four geographic
markets), consider parallel subtodos:

- Each subtodo covers one market / data source.
- Parent's AC is "all subtodos done + synthesis document exists."
- Synthesis WorkItem lives on the parent, not the children.
- Use `add-subtodo` for tracked children that produce their own branch artifacts.

This is one of the cases where parallel fan-out is authorized by grooming policy
(genuinely independent context-heavy domains). Still requires explicit user
approval or grooming authorization per `GROOMING.md`.

---

## Anti-patterns

| Anti-pattern | Why it fails |
|--------------|--------------|
| Treating research as unbounded exploration | No AC means no done signal; burns tokens indefinitely |
| Skipping methodology documentation | Future extension requires re-deriving the process |
| Mixing implementation code into a research spike | Confuses deliverables; use separate todos |
| Leaving raw data uncommitted | Provenance lost; cannot reproduce or verify |
| Synthesis without explicit WorkItem | Judgment step is skipped or rushed |

---

## Related

- `todos` SKILL.md -- the parent lifecycle this recipe adapts.
- `GROOMING.md` -- capability tiers, WorkItem vs subtodo decisions.
- `WORKING.md` -- operational runbook (finish/teardown applies unchanged).
- `RECIPE:retrofit-from-pr.md` -- different recipe for capturing already-done work.
