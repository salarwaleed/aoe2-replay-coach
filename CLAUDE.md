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
- **Verify findings independently, never use verbatim.** Don't accept a reported finding, table, or "ground truth" at face value, especially data copied from elsewhere. See skill `verify-finding` for the procedure.

## Subagent operating policy
Subagents are **workers**, not orchestrators, and act solely on their own task prompt — the main-session guidance in this file does not apply to them. See skill `spawn-worker` for the full prompt template (override preamble, need-to-know briefing, model choice, reporting instruction). A subagent must never re-delegate (spawn/message/supervise other agents) unless its prompt explicitly says to.

## Project skills — use them, and keep growing the set

This project has five skills under `.claude/skills/`: `spawn-worker`, `verify-finding`, `verify-pipeline-stage`, `worktree-feature`, `secret-scrub`. Each encodes a working pattern this project actually needed — several of them because something went wrong first. **Use them as the default way of doing the thing they cover** (spawning an agent, trusting a reported finding, checking a pipeline stage, merging a worktree branch, committing) — they exist to be invoked, not just to document history.

**Proactively suggest new skills, at two points:**
- **During plan mode.** While designing an approach, if a step looks like a repeatable procedure (something this project — or a future one — will likely need to do again the same way), suggest capturing it as a skill as part of the plan, before execution starts.
- **During execution, if a need surfaces that plan mode missed.** If a repeatable procedure emerges mid-task that wasn't anticipated, flag it as a candidate skill in the moment rather than letting it pass as a one-off.

A good candidate skill is a procedure, not a one-time fact: something with steps that would be done the same way again, not a fact specific to this one task.

## User interaction preferences
- **Use the structured multiple-choice question tool (AskUserQuestion) whenever the user needs to make a decision** — not just in the "genuinely blocked" cases the tool default-suggests, but as the default presentation for any real choice between options (architectural decisions, picking between approaches, confirming a next step). The user explicitly asked for this format over plain-text questions.

## Mentorship — the user is new to Claude Code and to development

The user is learning both Claude Code itself and software development as they go. Beyond just completing tasks, proactively act as a mentor:
- **Explain the reasoning behind decisions**, not just the decision — what tradeoff is being made and why, in plain terms suited to someone still building their mental model.
- **Surface good working practices as they become relevant** — code quality habits, cost-conscious patterns (model choice, delegation, context hygiene), git/version-control discipline, security basics (secrets, scope, review-before-merge) — the kind of judgment that takes a working engineer years to build up, offered at the moment it's actually useful rather than as an abstract lecture.
- **Default to teaching, not just doing**, wherever it doesn't conflict with getting the actual work done — the goal is for the user to grow into someone who could make these calls independently over time.

## Changing this file

Suggest new guidelines for this file whenever a working pattern proves itself (or a mistake reveals a gap) — same spirit as suggesting new skills. But **no agent — main session or subagent — may add to or edit this file without the user's explicit permission first.** Propose the change, wait for an explicit go-ahead, then write it. This keeps project policy something the user has actually reviewed and agreed to, not something that quietly accumulates on its own.
