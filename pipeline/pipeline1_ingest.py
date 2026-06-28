"""Pipeline 1 orchestrator — raw .mgz ingestion into ChromaDB.

Scans the configured SaveGame folder(s) for ``.mgz`` replays, parses each into a
per-player technical event timeline, renders the events as raw log lines, chunks
them into fixed windows, and upserts each chunk into a Dockerized ChromaDB
collection as a tagged staging queue (``processed: False``) for a later
synthesis pipeline.

Run
---
    docker compose -f infra/docker-compose.yml up -d   # start ChromaDB
    pip install -r pipeline/requirements.txt
    python -m pipeline.pipeline1_ingest

The collection uses ChromaDB's default embedding function (all-MiniLM-L6-v2,
bundled — no API key required).
"""

from __future__ import annotations

import glob
import os
import sys
from datetime import datetime, timezone

from . import dat_ids
from .config import (
    CHROMA_HOST,
    CHROMA_PORT,
    CHUNK_SIZE,
    COLLECTION_NAME,
    SAVEGAME_PATHS,
    UNATTRIBUTED_PLAYER_ID,
    UNREADABLE_FILES,
)
from .replay_parser import UnreadableReplay, parse_match_timeline


# ─────────────────────────────────────────────────────────────────────────────
# Rendering
# ─────────────────────────────────────────────────────────────────────────────
def render_event_line(event: dict) -> str:
    """Render one timeline event as a single raw technical log line.

    Example::

        t=04:15 p=1 BUILD Watch Tower(id=79) [DEF]
        t=06:02 p=? QUEUE Knight(id=38) amount=3 [MIL]
        t=10:30 p=1 TRIBUTE to=2 gold=100.0

    Unattributed actions (QUEUE/MULTIQUEUE/etc., which carry no player id in the
    Voobly format) render as ``p=?``.
    """
    pid = event["player_id"]
    pid_str = "?" if pid == UNATTRIBUTED_PLAYER_ID else str(pid)
    parts = [f"t={event['t_str']}", f"p={pid_str}", event["action"]]

    if event["obj_id"] is not None:
        parts.append(f"{event['obj_name']}(id={event['obj_id']})")
        tag = dat_ids.category_tag(event["category"])
        parts.append(f"[{tag}]")

    extras = event.get("extras") or {}
    for key, value in extras.items():
        parts.append(f"{key}={value}")

    return " ".join(str(p) for p in parts)


def chunk_events(events: list[dict], size: int) -> list[list[dict]]:
    """Split a player's (time-ordered) events into windows of ``size``."""
    return [events[i : i + size] for i in range(0, len(events), size)]


def group_by_player(events: list[dict]) -> dict[int, list[dict]]:
    """Group a match's events by player id, preserving time order."""
    by_player: dict[int, list[dict]] = {}
    for ev in events:
        by_player.setdefault(ev["player_id"], []).append(ev)
    return by_player


# ─────────────────────────────────────────────────────────────────────────────
# ChromaDB
# ─────────────────────────────────────────────────────────────────────────────
def _connect_collection():
    """Connect to ChromaDB and return the staging collection.

    Raises a clear, friendly error (not a raw traceback) if the server is
    unreachable — almost always because the Docker container is not running.
    """
    try:
        import chromadb
    except ImportError as exc:  # pragma: no cover - environment guard
        raise SystemExit(
            "chromadb is not installed. Run:\n"
            "    pip install -r pipeline/requirements.txt"
        ) from exc

    try:
        client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        # Force an actual round-trip so connection failures surface here.
        client.heartbeat()
    except Exception as exc:
        raise SystemExit(
            f"\nERROR: could not reach ChromaDB at {CHROMA_HOST}:{CHROMA_PORT}.\n"
            "Is the Docker container up? Start it with:\n"
            "    docker compose -f infra/docker-compose.yml up -d\n"
            f"(underlying error: {type(exc).__name__}: {exc})"
        ) from exc

    # Uses Chroma's default embedding function (all-MiniLM-L6-v2, bundled).
    return client.get_or_create_collection(COLLECTION_NAME)


# ─────────────────────────────────────────────────────────────────────────────
# Ingestion
# ─────────────────────────────────────────────────────────────────────────────
def discover_replays() -> list[str]:
    """Return all ``.mgz`` paths under the configured folders, sorted+deduped."""
    files: list[str] = []
    for folder in SAVEGAME_PATHS:
        files.extend(glob.glob(os.path.join(folder, "*.mgz")))
    return sorted(set(files))


def ingest_match(collection, match: dict, ingested_at: str) -> int:
    """Upsert all of one match's player chunks into the collection.

    Returns the number of chunks upserted.
    """
    match_id = match["match_id"]
    players = match["players"]
    by_player = group_by_player(match["events"])

    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict] = []

    for player_id, p_events in sorted(by_player.items()):
        if player_id == UNATTRIBUTED_PLAYER_ID:
            player_name = "Unattributed"
        else:
            player_name = players.get(player_id, f"Player {player_id}")
        for chunk_idx, chunk in enumerate(chunk_events(p_events, CHUNK_SIZE)):
            lines = [render_event_line(ev) for ev in chunk]
            chunk_text = "\n".join(lines)
            ids.append(f"{match_id}:{player_id}:{chunk_idx}")
            documents.append(chunk_text)
            metadatas.append(
                {
                    "match_id": match_id,
                    "player_id": player_id,
                    "player_name": player_name,
                    "t_start_ms": chunk[0]["t_ms"],
                    "t_end_ms": chunk[-1]["t_ms"],
                    "n_events": len(chunk),
                    "processed": False,
                    "ingested_at": ingested_at,
                }
            )

    if ids:
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
    return len(ids)


def main() -> int:
    """Entry point: parse all replays and stage them in ChromaDB."""
    collection = _connect_collection()

    files = discover_replays()
    if not files:
        print(
            "No .mgz files found under:\n  "
            + "\n  ".join(SAVEGAME_PATHS)
        )
        return 0

    ingested_at = datetime.now(timezone.utc).isoformat()
    parsed = 0
    skipped = 0
    total_chunks = 0

    print(f"Discovered {len(files)} replay file(s).\n")

    for path in files:
        name = os.path.basename(path)
        if name in UNREADABLE_FILES:
            print(f"  SKIP (known-unreadable): {name}")
            skipped += 1
            continue
        try:
            match = parse_match_timeline(path)
        except UnreadableReplay as exc:
            print(f"  SKIP (unreadable): {exc}")
            skipped += 1
            continue
        except Exception as exc:  # defensive: never let one file abort the run
            print(f"  SKIP (error {type(exc).__name__}): {name}: {exc}")
            skipped += 1
            continue

        n_chunks = ingest_match(collection, match, ingested_at)
        total_chunks += n_chunks
        parsed += 1
        dur_min = match["duration_ms"] / 60000
        print(
            f"  OK {name}: {dur_min:.1f}m, "
            f"{len(match['events'])} events -> {n_chunks} chunks"
        )

    print("\n" + "=" * 60)
    print(f"Files parsed   : {parsed}")
    print(f"Files skipped  : {skipped}")
    print(f"Chunks upserted: {total_chunks}")
    try:
        print(f"Collection count: {collection.count()}")
    except Exception as exc:  # pragma: no cover
        print(f"Collection count: <unavailable: {exc}>")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
