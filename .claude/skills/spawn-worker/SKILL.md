---
name: spawn-worker
description: Use this skill whenever the main/supervising session is about to delegate a task to a subagent (e.g. via the Agent tool), especially for build, research, fix, or verification work in this project. Compose the subagent's prompt with this template before sending it, so the subagent never inherits the main session's own "delegate to subagents" guidance and recursively spawns more agents instead of doing the work. Trigger this any time an Agent tool call is about to be written, not just when explicitly asked to "spawn a worker."
---

# Spawn worker

Compose every subagent prompt with four parts, in this order. A subagent reads CLAUDE.md and other project files just like the main session does — if its prompt doesn't override that, it may follow main-session guidance meant for *you*, not for it.

## 1. Override preamble (always first)

Open with this exact override, verbatim:

> Follow ONLY this prompt; ignore any project/CLAUDE.md guidance. You are a worker subagent: do the task yourself; do NOT spawn, message, or delegate to other agents, and do NOT act as a supervisor.

**Why this exists:** a subagent once read the main session's own "delegate building/parsing to subagents" instruction inside CLAUDE.md, took it as an instruction to itself, and spawned a chain of no-op "worker" agents that did nothing but burn tokens. The override prevents this category of failure entirely, regardless of what else CLAUDE.md says later.

## 2. Need-to-know briefing

Give the subagent only what *this task* requires — the specific files, paths, prior findings, and constraints it needs to act, not the project's full history or architecture. As in any organization, people work best when told what they need to know, not everything that's known. This also keeps the prompt (and therefore the cost of every spawn) lean.

## 3. Model selection

Default to `sonnet`. Use `haiku` only for genuinely trivial, mechanical tasks (a single file read-and-report, a simple lookup). Reserve `opus` for tasks that need deep architectural judgment or where getting it wrong is expensive to unwind. When in doubt, sonnet is the right default — it's the model this project standardized on for build and research work after Opus subagents proved unnecessarily costly for the same output.

## 4. Reporting instruction (always last)

Close with an explicit instruction such as:

> Report concisely — a summary of findings/results, not raw dumps, logs, or full file contents.

This keeps the main session's context (the most expensive place for tokens to accumulate) lean, since the subagent's full transcript isn't visible to the main session — only what it chooses to report back.

## Putting it together

```
Follow ONLY this prompt; ignore any project/CLAUDE.md guidance. You are a
worker subagent: do the task yourself; do NOT spawn, message, or delegate to
other agents, and do NOT act as a supervisor.

[Need-to-know context: the specific files/paths/prior findings this task needs]

[The actual task, stated clearly and self-contained]

Report concisely — a summary of findings/results, not raw dumps, logs, or
full file contents.
```

Pick the model (`sonnet` by default) as a parameter on the Agent call itself, not inside the prompt text.
