# Age of Empires II Behavioral Profiling Engine — Project Case Study

### From a hardcoded Discord bot to a two-tier-LLM game-analytics pipeline

> **A portfolio narrative: what I set out to build, how the plan changed when it met reality,
> the problems I hit, how I solved them, and what I learned doing it.**

---

## At a glance

| | |
|---|---|
| **Domain** | Game analytics · LLM application engineering · reverse-engineering |
| **Core stack** | Python · discord.py · the `mgz` replay library · ChromaDB · Ollama (local LLM) · Gemini (cloud LLM) |
| **Methodology** | AI-assisted, multi-agent development; empirical feasibility probing; iterative architecture |
| **Status** | Advanced design + research phase. A hard reverse-engineering problem **solved**; full pipeline scoped and documented; implementation gated on a few decisions. |
| **Signature win** | Cracked a replay-file format (`VER 9.F`) that the standard parser library could not read. |

---

## 1. Where it started

The project began as a working but **fully hardcoded** Discord bot for *Age of Empires II*
(Voobly v1.6 competitive mod): ~2,700 lines of Python with large static dictionaries powering
commands like `!civ`, `!counter`, `!build`, and a replay-analysis feature (`!analyze`, `!profile`)
that read saved games from disk.

I started by deliberately separating **where** work should happen — planning, documentation, and
coordination in a chat-style assistant environment, versus hands-on file editing, parsing, and
execution in a code-native environment. That distinction mattered: it kept high-level design
decisions separate from low-level implementation, a separation that became a theme of the whole
project.

My dissatisfaction was simple: **the bot "knew" things only because I had typed them in.** I wanted
it to *learn* — to answer questions from real data, powered by an LLM, not from dictionaries I had
to maintain by hand.

---

## 2. What was originally planned

The first plan was modest: **replace the hardcoded knowledge with live Gemini API calls.** Swap a
dictionary lookup for a model call and let the LLM answer strategy questions.

That plan survived contact with reality for about one design pass, because it contained a
conceptual error I had to confront early (see §4.1). The real project — the one worth building —
turned out to be far more interesting.

---

## 3. How the plan evolved

The idea grew, in stages, into a **"Deep Behavioral Profiling Engine"**: a system that parses a
player's replay files, extracts granular in-game telemetry, and uses LLMs to build an **evolving,
plain-English psychological/strategic profile** of each player — which the bot can then answer
questions about in real time.

The architecture settled into a deliberately **two-tier LLM design**:

```
DAYTIME CAPTURE   New replay appears → deterministic Python parser extracts telemetry
   (no API cost)  → staged in a vector DB (ChromaDB), tagged "unprocessed"

NIGHTLY SYNTHESIS Batch job feeds unprocessed telemetry to a LOCAL LLM (Ollama, free, offline)
   (while I sleep) → it interprets the timings and rewrites each player's profile.txt
                     only if something meaningfully changed

DAYTIME QUERY     User asks in Discord → bot reads the pre-compiled profile.txt directly
   (cheap, fast)  → injects it into ONE cloud LLM call (Gemini) → deep, instant answer
```

The reasoning behind the split is the part I'm proudest of: **expensive cloud tokens are spent only
at query time on tiny, pre-digested context, while the heavy interpretive work is done for free
overnight on local hardware.** Cost and latency drove the architecture, not the other way around.

---

## 4. Problems faced — and how I tackled them

### 4.1 "Use the LLM to read the files" — a category error
**Problem:** My initial instinct was to have Gemini decode the binary replay files.
**Insight:** An LLM is the wrong tool for parsing binary — it's unreliable, expensive, and
unnecessary. Decoding is a *deterministic* job; *interpretation* is the LLM's job.
**Resolution:** I split the system cleanly: **Python decodes, the LLM reasons.** This separation of
concerns became the backbone of the entire architecture.

### 4.2 Polluted data with a hidden lineage
**Problem:** The bot was scanning two save folders; the cached player profiles were silently built
from 4 old, off-version files instead of my real 24 competitive games.
**Resolution:** I traced the data lineage (every cached profile's "last seen" date mapped back to
the excluded files), narrowed the scanner to the correct folder, and reset the poisoned cache —
then confirmed the rebuild logic would regenerate cleanly. **Lesson internalized: always verify
where your data actually came from before trusting it.**

### 4.3 The replay files were unreadable — the central challenge
**Problem:** The standard `mgz` Python library **failed on every one of my 24 files** with a cryptic
parser error. These were Voobly/UserPatch **`VER 9.F`** recordings.
**Diagnosis:** I first ruled out the scary explanation — was this DRM/encryption locking the files
to Voobly? I proved it wasn't: the file headers decompressed cleanly with standard deflate to a
readable `VER 9.F` version string. **Not encryption — a parser/mod-version mismatch.** The library's
*structured header* parser choked on the mod's altered data layout.
**Resolution — multi-angle, resource-aware:** Rather than guess, I ran a **3-way race**: three
independent agents attacking the same single test file with different strategies (library upgrade,
alternate parser APIs, raw byte-level reverse-engineering) — **in the background, so I could halt the
losers the instant one succeeded**, saving compute. The winner bypassed the broken high-level parser
entirely and walked the file's **body** at the byte level using the library's low-level `fast`
module, accumulating `SYNC` time-ops for the game clock and reading the authoritative `POSTGAME`
block for the result. **A problem the official tooling declared impossible, solved by dropping one
level of abstraction.**

### 4.4 Ambition vs. physics — what a replay can actually tell you
**Problem:** The profiling vision called for rich telemetry: villager-on-stone counts, "first unit
entering enemy line of sight," exact army positioning.
**Insight:** A replay is a **command log** — it records what players *clicked*, never the game's
*outcomes* (resources, unit positions, vision, kills). Half the wishlist would require simulating
the entire game engine.
**Resolution:** Instead of designing on hope, I **empirically probed my real files** to see what
data physically existed, then ran a structured pipeline to classify every desired signal as
**extractable / workaround / not-feasible** — grounded in evidence, not optimism. I also discovered
an anomaly (the `RESEARCH` action was 100% absent, so age-up timing was unavailable) and adapted the
design to use **time-based game phases** instead. **Choosing to confront the constraints early,
honestly, is what kept the project buildable.**

### 4.5 Turning a vague wish-list into a ranked, validated spec
**Problem:** "Record everything interesting" is not a specification.
**Resolution:** I orchestrated a **7-agent pipeline**: five low-cost agents brainstormed ~197 telemetry
ideas across distinct domains (economy, military, defense, map control, psychology); a mid-tier agent
**deduplicated and ranked** them by significance into 92 tiered signals; a final agent **classified
each by technical feasibility** against my probe evidence. Output: a defensible, prioritized spec
with a clear "reliable spine" of ~14 directly-extractable signals plus strong proxies.

### 4.6 Don't lose the work
**Problem:** Critical analysis was living only in a chat transcript.
**Resolution:** I had it all written to durable, version-controllable documents (`TELEMETRY_PLAN.md`,
this case study) so the project's state survives independently of any one tool or session.

---

## 5. Working knowledge I gained

**Reverse-engineering & binary formats**
- The structure of AoE II `.mgz` recorded games: compressed header + uncompressed body of
  time-synchronized command operations; deflate decompression, length-prefixed sections,
  byte-stream walking.
- How to drop below a failing high-level API to a low-level one when an abstraction breaks.
- Distinguishing *encryption* from *compression* from *version mismatch* by evidence.

**LLM application architecture**
- When **not** to use an LLM (deterministic parsing) vs. when it shines (interpretation, synthesis).
- **Two-tier LLM design**: local model (Ollama) for free, latency-tolerant batch work; cloud model
  (Gemini) for cheap, fast, pre-contextualized queries.
- Retrieval/RAG concepts and **vector databases (ChromaDB)** — including the judgment that in v1 it
  functions as a tagged staging queue, not a semantic search store.
- The "pre-compute the expensive thinking, inject a small context at query time" cost pattern.

**Data engineering**
- An incremental ETL pipeline: detect new files → parse → stage with `processed` flags →
  batch-transform → update derived artifacts; designed for a folder that grows over time.
- Scheduled/offline processing (a nightly batch decoupled from the live service).
- Data-lineage tracing and cache invalidation.

**Systems & tooling**
- discord.py bot architecture: commands, embeds, intents, voice/TTS, async offloading of CPU-bound work.
- Hardware-aware ML deployment: recognizing that an AMD RDNA1 GPU (5600 XT) won't accelerate Ollama
  under ROCm, so the local model runs on CPU — acceptable precisely because it's an overnight batch.
- **Multi-agent orchestration**: distributing work across model tiers by cost, running competing
  approaches in parallel, and halting redundant work on first success.

---

## 6. My approach to problem-solving & architecture

A few principles I demonstrated repeatedly, and now hold deliberately:

1. **Separation of concerns.** Deterministic work and probabilistic work are different tools.
   Decode with code; reason with the model. Most of the architecture fell out of this one line.
2. **Right tool for the job, costed.** Local vs. cloud LLM, vector DB vs. simple queue, GPU vs. CPU —
   each chosen against real constraints (price, latency, hardware), not defaults.
3. **Validate before you commit.** I probed the actual files before designing on top of them, and
   classified every feature by real feasibility. I would rather kill a feature early than discover
   mid-build that the data never existed.
4. **Confront constraints honestly.** When the data couldn't support half the vision, I said so and
   rescoped — a buildable 60% beats an imaginary 100%.
5. **Manage resources deliberately.** Parallel investigation, then halt the losers. Cheap models for
   breadth, capable models for judgment.
6. **Make the work durable.** Decisions and findings go into documents, not just memory.

---

## 7. What completing this prepares me to build

The skills exercised here transfer directly to:

- **LLM / RAG application engineering** — production systems that combine deterministic data
  pipelines with LLM reasoning, with real cost and latency budgets.
- **Data engineering / ETL platforms** — incremental ingestion, staging, scheduled transformation,
  and lineage-aware data hygiene.
- **Game & esports analytics** — replay parsing, telemetry extraction, and player/behavioral modeling
  (a real and growing industry).
- **Reverse-engineering & interoperability** — reading undocumented or version-mismatched binary
  formats when official tooling falls short.
- **Multi-agent / agentic AI systems** — orchestrating tiered models for cost-effective automation.
- **Behavioral analytics** generally — turning granular event logs into human-readable, evolving
  profiles.

---

## 8. Closing reflection

The most valuable thing this project taught me isn't a library or an API — it's a **way of working**:
start with an ambitious vision, pressure-test it against reality early and honestly, separate the
deterministic from the probabilistic, choose every component against real constraints, and document
the journey so the knowledge compounds. The headline result — reverse-engineering a replay format the
standard tools couldn't read — is satisfying. But the discipline that produced it is the part I'd
bring to any team.

---

*Companion document: `age of empire discord bot/TELEMETRY_PLAN.md` — the full technical spec, the
92-signal feasibility catalogue, and the working parser code.*
