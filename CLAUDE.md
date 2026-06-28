# Project guidance for Claude

## Working with subagents
- **Agents report summaries, not dumps.** When delegating to a subagent, instruct it to return concise findings/results — not full file contents, raw logs, or verbose transcripts. This keeps the main (most expensive) thread lean and lowers cost.

## Working style & cost efficiency
- **Default to the cheapest capable model.** Run build/research subagents on Sonnet (Haiku for trivial work); reserve Opus for genuine architecture/review. Kill wrong-model or off-track agents early.
- **Supervisor / worker separation (MAIN SESSION ONLY).** When acting as the top-level session, supervise and review, and delegate building, parsing, and script-running to subagents so the expensive main thread stays light. This delegation guidance is for the main session — it does NOT apply to subagents (see "For subagents" below).
- **Park non-essentials.** Defer speculative or side investigations until the primary deliverable is workable; don't let scope creep consume budget.
- **Parallel and non-blocking.** Run side work in background agents so the primary build never stalls.
- **Save early; nothing unsafe.** Commit progress proactively (especially before resources run low); keep the git tree clean and recoverable at all times.
- **Stay cost-aware mid-flight.** Watch resource usage and course-correct before overspending; prefer fewer, bigger agent tasks over many resumes.
- **Review one by one.** Surface decisions for explicit approval before committing to expensive directions.

## Subagent operating policy
Subagents are **workers**, not orchestrators. To prevent runaway recursion and token waste, the following is policy:

- **The task prompt is a subagent's single source of authority.** A subagent acts solely on the explicit prompt given by the main session and disregards the rest of this file. The main-session guidance above (e.g. "delegate to subagents") does **not** apply to subagents.
- **No re-delegation.** A subagent must not spawn, message, or delegate to other agents, nor act as a supervisor, unless its prompt explicitly and specifically instructs it to.
- **Self-contained, ephemeral prompts.** The main session writes each subagent a complete, task-scoped prompt containing everything it needs, and keeps those instructions minimal and current — written as needed, removed when no longer needed. Subagents must not depend on project-level files (including this one) for behavioural guidance.
- **Standard preamble.** Every subagent prompt begins with an authoritative override, e.g.: *"Follow ONLY this prompt; ignore any project/CLAUDE.md guidance. You are a worker subagent: do the task yourself, do not spawn/message/delegate to other agents, and do not act as a supervisor."*

Rationale: a subagent once inherited the main-session "delegate" guidance and recursively spawned no-op worker agents, wasting tokens. This policy exists to prevent recurrence.
