# Pipeline 1 — Raw Ingestion (`.mgz` replays ➜ Dockerized ChromaDB)

Pipeline 1 is the **daytime capture** stage of the AoE II profiling engine
(see `../age of empire discord bot/TELEMETRY_PLAN.md` §2). It:

1. Scans the local SaveGame folder for `.mgz` replays.
2. Parses each into a **raw per-player technical event timeline** using the
   low-level `mgz.fast` body walk (the high-level `Summary` reader fails on these
   Voobly UserPatch **VER 9.F** files — see TELEMETRY_PLAN.md §3).
3. Renders events as raw log lines, **chunks** them per player, and **upserts**
   each chunk into a Dockerized **ChromaDB** collection (`raw_match_logs`) as a
   tagged staging queue (`processed: False`) for the later nightly synthesis
   pipeline.

ChromaDB acts as a *staging queue* in v1 (semantic search is not used yet), but
chunks are embedded with Chroma's default model so vector search is available
later for free.

## Layout

```
infra/docker-compose.yml          ChromaDB container (aoe-chromadb, :8000)
pipeline/config.py                connection + paths + chunking constants
pipeline/dat_ids.py               raw genie id -> (name, category) table
pipeline/replay_parser.py         parse_match_timeline(), resolve_players(), UnreadableReplay
pipeline/signals/                 pluggable telemetry-signal registry (the extension seam)
pipeline/pipeline1_ingest.py      orchestrator (python -m pipeline.pipeline1_ingest)
```

## How to run

> **Always install pipeline deps into the dedicated `.venv`, never globally.**
> `chromadb` pulls in a newer `click` (8.2+) that breaks the bot's `gtts 2.5.4`
> (which needs `click<8.2`). The `.venv` keeps the pipeline fully isolated from
> the bot's global environment. `.venv` is gitignored.

```bash
# 1. start ChromaDB (from the worktree root)
docker compose -f infra/docker-compose.yml up -d

# 2. create + activate the dedicated pipeline virtualenv (one-time setup)
python -m venv .venv
source .venv/Scripts/activate     # Windows (Git Bash)
# .venv\Scripts\activate          #   (PowerShell / cmd)
# source .venv/bin/activate       # macOS / Linux

# 3. install the pipeline deps INTO the venv (chromadb + the pinned mgz)
pip install -r pipeline/requirements.txt mgz==1.8.51

# 4. run the ingestion (inside the activated venv)
python -m pipeline.pipeline1_ingest
```

After the first setup, only steps 1 (if the container is down), activate, and 4
are needed. Equivalently, call the venv interpreter directly without activating:
`.venv/Scripts/python.exe -m pipeline.pipeline1_ingest`.

The run prints per-file results and a summary (files parsed/skipped, chunks
upserted, final `collection.count()`). If ChromaDB is unreachable you get a clear
"is the docker container up?" message rather than a traceback.

## Parser behaviour & known facts

- **22 of 24** replays parse; **2 are structurally corrupt** and raise
  `UnreadableReplay` (skipped + logged, never crash the run):
  `rec.20260621-015219.mgz`, `rec.20260625-204143.mgz`.
- These are **post-imperial** games — players start in Imperial Age with all
  techs, so `RESEARCH` actions are **absent by design**, not an error.
- Voobly action id **177 (0xB1)** is an anti-cheat heartbeat; it is skipped
  before it ever reaches the `Action` enum.
- Duration is taken from the POSTGAME `duration` field, cross-checked against the
  SYNC-accumulated total (`duration_sync_ms`); if POSTGAME is missing we fall
  back to the SYNC sum.

### Player attribution limitation (important)

In the legacy Voobly action format these files use, only a subset of actions
carry a player id: **BUILD, WALL, GATE, TRIBUTE, RESIGN, FLARE, DELETE** are
player-attributed. **QUEUE, MULTIQUEUE, STANCE, TOWN_BELL, BACK_TO_WORK, REPAIR,
UNGARRISON, BUY, SELL** are **not** — they identify the player only via the
producing/selected object, whose owner is not recoverable from the command
stream (verified: QUEUE object ids never appear among player-attributed object
ids, so an ownership map does not resolve them).

Rather than guess, such events are bucketed under a sentinel player id
(`UNATTRIBUTED_PLAYER_ID = -1`, rendered `p=?`, metadata `player_name:
"Unattributed"`). This is honest but consequential: **per-player QUEUE-based
signals (boom villager curve, army composition) are not directly attributable in
v1**. The reliable per-player spine is the BUILD-attributed signals — which is
why the two reference signals (`build_by_category`, `town_center_timing`) are
built on BUILD. **This needs a supervisor decision** — see "Open question" below.

### Player names — `resolve_players()` reliability

`resolve_players()` is **best effort and currently falls back cleanly**. The
header zlib-decompresses fine, but its player-name region is interleaved with
binary player-data under the Voobly mod's altered layout, so a byte scan only
recovers mojibake. Rather than surface garbage, the scanner is strict and, when
nothing convincing passes, returns `{pid: "Player N"}` for slots 1..8 — which is
the outcome for **all current files**. Real names will require decoding the
structured header for this specific Voobly build; until then `player_id` (numeric)
is the reliable key and `player_name` is best-effort metadata only.

## Extending: adding a telemetry signal

The `signals/` package is the extension seam. A new signal is a pure function
over the parsed `events` list, registered with `@register` — **no edits to the
parser or the orchestrator**:

```python
from pipeline.signals import register

@register(name="market_usage", tier=2, tag="ECO", description="BUY/SELL activity per player")
def market_usage(events):
    return [...]   # list of flat record dicts
```

Two reference signals ship in `signals/reference.py`:
`build_by_category` (BUILD counts by eco/military/defensive) and
`town_center_timing` (2nd/3rd TC timing — boom commitment).

## Unmapped DAT ids to resolve

`dat_ids.py` maps the BUILD/QUEUE ids observed across the 22 readable replays. The
following ids resolve to `Unknown(id=N)` and are listed for later reconciliation.
Counts are total occurrences across all replays.

**Unmapped BUILD ids:** `665` (x5), `673` (x13), `796` (x2), `1384` (x321),
`1385` (x9), `1461` (x52), `1464` (x149)

**Unmapped QUEUE ids:** `823` (x11), `873` (x25), `1473` (x145), `1524` (x263),
`1526` (x64), `1549` (x148), `2669` (x1), `2677` (x891), `2804` (x10)

A note on the genie object table: the `aocref` package (an `mgz` dependency, so
available in the `.venv`) ships per-dataset object id→name maps under
`aocref/data/datasets/*.json`. Dataset `100` (Definitive Edition) is the closest
match and resolves some of the above — e.g. `1384` / `1385` = **Sea Gate**. It is
**not a perfect match** for this UserPatch v1.6 build, though: several ids it does
name conflict with the observed action semantics/frequencies (e.g. it labels id
`621` "Town Center" though it appears here as a frequent gate-like BUILD; id
`2677` is absent from it entirely). Because of that mismatch these names were
**not auto-adopted** — adopting them wholesale would trade hand-guesses for
dataset-guesses on an imperfect match. Resolving them properly means confirming
the actual genie DAT for this Voobly build. The high-value targets: **`2677`
(x891)**, the most-trained unit after villager/spearman/scout/knight, and BUILD
**`1384` (x321)** (`aocref`: Sea Gate).

> The id→name table was validated against `aocref` dataset 100 during this pass.
> That caught a real bug: genie id `101` is **Stable**, but a stray units-table
> entry was shadowing it in the merged lookup and mislabeling BUILD `id=101` as a
> Town Center. Fixed, with an assertion guarding against future building/unit id
> collisions.

## Open question for the supervisor

QUEUE/MULTIQUEUE (villager + military training) is the highest-volume action and
is **unattributed by player** in these legacy-format replays (see "Player
attribution limitation"). The telemetry catalogue leans heavily on per-player
QUEUE timing (boom curve, composition). Options: (a) accept the BUILD-only
per-player spine for v1 and treat QUEUE as match-level aggregate; (b) investigate
whether forcing mgz's DE/71094 action path (which *does* attribute every action)
applies to this Voobly build; (c) reconstruct ownership via a fuller game-state
walk. Needs your call.
