# Nightly Synthesis — Windows Task Scheduler Setup

This is stage **② NIGHTLY SYNTHESIS** from `age of empire discord bot/TELEMETRY_PLAN.md`
section 2: a job that runs **outside the bot process**, overnight, and turns
the day's staged ChromaDB chunks into DynamoDB timelines and then into
strategic player profiles in MinIO/S3.

It deliberately does **not** run inside the bot (unlike the daytime
SaveGame watcher) for two reasons:

1. It must still complete even if the Discord bot itself is restarted or down.
2. Pipeline 3's synthesis model (`qwen2.5:7b`, CPU-bound, several minutes per
   player) is far too slow/heavy to run inside the bot's event loop without
   blocking everything else.

## What the script does

`nightly_synthesis.bat` (at the worktree root) runs, in order:

```
python -m pipeline.pipeline2_telemetry        # ChromaDB chunks -> DynamoDB timeline events
python -m pipeline.pipeline3_profiles --all    # DynamoDB -> Ollama synthesis -> MinIO/S3 profiles
```

using the **shared pipeline virtualenv** at:

```
D:\my-portfolio\discord bot\.venv\Scripts\python.exe
```

(the same dedicated venv documented in `pipeline/README.md` — never run the
pipeline against a global/system Python).

Behavior:

- If Pipeline 2 fails (non-zero exit), Pipeline 3 is **skipped** — there is
  no point synthesizing profiles from a timeline that didn't finish updating.
- Every run writes a fresh timestamped log to `logs\nightly_synthesis_<timestamp>.log`
  at the worktree root (created automatically if missing). Check the most
  recent log after each run, especially after the first scheduled run.
- The script's own exit code is Pipeline 3's exit code (or Pipeline 2's, if
  Pipeline 2 failed first) — Task Scheduler will show a non-zero "Last Run
  Result" if anything failed, so you don't have to open the log every night.

## Prerequisites before scheduling

Both pipelines talk to **already-running local services** — the script does
not start them. Before the first scheduled run (and ideally checked into
whatever you use to keep these running persistently), confirm:

| Service        | Port  | Start command (from worktree root)                  |
|-----------------|-------|------------------------------------------------------|
| ChromaDB        | 8000  | `docker compose -f infra/docker-compose.yml up -d`   |
| DynamoDB Local  | 8001  | (same compose file)                                   |
| MinIO           | 9000  | (same compose file)                                   |
| Ollama          | 11434 | `ollama serve` (and `ollama pull qwen2.5:7b` once)    |

If any service is unreachable, the relevant pipeline exits with a clear
error message in the log (not a silent failure) — see each pipeline's
docstring/README for the exact message to expect.

## Registering with Windows Task Scheduler

1. Open **Task Scheduler** (`taskschd.msc`).
2. **Action -> Create Task...** (not "Create Basic Task" — we want the extra
   options below).
3. **General** tab:
   - Name: `AoE2 Bot - Nightly Synthesis`
   - "Run whether user is logged on or not" — recommended, so it still runs
     if you're not at the PC.
   - Check "Run with highest privileges" only if needed for your Docker/Ollama
     setup; usually not required.
4. **Triggers** tab -> **New...**:
   - Begin the task: **On a schedule**
   - Daily, start time **3:00:00 AM** (matches the plan's "~3 AM, offline").
   - Leave "Recur every: 1 days".
5. **Actions** tab -> **New...**:
   - Action: **Start a program**
   - Program/script:
     ```
     D:\my-portfolio\discord-bot-worktrees\pipeline-automation\nightly_synthesis.bat
     ```
     (If you've merged this out of the worktree into the main repo, update
     this path to wherever `nightly_synthesis.bat` actually lives — e.g.
     `D:\my-portfolio\discord bot\nightly_synthesis.bat`.)
   - Start in (optional): leave blank — the script resolves its own
     directory via `%~dp0`, so it works regardless of Task Scheduler's
     working directory.
6. **Conditions** tab:
   - Uncheck "Start the task only if the computer is on AC power" if this is
     a desktop (no battery) — leave checked/adjust if it's a laptop you want
     to spare overnight.
7. **Settings** tab:
   - Check "Run task as soon as possible after a scheduled start is missed"
     (covers the PC being off at 3 AM).
   - Consider "If the task fails, restart every: 30 minutes, up to 3 times"
     for resilience against a transient service outage.
8. Save. You'll be prompted for your Windows account password if you chose
   "Run whether user is logged on or not".

### Testing the registration

Right-click the new task -> **Run**. Then check the newest file in
`logs\` at the worktree root to confirm both pipelines ran and exited 0.
You can also check Task Scheduler's own "Last Run Result" column (`0x0` /
`The operation completed successfully` = success).

## Notes / things that can bite you

- **Long runtime is expected.** Pipeline 3 synthesizes one profile per known
  player, each a CPU-bound Ollama call that can take several minutes
  (`PROFILE_OLLAMA_TIMEOUT` in `pipeline/config.py` defaults to 600s per
  call). A run across several players can take well over an hour. Don't
  schedule anything else that competes for CPU/Ollama in the same window.
- **Idempotent either way.** Both pipelines are safe to re-run or to run
  twice in one night (e.g. a manual test run plus the scheduled one) —
  Pipeline 2's DynamoDB writes use deterministic sort keys, and Pipeline 3
  overwrites each player's profile at a stable S3/MinIO key. No duplicate
  data results from an extra run.
- **The `logs\` directory is local-only.** It is not part of the pipeline
  package and isn't covered by the existing `.gitignore` `*.log` rule by
  directory, but matches the `*.log` glob already in `.gitignore`, so these
  files won't get committed by accident.
