# AoE II Discord Bot — Behavioral Profiling Engine: Telemetry & Architecture Plan

> **Status:** Design/research phase — saved 2026-06-27. No pipeline code written yet.
> This document captures the architecture, the replay-parsing breakthrough, and the full
> telemetry feasibility analysis so the work survives independently of the chat history.

---

## 1. Project Vision (and the correction from "yesterday")

**Goal:** Turn the bot from a *hardcoded* knowledge bot into a **data-driven, two-tier-LLM
"Deep Psychological Profiling Engine"** that learns each player from their own replay files
and answers questions about them in real time.

Key correction: knowledge should **not** be hardcoded into `bot.py`. The bot should learn each
player from their `.mgz` replays and answer from evolving, machine-written profiles —
a cheap **cloud LLM (Gemini via Openclaw)** for live answers, and a free **local LLM (Ollama)**
doing heavy synthesis overnight.

---

## 2. Target Architecture (two-tier LLM pipeline)

```
① DAYTIME CAPTURE  (bot running, NO API calls)
   New .mgz in SaveGame ─► in-bot watcher ─► Python parse (mgz.fast, deterministic)
   ─► extract telemetry events (+ game-time) ─► ChromaDB "raw_match_logs"
      metadata { processed: false, player }

② NIGHTLY SYNTHESIS  (Windows Task Scheduler, ~3 AM, offline)
   Batch script pulls { processed:false } ─► Local LLM ① (Ollama, CPU)
   interprets the raw timings ─► synthesises behaviour by Early/Mid/End game phase
   ─► rewrites {player}_profile.txt ONLY if meaningfully changed
   ─► marks ChromaDB { processed:true }

③ DAYTIME QUERY  (live in Discord)
   User: !ask <player> ─► bot reads {player}_profile.txt DIRECTLY (bypasses ChromaDB)
   ─► Cloud LLM ② (Gemini via Openclaw), profile injected as context, 1 cheap call
   ─► deep behavioural answer ─► Discord embed
```

**Design notes / decisions so far**
- Embeddings: local model (per earlier choice) — but in v1 ChromaDB acts as a **tagged staging
  queue**; semantic vector search is NOT yet used (queries read the profile `.txt` directly).
  → A SQLite/JSON queue could replace ChromaDB in v1; ChromaDB kept for future semantic search.
- Auto-update: **in-bot background loop** scans the SaveGame folder + ingests new files;
  nightly synthesis is a **separate scheduled script** (runs even if the bot is down).
- Hardware: AMD **5600 XT will NOT accelerate Ollama** (RDNA1 unsupported by ROCm on Windows)
  → nightly LLM runs on **CPU**; fine for an overnight batch with an 8B-class model on 16 GB RAM.
- Phases are by **elapsed game-time** (Early/Mid/End by minutes), NOT by age — see §6.

---

## 3. Replay-Parsing Breakthrough (VER 9.F)

These are Voobly/UserPatch **`VER 9.F`** recorded games. The high-level `mgz.summary.Summary`
**fails** on them (`invalid mgz file: expected 5 to 5, found 0 (parsing) -> initial`) because
mgz's structured *header* parser chokes on the Voobly mod's altered player-data layout. **Not
encryption — just a parser/mod mismatch** (the header zlib-decompresses cleanly to `VER 9.F`).

**Working method (uses the already-installed `mgz==1.8.51`, no upgrade):** skip the header via
the length prefix and walk the **body** with the low-level `mgz.fast` parser.

```python
import struct, io
from mgz.fast import sync as fast_sync, action as fast_action
from mgz.fast.enums import Operation
from mgz.body.actions import postgame as postgame_struct

with open(path, 'rb') as fh:
    raw = fh.read()
header_len = struct.unpack('<I', raw[:4])[0]     # 4-byte little-endian length prefix
body = raw[4 + header_len:]
data = io.BytesIO(body)
data.read(24)                                    # skip leading meta/start block

total_ms = 0
while True:
    chunk = data.read(4)
    if len(chunk) < 4:
        break
    op = Operation(struct.unpack('<I', chunk)[0])
    if op == Operation.SYNC:
        inc, _, _ = fast_sync(data); total_ms += inc      # accumulate game-time
    elif op == Operation.VIEWLOCK:
        data.read(12)
    elif op == Operation.ACTION:
        atype, payload = fast_action(data)                 # player commands
        if str(atype) == 'Action.POSTGAME':
            pg = postgame_struct.parse(payload['bytes'])    # authoritative duration/complete flag
            break
```

- **Duration:** authoritative from the `POSTGAME` block's `duration` field; cross-checked by
  summing `SYNC` increments.
- **Voobly quirk:** action_id **177 (0xB1)** is an anti-cheat heartbeat injected into the action
  stream — must be skipped or the parser throws `177 is not a valid Action`.
- Each `ACTION` carries a `player_id` and an exact game-time timestamp (from accumulated SYNC).
- **Building/unit ids are raw genie DAT ids** — mgz gives no names when the header is unparsed,
  so we must ship a static **id → name(+category)** lookup (well-documented, stable across AoC/UP/DE).

---

## 4. Data Inventory

- **Active folder (only one scanned):**
  `D:\Program Files (x86)\Microsoft Games\Age of Empires II\Voobly Mods\AOC\Data Mods\v1.6 Game Data\SaveGame`
  → 24 `.mgz` files (May–Jun 2026). **22 parse** at body level; **2 are unreadable** and must be
  skipped + logged: `rec.20260621-015219.mgz`, `rec.20260625-204143.mgz`.
- **Excluded folder** (base-game `...\Age of Empires II\SaveGame`, 4 old off-version files) was
  removed from `SAVEGAME_PATHS` in `bot.py`. `profiles.json` was reset to `{}` (it had been built
  entirely from those 4 excluded files).
- Longest games found: `rec.20260531-235412.mgz` (119 min, 13,643 actions),
  `rec.20260605-212542.mgz` (69 min, 12,826 actions).

**Action types PRESENT (with field parsers):** BUILD, WALL, GATE, QUEUE, MULTIQUEUE, TRIBUTE,
DE_TRIBUTE, MOVE, ORDER, GATHER_POINT, STANCE, FORMATION, GUARD, FOLLOW, PATROL, ATTACK_GROUND,
DELETE, UNGARRISON, REPAIR, SELL, BUY, FLARE, TOWN_BELL, BACK_TO_WORK, RESIGN, SPECIAL, GAME,
SAVE, POSTGAME, SYNC.
**Action type ABSENT (critical):** `RESEARCH` (id 101) — **zero** across all 24 files.

---

## 5. Telemetry Catalogue — 92 signals, ranked & classified

Produced by a 7-agent pipeline (5 brainstorm → dedupe/rank → extractability classify).
Raw ~197 ideas → **92 deduped**. Verdicts: **✅ Extractable 14 · 🟡 Workaround 33 · ❌ Not feasible 45**.
Tags: [ECO] [MIL] [DEF] [MAP] [PSY]. Verdict legend:
✅ = direct from action stream + game-time · 🟡 = proxy/approximation/partial · ❌ = needs full game-state/vision/resource simulation, or absent.

### TIER 1 — Defining signals (✅3 · 🟡8 · ❌5)
- [ECO] Boom / villager-count growth curve — 🟡 — count villager QUEUE orders over time (ignores deaths/idle)
- [ECO] Feudal/age-advance timing — ❌ — RESEARCH absent; only weak proxy = first age-gated building/unit
- [ECO] 2nd/3rd TC built (boom commitment) — ✅ — BUILD filtered to Town Centre id: count + timestamps
- [MIL] First military unit leaves base < 5 min — 🟡 — MOVE/ORDER on units known-military from QUEUE vs base coords
- [MIL] Raid/attack within 10 min of feudal — ❌ — needs feudal timestamp (unavailable)
- [MIL] Targets/kills enemy villagers — ❌ — no kill/death data; ORDER target_id has no type
- [MIL] All-in push / full-army commitment — 🟡 — proxy via large simultaneous MOVE/ATTACK_GROUND clusters off-base
- [MIL] Composition transitions (archers→cav, siege focus) — 🟡 — QUEUE unit_id sequence (training orders, not survivors)
- [DEF] Base perimeter / choke-point walled — 🟡 — aggregate WALL/GATE coords into rough perimeter (no terrain geometry)
- [DEF] Castle in-base vs forward — 🟡 — BUILD Castle coords vs starting-TC centroid heuristic
- [MAP] Scout leaves home & discovers enemy base — ❌ — no vision/LOS/"discover" events
- [MAP] Expands to new resource cluster / forward — 🟡 — BUILD (TC/camps) far from start (cluster identity unknown)
- [PSY] Resigns within 5 min of raid / after key loss / despite advantage — 🟡 — RESIGN time is exact; the *context* needs loss/strength data we lack
- [PSY] Deviates from build order / abandons strategy — ✅ — compare actual BUILD/QUEUE sequence vs a reference template
- [PSY] Detection-to-reaction gap on enemy sighting — ❌ — no sighting/vision event to anchor "detection"
- [PSY] Paralysis/freeze after army dies / under attack — ❌ — needs army-death/combat events

### TIER 2 — Supporting signals (✅7 · 🟡13 · ❌12)
- [ECO] Villager reassignment (food→wood/gold) — ❌ — gather-target resource type not recorded
- [ECO] Idle villager 5s+ / idle TC — ❌ — idleness is state, needs simulation
- [ECO] Resource shortage events — ❌ — no resource totals in stream
- [ECO] Key economic techs (wheelbarrow, loom, plow, mining) — ❌ — RESEARCH absent
- [ECO] Market usage (buy/sell) — ✅ — BUY/SELL actions with resource + amount
- [ECO] Pop-capped / capped while building house — ❌ — needs live pop/cap state
- [ECO] Eco stalled 30s+ — 🟡 — proxy via long gaps in villager QUEUE/BUILD activity
- [MIL] Military building order & timing — ✅ — BUILD filtered by military-building ids
- [MIL] Dedicated raid group (4–6) vs mass army — 🟡 — object_ids count in one MOVE/ORDER (types unconfirmed)
- [MIL] Army moves toward enemy base/resource lines — 🟡 — MOVE/ATTACK_GROUND coords trending to enemy start
- [MIL] Monk conversion of units — ❌ — conversion is an outcome (ownership change), not a command
- [MIL] Loses majority of army / rebuilds — ❌ — no unit-loss data
- [MIL] Trade efficiency (5-for-3) — ❌ — needs kill/death tracking
- [MIL] Attacks TC / defensive structures — 🟡 — ATTACK_GROUND/ORDER coords on known building coords (target type unconfirmed)
- [DEF] Watch/guard tower placement & clustering — ✅ — BUILD tower ids + coords
- [DEF] Garrisoning during attack — 🟡 — UNGARRISON events present (imply prior garrison); garrison-in timing weaker
- [DEF] Repairs under attack vs proactive — 🟡 — REPAIR timestamp solid; "under attack" inferred
- [DEF] Town bell during attack — 🟡 — TOWN_BELL timestamp solid; "during attack" inferred
- [DEF] Response time to structure damage — ❌ — no damage/HP events
- [DEF] Stone allocation to walls vs eco — ❌ — no per-category resource-spend totals
- [MAP] Relic collection & securing — ❌ — pickup/garrison-in is a game-state event
- [MAP] Forward military building / lumber camp — 🟡 — BUILD coords far from base centroid (threshold heuristic)
- [MAP] Tribute to ally (size) — ✅ — TRIBUTE/DE_TRIBUTE: sender, recipient, resource, amount
- [MAP] Defends teammate's TC / coordinates timing — 🟡 — correlate two players' MOVE/ATTACK coords near ally base
- [MAP] Stance change toward ally/enemy — ✅ — STANCE action with player_id + timestamp
- [PSY] APM spikes/drops during fights — 🟡 — action density over time is solid; "during fights" inferred
- [PSY] Hesitation before aging / attacking from advantage — ❌ — needs age timing + "advantage" state
- [PSY] Shifts resource allocation after loss — ❌ — needs loss events + allocation tracking
- [PSY] Repeats failed strategy / overbuilds — 🟡 — repeated QUEUE unit_id spikes (outcome "failed/worked" unconfirmable)
- [PSY] Slow retreat until near-death — ❌ — needs HP/position-over-time + death events

### TIER 3 — Minor/situational (✅4 · 🟡12 · ❌28, summarised)
- ✅ Extractable: [MIL] Mercenary/unique-unit usage (QUEUE unit_id via table); [MAP] Flare/ping frequency & location (FLARE coords+time). (Plus market/stance already counted above.)
- 🟡 Workaround: [ECO] Farm/fish-trap seeding cadence (BUILD ids); [DEF] Wall deleted/rebuilt same spot (DELETE↔WALL coord match); [DEF] Gate repositioned (GATE BUILD/DELETE coord delta); [DEF] Secondary wall layer / thickness (WALL coord density); [DEF] Trebuchet near gate (unit MOVE vs gate coords); [MAP] Fishing boat to new water (MOVE of boat object); [PSY] Spam-clicking same spot (repeated MOVE/ORDER same coords); [PSY] Move-and-cancel indecision (rapid alternating commands on same object_ids); [PSY] Chat behaviour — **needs a quick probe** (chat availability uncertain).
- ❌ Not feasible: villager walk distance, stockpile imbalance, multiple idle villagers, scout-harasses-gatherers, focus-fire on building, flanking pattern, scout camps/lingers, gathering site abandoned/contested, camera fixed vs jumping, collision pathing stuck, random unrelated upgrades after loss (RESEARCH absent) — all require resource/position/vision/combat simulation not in the command stream.

---

## 6. Key Constraints & Findings

1. **A replay is a command log, not a recording.** It captures what players *clicked*, never the
   game's *outcomes* — no resource totals, unit positions, HP, kills/deaths, vision/LOS, or camera.
   "What was built and when" = solid; "what happened as a result" = mostly not.
2. **RESEARCH is 100% absent** — the single biggest hole. Removes Feudal/Castle/Imperial timing and
   every tech-research signal, cascading into ❌ for all "after aging up" items.
   → Mitigation: use **time-based phases** (Early/Mid/End by elapsed minutes; game-time is exact).
3. **Raw DAT ids** need a static id→name(+category: eco/military/defensive) table we supply.
4. **2 of 24 files unreadable**; **Voobly heartbeat (177)** filtered.
5. **The reliable spine** (what profiling CAN stand on): build-order DNA & deviation, TC/expansion
   timing (booming), military-building order/timing & army-toward-enemy proxy (aggression),
   wall/tower/castle placement (defense), tributes + stance + flares (teamwork),
   resign timing + APM/action-density (tilt/mentality), unique-unit usage, market usage.

---

## 7. Open Decisions (pending user answer)

**Q1 — Telemetry scope:** (recommended) build on the extractable spine + strong proxies, time-based
phases, drop the 45 simulation-only signals · OR ship spine now + build a game-state re-simulation
engine later · OR insist on full granularity first (not advised).

**Q2 — RESEARCH/age-up absence:** (recommended) skip & use time-based phases · OR investigate briefly
whether this Voobly build encodes research differently · OR investigate deeply.

---

## 8. Resume Instructions / Next Steps

1. Answer Q1 + Q2 above.
2. Build the static DAT id→name(+category) table for the v1.6 building/unit set.
3. Implement `parse_match_timeline()` (new) on top of the §3 `mgz.fast` body walk — emit the
   ✅/🟡 telemetry events with timestamps + player_id; skip the 2 unreadable files + heartbeat.
4. Wire the in-bot watcher → ChromaDB staging `{processed:false}`.
5. Write the nightly Ollama batch script (Task Scheduler) → `{player}_profile.txt` synthesis.
6. Add the Discord `!ask <player>` command → read profile.txt → Gemini/Openclaw call.

**Still needed from the user / unresolved:** Openclaw endpoint format (OpenAI-style `/chat/completions`
vs native Gemini `:generateContent`), API key, and model name for the daytime Gemini call.

**Working preference noted:** delegate script/parsing execution to spawned sub-agents rather than
running it directly in the main session.
