"""Pipeline 3 orchestrator — DynamoDB timelines -> LLM synthesis -> S3 profiles.

Pulls a player's attributed timeline events (``player_id != -1``) across all
matches they appear in from ``match_timelines`` (DynamoDB), feeds the
chronological event sentences to a local Ollama model for strategic
synthesis, and stores the resulting profile (both ``.json`` and ``.md``) in
an S3-compatible bucket (MinIO locally, real S3 in prod — see
``pipeline/s3_store.py``).

Run
---
    docker compose -f infra/docker-compose.yml up -d   # + minio
    pip install -r pipeline/requirements.txt
    ollama pull qwen2.5:7b                              # one-time, ~4-5 GB

    python -m pipeline.pipeline3_profiles "Player 1"    # one player
    python -m pipeline.pipeline3_profiles --all         # every known player
    python -m pipeline.pipeline3_profiles --list         # just list known names

Idempotent in the sense that profiles are stored at stable keys
(``profiles/{player_name}/profile.{json,md}``) — re-running for a player
simply overwrites their profile with a fresh synthesis. There is NO
deterministic fallback if Ollama / the configured model isn't ready: this
pipeline raises a clear error and exits non-zero rather than fabricating a
profile (see ``profile_synth.OllamaNotReadyError``).
"""

from __future__ import annotations

import argparse
import sys

from .config import DYNAMODB_TABLE_NAME, UNATTRIBUTED_PLAYER_ID
from .dynamo_store import _connect_table
from .profile_synth import (
    OllamaNotReadyError,
    ollama_profile_model_ready,
    profile_to_markdown,
    synthesize_profile,
)
from .s3_store import ensure_bucket, put_profile


# ─────────────────────────────────────────────────────────────────────────────
# DynamoDB queries
# ─────────────────────────────────────────────────────────────────────────────
def list_known_player_names(table) -> list[str]:
    """Scan the whole table and return the distinct attributed player names.

    A full scan is acceptable here: this table holds one demo dataset's worth
    of replay events, not a production-scale workload, and pipeline 3 runs
    on-demand (not per-request). Excludes the "Unattributed" sentinel rows
    (player_id == UNATTRIBUTED_PLAYER_ID).
    """
    names: set[str] = set()
    scan_kwargs: dict = {
        "ProjectionExpression": "player_id, player_name",
    }
    while True:
        resp = table.scan(**scan_kwargs)
        for item in resp.get("Items", []):
            if int(item.get("player_id", UNATTRIBUTED_PLAYER_ID)) != UNATTRIBUTED_PLAYER_ID:
                names.add(item["player_name"])
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key
    return sorted(names)


def fetch_player_events(table, player_name: str) -> list[dict]:
    """Scan for all attributed events belonging to ``player_name``, across
    every match. Returns items sorted chronologically across matches by
    ``t_ms`` (NOT globally meaningful across different matches' clocks, but
    gives a stable, readable per-match-then-time ordering for the prompt:
    sorted by (match_id, t_ms) so each match's events stay contiguous and in
    order, which is what a human reading a "career log" would expect).

    A full table scan + filter is used rather than a GSI on player_name —
    fine at this dataset's scale; see ``list_known_player_names`` docstring.
    """
    items: list[dict] = []
    scan_kwargs: dict = {
        "FilterExpression": "player_name = :pn AND player_id <> :unattrib",
        "ExpressionAttributeValues": {
            ":pn": player_name,
            ":unattrib": UNATTRIBUTED_PLAYER_ID,
        },
    }
    while True:
        resp = table.scan(**scan_kwargs)
        items.extend(resp.get("Items", []))
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key

    items.sort(key=lambda it: (str(it["match_id"]), int(it["t_ms"])))
    return items


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────────────
def build_profile_for_player(table, s3_client, player_name: str) -> dict:
    """Pull events, synthesize, and store a profile for one player.

    Returns a small summary dict for the run report. Raises
    ``ValueError`` if the player has no attributed events, or
    ``OllamaNotReadyError`` if the LLM isn't available (propagated to the
    caller, which decides how to report it).
    """
    events = fetch_player_events(table, player_name)
    if not events:
        raise ValueError(f"No attributed events found for player '{player_name}'.")

    sentences = [ev["sentence"] for ev in events]
    n_matches = len({str(ev["match_id"]) for ev in events})

    profile = synthesize_profile(player_name, sentences, n_matches)
    markdown_text = profile_to_markdown(profile)

    json_key, md_key = put_profile(player_name, profile, markdown_text, client=s3_client)

    return {
        "player_name": player_name,
        "n_matches": n_matches,
        "n_events": len(events),
        "json_key": json_key,
        "md_key": md_key,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("player_name", nargs="?", help="Build a profile for this one player.")
    group.add_argument(
        "--all", action="store_true", help="Build profiles for every known attributed player name."
    )
    group.add_argument(
        "--list", action="store_true", help="Just list known attributed player names and exit."
    )
    args = parser.parse_args(argv)

    if not args.player_name and not args.all and not args.list:
        parser.error("Provide a player name, or use --all / --list.")

    table = _connect_table()

    if args.list:
        names = list_known_player_names(table)
        print(f"Known attributed player names in '{DYNAMODB_TABLE_NAME}' ({len(names)}):")
        for name in names:
            print(f"  - {name}")
        return 0

    ready, message = ollama_profile_model_ready()
    if ready:
        print(f"[llm] {message}")
    else:
        print(f"[llm] NOT READY: {message}")
        print(
            "\nProfile synthesis requires the LLM (no deterministic fallback exists "
            "for this task). Re-run this command once the model is ready."
        )
        return 1

    ensure_bucket()
    s3_client = None  # let s3_store build/reuse its own client per call

    if args.all:
        targets = list_known_player_names(table)
        if not targets:
            print("No attributed player names found in DynamoDB.")
            return 0
    else:
        targets = [args.player_name]

    print(f"Building profile(s) for {len(targets)} player(s): {targets}\n")

    results = []
    failures = []
    for name in targets:
        try:
            summary = build_profile_for_player(table, s3_client, name)
            results.append(summary)
            print(
                f"  OK {name}: {summary['n_events']} event(s) across "
                f"{summary['n_matches']} match(es) -> "
                f"s3://{summary['json_key']}, s3://{summary['md_key']}"
            )
        except OllamaNotReadyError as exc:
            # Propagate immediately: if the model dropped out mid-run there's
            # no point grinding through the rest of the targets.
            print(f"\n[llm] Ollama became unavailable mid-run: {exc}")
            return 1
        except ValueError as exc:
            failures.append((name, str(exc)))
            print(f"  SKIP {name}: {exc}")

    print("\n" + "=" * 60)
    print(f"Profiles written : {len(results)}")
    print(f"Skipped          : {len(failures)}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
