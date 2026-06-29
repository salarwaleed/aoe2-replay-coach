---
name: verify-pipeline-stage
description: Use after any data-pipeline stage (ingestion, transformation, synthesis, an ETL job, a batch script) reports success, before marking that stage done or moving on to the next stage that depends on it. Independently confirm what actually landed in the resulting datastore rather than trusting the stage's own summary or log output. Trigger whenever a pipeline run finishes, a "X chunks processed" or "Y items written" summary is printed, or before merging/closing a task that says a data stage is complete.
---

# Verify pipeline stage

A pipeline's own exit code and summary line tell you it *ran*, not that it produced what was intended. "0 errors, 827 items written" is consistent with a run that wrote 827 items of stale, wrong, or placeholder data just as easily as a run that worked perfectly — the log can't tell the difference, only the data can.

**Why this matters:** in this project, this exact gap let a stage run cleanly against upstream data that was stale (collected before a fix landed), and the run's own summary reported total success the whole time. The mismatch was only caught because the data itself was inspected directly, independent of the pipeline's own report.

## The check, after every stage

1. **Open a fresh client connection to the actual datastore** the stage wrote to (a vector DB, a relational/NoSQL store, an object store, a file) — don't reuse the pipeline process's own connection or trust its self-report.
2. **Pull real sample records, not just counts.** A count can be right while the content is wrong (stale values, a fallback/placeholder used where real data was expected, an off-by-one in a lookup).
3. **Check the counts too** — confirm nothing was silently dropped, and nothing was unexpectedly duplicated (especially after a re-run; idempotent upserts should leave counts unchanged).
4. **Read the sample content with the specific failure modes of this stage in mind**: encoding/garbling issues, a fallback value present where real data should be, data that predates an upstream fix you just made, or a value that's structurally plausible but practically wrong (see the `verify-finding` skill for that last case).
5. **Only report the stage as done once a fresh, independent read confirms it** — not when the stage's own log says success.

## A natural trigger to watch for

If a fix just landed upstream (a parser correction, a corrected lookup table, a bug fix) and a downstream stage was run *before* that fix, its output is stale by construction — rerunning it isn't optional, it's required. Check timestamps/commit order, not just "did this stage run at some point."
