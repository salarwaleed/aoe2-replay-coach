"""Pipeline 2 orchestrator — raw chunks -> event sentences -> DynamoDB timeline.

Pulls ``processed: false`` chunks staged by Pipeline 1 in ChromaDB, rewrites
each chunk's raw log lines into chronological event sentences (via a local
Ollama model, falling back to a deterministic template renderer if Ollama
isn't reachable or has no model installed), writes the structured timeline to
DynamoDB, and flips those chunks to ``processed: true`` in ChromaDB.

Run
---
    docker compose -f infra/docker-compose.yml up -d   # chromadb + dynamodb-local
    pip install -r pipeline/requirements.txt
    python -m pipeline.pipeline2_telemetry [--limit N]

Idempotent: DynamoDB sort keys are deterministic (time + player + seq within
a chunk), so re-running on the same chunk overwrites the same items rather
than duplicating them. ChromaDB's ``processed`` flag is only flipped after a
chunk's events are durably written, so a crash mid-run just leaves that
chunk's flag at ``false`` for the next run to pick up again.
"""

from __future__ import annotations

import argparse
import sys

from .config import CHROMA_HOST, CHROMA_PORT, COLLECTION_NAME
from .dynamo_store import _connect_table, put_events
from .llm_extract import extract_sentences, ollama_is_ready


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
        client.heartbeat()
    except Exception as exc:
        raise SystemExit(
            f"\nERROR: could not reach ChromaDB at {CHROMA_HOST}:{CHROMA_PORT}.\n"
            "Is the Docker container up? Start it with:\n"
            "    docker compose -f infra/docker-compose.yml up -d\n"
            f"(underlying error: {type(exc).__name__}: {exc})"
        ) from exc

    return client.get_or_create_collection(COLLECTION_NAME)


def fetch_unprocessed_chunks(collection, limit: int | None) -> dict:
    """Return up to ``limit`` chunks with metadata ``processed: False``."""
    kwargs = {"where": {"processed": False}, "include": ["documents", "metadatas"]}
    if limit is not None:
        kwargs["limit"] = limit
    return collection.get(**kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────────────
def process_chunk(chunk_id: str, raw_text: str, meta: dict, use_ollama: bool) -> tuple[list[dict], str]:
    """Extract sentences for one chunk and shape them as DynamoDB items.

    Returns ``(events, path_used)``.
    """
    pairs, path_used = extract_sentences(raw_text, use_ollama=use_ollama)

    events: list[dict] = []
    for ev, sentence in pairs:
        events.append(
            {
                "t_ms": ev.t_ms,
                "t_str": ev.t_str,
                # Prefer the per-line player id (matters for chunks where a
                # line is individually attributed) but fall back to the
                # chunk's metadata player id/name for consistency.
                "player_id": ev.player_id,
                "player_name": meta.get("player_name", "Unknown"),
                "action": ev.action,
                "obj_name": ev.obj_name,
                "category": ev.category_tag,
                "sentence": sentence,
                "source_chunk_id": chunk_id,
            }
        )
    return events, path_used


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N unprocessed chunks (default: all).",
    )
    args = parser.parse_args(argv)

    collection = _connect_collection()
    table = _connect_table()

    ready, message = ollama_is_ready()
    if ready:
        print(f"[llm] {message} Using Ollama for sentence extraction.")
    else:
        print(f"[llm] {message}")
        print("[llm] Falling back to the deterministic template renderer.")

    result = fetch_unprocessed_chunks(collection, args.limit)
    ids = result.get("ids", [])
    documents = result.get("documents", [])
    metadatas = result.get("metadatas", [])

    if not ids:
        print("No unprocessed chunks found.")
        return 0

    print(f"Found {len(ids)} unprocessed chunk(s).\n")

    path_counts: dict[str, int] = {"ollama": 0, "fallback": 0}
    total_events = 0
    processed_chunk_ids: list[str] = []
    matches_touched: set[str] = set()

    for chunk_id, raw_text, meta in zip(ids, documents, metadatas):
        match_id = meta["match_id"]
        events, path_used = process_chunk(chunk_id, raw_text, meta, use_ollama=ready)
        path_counts[path_used] += 1

        n_written = put_events(table, match_id, events)
        total_events += n_written
        matches_touched.add(match_id)
        processed_chunk_ids.append(chunk_id)

        print(
            f"  OK {chunk_id}: {len(events)} event(s) -> {n_written} item(s) "
            f"written [{path_used}]"
        )

    # Flip processed=true only after the corresponding DynamoDB writes
    # succeeded, so a crash mid-run leaves unfinished chunks at false for the
    # next run to retry.
    if processed_chunk_ids:
        collection.update(
            ids=processed_chunk_ids,
            metadatas=[{"processed": True} for _ in processed_chunk_ids],
        )

    print("\n" + "=" * 60)
    print(f"Chunks processed   : {len(processed_chunk_ids)}")
    print(f"Matches touched    : {len(matches_touched)}")
    print(f"DynamoDB items     : {total_events}")
    print(f"Extraction path    : ollama={path_counts['ollama']}, fallback={path_counts['fallback']}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
