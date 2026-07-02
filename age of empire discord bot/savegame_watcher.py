"""In-bot "daytime capture" watcher (TELEMETRY_PLAN.md §2, stage ①).

A background `discord.ext.tasks.loop` that periodically re-runs Pipeline 1's
ingestion (`pipeline.pipeline1_ingest`) so new `.mgz` replays dropped into
SAVEGAME_PATHS get staged into ChromaDB while the bot is running, with no
manual step required.

Design notes
------------
- Pipeline 1's ingestion is idempotent (upserts by deterministic chunk id —
  see `pipeline1_ingest.ingest_match`), so the simplest robust approach is to
  just re-invoke its `main()` on a timer rather than writing new file-diffing
  logic. Re-ingesting unchanged files is cheap (no-op upserts).
- `pipeline` is a *sibling* package to this file's directory (both live under
  the worktree root), and the bot is launched with cwd set to this directory
  (see `run_bot.bat`), so the worktree root is NOT on `sys.path` by default.
  `_ensure_pipeline_importable()` adds it before the first import.
- `pipeline1_ingest._connect_collection()` raises `SystemExit` (a
  BaseException, not Exception) if ChromaDB is unreachable. Left uncaught,
  that would kill the whole bot process from inside the loop. Every cycle is
  wrapped in `except BaseException` and logged instead of propagating, and a
  `tasks.loop` `error` handler is wired up as a second safety net.
- This module is intentionally self-contained: importing it has no side
  effects beyond the sys.path adjustment above. Nothing here touches
  `profiles.json`, `_scan_recordings()`, or any existing Discord command —
  this is a wholly separate staging path feeding ChromaDB, not the legacy
  profile system.

Usage (wired into bot.py's on_ready — see the hook there)::

    from savegame_watcher import start_savegame_watcher
    start_savegame_watcher()
"""

from __future__ import annotations

import os
import sys
import traceback

from discord.ext import tasks

# Minutes between ingestion sweeps. Overridable via env var for testing
# (e.g. SAVEGAME_WATCH_INTERVAL_MINUTES=0.1 for a ~6s loop).
WATCH_INTERVAL_MINUTES: float = float(
    os.environ.get("SAVEGAME_WATCH_INTERVAL_MINUTES", "5")
)


def _ensure_pipeline_importable() -> None:
    """Put the worktree root (parent of this file's directory) on sys.path.

    `pipeline` is a sibling package one level up from
    `age of empire discord bot/`. The bot is normally launched with cwd
    already set to this directory (see run_bot.bat), so without this the
    `pipeline` package import below would fail with ModuleNotFoundError.
    Safe to call repeatedly — only inserts the path once.
    """
    this_dir = os.path.dirname(os.path.abspath(__file__))
    worktree_root = os.path.dirname(this_dir)
    if worktree_root not in sys.path:
        sys.path.insert(0, worktree_root)


_ensure_pipeline_importable()


# Sentinel: the sweep failed because a pipeline dependency (e.g. chromadb) is
# not installed in THIS Python environment. Unlike a transient outage this can
# never succeed on retry, so the loop disables itself instead of failing every
# cycle forever (which buried real errors in noise).
_MISSING_DEP = -99


def run_ingest_sweep() -> int:
    """Run one Pipeline 1 ingestion sweep synchronously.

    Returns Pipeline 1's exit code (0 on success), or _MISSING_DEP when the
    failure is an uninstalled dependency. Never raises — any error, including
    the SystemExit pipeline1_ingest raises when ChromaDB is unreachable, is
    caught and logged so a transient outage just skips this cycle instead of
    taking the bot down.
    """
    try:
        from pipeline.pipeline1_ingest import main as ingest_main

        return ingest_main()
    except BaseException as exc:  # noqa: BLE001 - intentional: see module docstring
        print(f"[savegame_watcher] ingestion sweep failed: {type(exc).__name__}: {exc}")
        if "not installed" in str(exc):
            return _MISSING_DEP
        return 1


@tasks.loop(minutes=WATCH_INTERVAL_MINUTES)
async def _savegame_watch_loop() -> None:
    """Periodic task: re-run Pipeline 1 ingestion on a background thread.

    Runs the (synchronous, blocking) ingestion via `loop.run_in_executor` so
    it never blocks the bot's event loop / heartbeats while parsing replays
    or talking to ChromaDB over HTTP.
    """
    import asyncio

    loop = asyncio.get_running_loop()
    code = await loop.run_in_executor(None, run_ingest_sweep)
    if code == _MISSING_DEP:
        print(
            "[savegame_watcher] disabled for this run: pipeline dependencies "
            "are not installed in the bot's Python. To enable in-bot "
            "ingestion, run:  pip install -r pipeline/requirements.txt  "
            "(with the bot's Python). Replays can still be ingested by "
            "running Pipeline 1 in its venv."
        )
        _savegame_watch_loop.stop()
        return
    status = "ok" if code == 0 else f"exit code {code}"
    print(f"[savegame_watcher] sweep complete ({status}).")


@_savegame_watch_loop.before_loop
async def _before_loop() -> None:
    # discord.ext.tasks requires the bot to be ready before a loop using
    # bot state starts; this loop doesn't touch bot/guild state, but waiting
    # keeps startup log output predictable (sweep messages appear after the
    # "online and ready" banner, not interleaved with login).
    pass


@_savegame_watch_loop.error
async def _on_loop_error(exc: BaseException) -> None:
    """Last-resort safety net: log and let the loop's auto-reconnect retry.

    discord.ext.tasks.Loop stops the loop on an unhandled exception unless
    `reconnect=True` (the default) lets it restart on the next tick for
    most exception types. We additionally never want a single bad sweep to
    look like a silent failure, so it's printed here with a traceback.
    """
    print("[savegame_watcher] background loop error:")
    traceback.print_exception(type(exc), exc, exc.__traceback__)


def start_savegame_watcher() -> None:
    """Start the periodic SaveGame ingestion loop if not already running.

    Safe to call multiple times (e.g. if on_ready fires again after a
    reconnect) — discord.ext.tasks.Loop.start() raises RuntimeError if
    already running, which is swallowed here.
    """
    if _savegame_watch_loop.is_running():
        return
    try:
        _savegame_watch_loop.start()
        print(
            f"[savegame_watcher] started: sweeping SaveGame folder(s) every "
            f"{WATCH_INTERVAL_MINUTES} minute(s)."
        )
    except RuntimeError:
        # Already running (race with a concurrent on_ready call) — fine.
        pass


def stop_savegame_watcher() -> None:
    """Stop the periodic loop (graceful — finishes the in-flight sweep)."""
    if _savegame_watch_loop.is_running():
        _savegame_watch_loop.stop()
