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

## For subagents (IMPORTANT — prevents runaway recursion)
- If you are a spawned subagent, **you are the worker.** Do the assigned task yourself with your own tools.
- **Do NOT spawn, message, or delegate to other agents, and do NOT act as a supervisor**, unless your task prompt explicitly tells you to. The "delegate to subagents" guidance above is for the main session only.
- Earlier, a subagent read the main-session delegation guidance and recursively spawned "worker" agents that did no work and wasted tokens. Don't repeat that — just execute your task and report.
