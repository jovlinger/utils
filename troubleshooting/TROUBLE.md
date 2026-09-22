TROUBLE
=======

        -or-

A lightweight expert system to be run by your agent or yourself.

# Audience

Human or agent.

# Glossary

1. Case: this is the base unit of this knowledge trove.
   Each case is one file in this directory with a semi-structured name.

1.1. Case file naming.
   Each starts with CASE (case insensitive, uppercase preferred), and then a very brief symptom or at least a problem area.
   Prefer to avoid spaces to simplify quoting.
   If several cases want the same title, disambiguate by adding a suffix.
   For example, digits of pi or zoo animals are as valid as incrementing a counter.
   Example: `CASE:update_ecr_images_dies.1.md`

   Case filenames are the first-pass index. They should usually be sufficient for a quick scan.
   
1.2. Case contents.
   A case begins with cheap metadata lines (see `_CASE:template.md`):

   - `Summary:` one sentence describing the failure mode.
   - `Keywords:` a short comma-separated list using stable categories.

   Scan metadata with:

   ```sh
   rg -i "^(Summary|Keywords):" ./troubleshooting
   ```

   A case also has two mandatory sections starting in markdown single-# format: `# Symptoms` and `# Solutions`.
   (we accept any unambiguous synonym of these, including singular versions, e.g. `# Trigger` / `# Response`)
   These two sections should be comprehensible by an engineer, but targeted at machine consumption.
   These sections are preferably last. They may be preceded by human-targeted discussion.
   There may be a final section on `# Solved` to discuss post-resolution steps.
   
1.3. Case symptom imprecision.
   There is no expectation that symptoms are unique: a given error may ambiguously match several symptoms.
   The hope is that as we encounter more and more situations, these cases will be edited to more precisely target solutions to their symptoms.

1.4. Case solution.
   The solution should be clear without major deviations.
   Negative example: "if you are on Linux, reformat your hard drive; if you are on Windows, play minesweeper."
   If two solutions are very different, clone the case and put Linux and Windows as symptoms.
   Small deviations and details are expected and allowed (let PROJ_DIR be the parent directory holding your opportunity checkout
   **or** if this is a secondary checkout of the repository, watch out for $OPP_DIR being set to the primary location).


# How to use this knowledge trove

1. You will be here because you have experienced an error.
   If this happened in a terminal, capture the last few pages of terminal state and use that for pattern matching against the trove.
   Some commands log to `/tmp` using structured names, for example: `/tmp/gen_db_image.2026-02-03T15-17-21-336606.txt`.
   (Note the RFC3339 name; we also generate manifests with similar names, except for the `_manifest_YYYYMMDDhhmmss.txt` ending.)
   If this log is from the time period of the error and contains errors, it is likely a good source of symptoms.

   We hope that CASE:filenames will suffice, but you may need to read the files themselves to extract the `# Symptoms` section.
   
2. If the symptoms match, apply the solution

3. Optionally note any tips on how to determine whether the problem is `# Solved`, and tweak the instructions to target symptoms more accurately.
   Especially important are negative symptoms to help avoid solutions that don't work.

4. Write, don't just read. The moment you (human or agent) confirm a fix for a problem that took
   real diagnostic effort, is likely to recur, or would otherwise force someone else to re-derive
   the same diagnosis, add a new CASE. Do this proactively -- don't wait to be asked "write this
   up" or "record this." Start from `_CASE:template.md`, follow the naming/contents rules in the
   Glossary above, and land it on its own branch/PR: a case is docs, not code, so don't bundle it
   into an unrelated feature/ticket branch.


