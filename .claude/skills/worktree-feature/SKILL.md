---
name: worktree-feature
description: Use when building a feature or fix that should be developed and reviewed in isolation before it lands in main — especially when the implementation will be delegated to a subagent rather than written by the main session itself. Sets up an isolated git worktree/branch, dispatches the agent, and defines a scope-checked review gate before merging. Trigger this whenever about to hand a code change to a subagent and will need to merge its result back into the main branch afterward.
---

# Worktree feature

The point of this workflow is to keep the person reviewing a change (the main/supervising session) separate from the person who wrote it (the subagent) — and to make sure that review actually happens before the change lands, rather than after.

**Why this matters:** a supervising session that also writes the implementation can't review its own code without bias, and a change merged without an explicit scope check can silently touch files it was told never to touch. This sequence was used repeatedly in this project to build and merge several pipeline stages safely.

## The sequence

1. **Create an isolated worktree on a new branch off main.**
   - If no worktree exists yet for this project: `git worktree add -b <branch-name> <worktree-path> main`
   - If a worktree already exists and is reusable: `cd <worktree-path> && git checkout -b <branch-name> main`

2. **Dispatch a worker agent scoped to that worktree**, using the `spawn-worker` skill's template — give it the worktree path, the exact files it's expected to touch, and (just as importantly) which files it must *not* touch.

3. **After the agent reports back, review independently — don't take its self-report as the review.**
   - `git diff main..<branch-name> --stat` — see exactly which files changed and by how much.
   - Explicitly check the changed-files list against what was out of scope. If the agent was told "never touch X" and X appears in the diff, that's a stop, not a footnote.
   - For anything non-trivial, skim the actual diff content too, not just the file list.

4. **Merge only if the diff is clean and in-scope.**
   - `git merge --no-ff <branch-name>` with a descriptive commit message explaining what changed and why (and, if relevant, what was verified — see `verify-pipeline-stage` for data-producing changes).

5. **If anything is out of scope, unclear, or contradicts what was asked, block the merge and investigate first.** Don't merge "mostly right" work and plan to clean it up after — fix it on the branch before it lands.

## Pairing with other skills

- Write the dispatch prompt using `spawn-worker`.
- If the agent's work involved running a pipeline or producing data, apply `verify-pipeline-stage` before considering the branch ready to merge, not just a clean `git diff`.
- If the agent reported an extracted value, table, or root cause as part of its work, apply `verify-finding` before trusting it.
