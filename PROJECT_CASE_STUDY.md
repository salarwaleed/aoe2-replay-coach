# Case Study — Teletron: a data-driven Age of Empires II coaching platform

### From a hardcoded Discord bot to a deployed, two-tier LLM game-analytics system

---

## Overview

| | |
|---|---|
| **Domain** | LLM application engineering · data pipelines · binary reverse-engineering · real-time voice |
| **Core stack** | Python 3.13 · discord.py · Google Gemini · Ollama (local LLM) · ChromaDB · DynamoDB · MinIO/S3 · the `mgz` replay library · Docker |
| **Scope** | A Discord bot that answers Age of Empires II strategy questions from real match data, holds spoken conversations in a voice channel, and builds evolving player profiles by parsing game replay files. |
| **Status** | **Shipped and deployed.** The pipeline runs end-to-end; the bot is containerized and runs 24/7 on a free cloud VM; a unit-test suite runs in CI. |
| **Signature results** | Parsed a replay format the standard library cannot read; decrypted Discord's mandatory end-to-end-encrypted voice in order to transcribe it; built a provable player-attribution mechanism with measured, reported coverage. |

---

## 1. Problem and motivation

The project began as a functional but entirely hardcoded Discord bot for a competitive *Age of Empires II* community running a custom Voobly v1.6 ruleset — roughly 2,700 lines of Python whose "knowledge" lived in large static dictionaries. Every answer it gave was something a human had typed into a lookup table by hand.

The objective was to replace that static knowledge with a system that *learns from data*: parse the community's own match replays, extract per-player behavioural telemetry, and use language models to turn that telemetry into readable strategic profiles the bot can reason about in real time. The design constraint throughout was cost and latency discipline — the system had to be effectively free to run on a single workstation plus a free cloud tier.

---

## 2. System architecture

The system is organized into two tiers with deliberately different economics:

- **Synthesis tier (local, batch, latency-tolerant).** New replays are parsed by deterministic Python and staged in a vector store; a local LLM (Ollama) interprets that telemetry overnight into per-player profiles. This work is free and private, and never blocks a user.
- **Live tier (cloud, interactive, cost-sensitive).** In Discord, the bot reads the pre-computed profile and reference data, and makes a single grounded call to a cloud LLM (Gemini) for a fast, contextual answer.

```
Replays ──► Pipeline 1: ingest ──► ChromaDB
                                      │
                     Pipeline 2: telemetry (Ollama) ──► DynamoDB
                                      │
                     Pipeline 3: profiles (Ollama) ──► MinIO / S3
                                                          │
Discord ◄──► bot.py ──► Gemini (live answers, grounded in profiles + rules)
```

The guiding principle is that expensive cloud tokens are spent only at query time, on small pre-digested context, while the heavy interpretive work is amortized to free local compute. The separation of *deterministic decoding* from *probabilistic interpretation* — Python decodes, the model reasons — is the backbone of the design.

---

## 3. Key engineering challenges

### 3.1 Reverse-engineering an unreadable replay format

The community's `.mgz` files are Voobly UserPatch `VER 9.F` recordings, and the standard `mgz` Python library fails to parse them. The first step was ruling out the alarming explanation — that the files were DRM-locked — by confirming the headers decompress cleanly with standard deflate to a readable version string. This was a parser/mod-version mismatch, not encryption.

The solution bypassed the library's structured high-level parser and walked the file's command **body** at the byte level using its low-level primitives — accumulating time-synchronization operations for the game clock and reading the authoritative post-game block for the result. A second pass recovered per-player names, civilizations, colors, and spawn positions directly from the decompressed header, fields the high-level parser returns as null. A capability the official tooling reports as impossible was achieved by dropping one level of abstraction.

### 3.2 Feasibility-driven scoping

A replay is a **command log**: it records what players clicked, not the game's outcomes (resource counts, unit positions, kills). Rather than design against hope, every desired telemetry signal was empirically probed against real files and classified as directly extractable, recoverable via proxy, or not feasible. An observed anomaly — one action type absent entirely — was handled by switching age-progression estimates to time-based game phases. Confronting the data's limits early kept the system buildable and its claims honest.

### 3.3 Retrieval-augmented grounding for a non-standard ruleset

Once live answers came from Gemini, a subtle failure surfaced: the model gave textbook Age of Empires II advice — early-game villager counts, standard age-up timings — none of which apply to this server's custom Imperial-Age-start ruleset. The model knew vanilla strategy from its training data and had never encountered this meta.

The fix was retrieval-augmented grounding. Every answer prompt now carries structured, server-specific reference data — exact starting resources, building costs, and production rates — together with the relevant player profiles, injected via tagged context blocks. The model reasons from the server's actual numbers rather than its priors, and command handlers route through a single grounding layer so behaviour is consistent across every feature.

### 3.4 Decrypting Discord's mandatory end-to-end-encrypted voice

A goal was conversational voice: a user speaks a wake word and a question in a voice channel and hears a spoken answer. The receive path presented a substantial obstacle. Stock discord.py cannot receive voice at all, which a community extension addresses; but every received audio frame then decoded to noise.

The cause was **DAVE**, Discord's MLS-based end-to-end voice encryption, which the platform made mandatory in 2026 — non-participating clients are refused at connection time. The bot therefore could not opt out of encryption; it had to decrypt it. Because the bot is a full member of the encrypted voice group, it holds the group's media keys. The receive pipeline was hooked to decrypt each frame with the live session before audio decode, and to drop the occasional undecryptable transition frame rather than fault the stream. In live testing this decrypted the overwhelming majority of frames cleanly and produced accurate transcripts. Speech output (text-to-speech) and wake-word handling were tuned against real transcripts, including accent- and onset-clipping variants observed in practice.

### 3.5 Player attribution, measured honestly

Unit-production commands in this replay format carry no player identifier, so "who built this army" is not directly recorded. The system builds an ownership ledger from the minority of commands that *do* carry identity, attributing production to a building only when the evidence is unambiguous and discarding any object with conflicting claims rather than guessing.

Critically, the coverage of this mechanism was measured across the full replay corpus rather than a convenient sample: an early three-file estimate of ~18–22% was corrected to a true ~9% once every game was analyzed, and the lower figure is the one reported. The value of the result is inseparable from the rigor of its measurement.

---

## 4. Engineering practices

- **Two-tier, cost-aware model selection.** Local models for free, latency-tolerant batch synthesis; a cheap cloud model for fast, pre-contextualized live queries; work distributed by cost rather than defaults.
- **Verification over trust.** Data-producing stages and reported findings were independently confirmed against the actual datastores before being relied upon — a discipline that caught real issues, including a data-lineage bug where profiles had been built from the wrong replay folder, and duplicate records introduced by re-running a stage after its keying logic changed.
- **Testing and CI.** A pytest suite covers the pure, deterministic core — wake-word matching, audio conversion, the attribution ledger's conflict handling, and the civilization-id lookup — and runs on every push via GitHub Actions.
- **Reproducible deployment.** The live bot is containerized (Docker) with a documented deployment path to a free always-on cloud VM; the heavy local synthesis remains on a workstation and publishes results to the shared store.
- **Durable documentation.** Design decisions, the telemetry specification, and the reverse-engineering research are captured in version-controlled documents so the project's state survives independently of any single tool or session.

---

## 5. Current state

The bot is live and answers strategy, economy, build-order, matchup, and free-form questions grounded in real player data; it joins voice channels to both speak coaching and listen for spoken questions; and it recaps recorded games. The full replay pipeline runs end-to-end into ChromaDB, DynamoDB, and MinIO. The codebase is tested in CI and deployable to a free cloud tier. Ongoing work concerns the hardest open sub-problem — raising per-player attribution coverage — for which a promising starting-Town-Center heuristic has been identified and is pending a single labelled validation game.

---

## 6. Skills demonstrated

- **LLM / RAG application engineering** — production systems combining deterministic data pipelines with grounded LLM reasoning under real cost and latency budgets.
- **Data engineering** — incremental ingestion, staged transformation, scheduled batch synthesis, and lineage-aware data hygiene across a vector store, a NoSQL store, and object storage.
- **Reverse-engineering and interoperability** — recovering structured data from an undocumented, version-mismatched binary format and a mandatory encryption layer.
- **Real-time systems** — low-level audio handling, live decryption, and thread-to-event-loop coordination in an asynchronous service.
- **Engineering judgment** — feasibility-driven scoping, empirical measurement of one's own results, cost-conscious architecture, and test/CI discipline.
