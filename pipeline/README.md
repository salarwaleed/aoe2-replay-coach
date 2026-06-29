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

`resolve_players()` now recovers **real names, civs, colors, and spawn** from
the VER 9.F header (decoded per `docs/header_decode`) — verified 100% across
all 22 readable replays (see commit `381e8b4`). The header zlib-decompresses
fine; the per-player `attributes` struct is located and walked forward to the
stats block to pull real values. It still falls back to `{pid: "Player N"}`
for any slot it can't confidently resolve, so callers should not assume every
slot is a real name, but `player_id` (numeric) remains the reliable join key
regardless.

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

---

# Pipeline 3 — Player Profiling (DynamoDB timelines ➜ Ollama synthesis ➜ MinIO/S3)

Pipeline 3 is the **strategic synthesis** stage. For a given player name it:

1. Pulls **all their attributed events** (`player_id != -1`) across every match
   they appear in from the `match_timelines` DynamoDB table (Pipeline 2's
   output), sorted chronologically per match.
2. Feeds the resulting event sentences to a local **Ollama** model
   (`qwen2.5:7b` by default) with a prompt that explicitly states the data's
   known gaps, asking for a 7-section strategic profile: playstyle, economy,
   aggression, defense, teamwork, tendencies/strengths, and caveats.
3. Stores the result as both `profile.json` (structured) and `profile.md`
   (human-readable) in an S3-compatible bucket — **MinIO** locally, real AWS
   S3 in prod, via the exact same boto3 code.

Unlike Pipeline 2, there is **no deterministic fallback** here: synthesizing a
strategic read genuinely requires an LLM. If Ollama or the configured model
isn't available, the pipeline raises a clear `OllamaNotReadyError` / exits
non-zero with an actionable message rather than fabricating a profile.

## Layout

```
infra/docker-compose.yml          + minio service (aoe-minio, :9000 API / :9001 console)
pipeline/config.py                + PROFILE_OLLAMA_* and S3_* settings
pipeline/s3_store.py              boto3 S3/MinIO wrapper: ensure_bucket(), put_profile(), get_profile()
pipeline/profile_synth.py         Ollama client + prompt + section parser: synthesize_profile()
pipeline/pipeline3_profiles.py    orchestrator (python -m pipeline.pipeline3_profiles)
```

## How to run

```bash
# 1. start MinIO alongside chromadb + dynamodb-local (from the worktree root)
docker compose -f infra/docker-compose.yml up -d

# 2. pull the profiling model (one-time, ~4-5 GB download)
ollama pull qwen2.5:7b

# 3. (inside the activated .venv) list known attributed player names
python -m pipeline.pipeline3_profiles --list

# 4. build a profile for one player, or all of them
python -m pipeline.pipeline3_profiles "Player 1"
python -m pipeline.pipeline3_profiles --all
```

If the configured model isn't pulled yet (e.g. still downloading), the run
prints a clear "not ready" message and exits 1 — check progress with
`ollama list` and re-run once it appears.

## Storage: MinIO now, real AWS S3 later — same code

`pipeline/s3_store.py` builds its boto3 client from `pipeline/config.py`:

- **Local dev (default):** `S3_ENDPOINT_URL=http://localhost:9000` with dummy
  credentials (`localadmin` / `localpassword123`, matching the `minio` service's
  `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD` in `infra/docker-compose.yml`). Browse
  stored profiles at the MinIO console, `http://localhost:9001`.
- **Real AWS:** set `S3_ENDPOINT_URL=""` (empty) and provide real credentials via
  the standard AWS mechanisms (env vars, `~/.aws/credentials`, or an IAM role).
  With the endpoint unset, boto3 talks to the real regional S3 endpoint and
  every other line of code is unchanged.

Profiles are stored at stable (non-timestamped) keys, so re-running for a
player simply overwrites their previous profile:

```
profiles/{player_name}/profile.json
profiles/{player_name}/profile.md
```

## Known data gaps reflected in every profile

The prompt sent to the model explicitly states, and every generated profile's
**Caveats** section must restate, the same player-attribution limitation
documented above for Pipeline 1/2: only BUILD, WALL, GATE, TRIBUTE, RESIGN,
FLARE, and DELETE are player-attributed. **QUEUE/MULTIQUEUE (unit training) is
not**, so profiles never claim anything about army composition, unit choices,
or military unit counts — that data simply doesn't exist yet at the per-player
level in this dataset.
