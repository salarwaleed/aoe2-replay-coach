"""Corpus-wide ownership-inference survey. READ-ONLY. Outputs to this folder."""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, r"C:\Users\salar\AppData\Local\Temp\claude\D--my-portfolio-discord-bot\92922a63-4aa8-4ca1-ac2a-df335b325320\scratchpad\corpus_survey")
sys.path.insert(0, r"D:\my-portfolio\discord bot")

import walk
from pipeline.replay_parser import resolve_players, resolve_player_civs
from pipeline.config import SAVEGAME_PATHS

OUT_DIR = r"C:\Users\salar\AppData\Local\Temp\claude\D--my-portfolio-discord-bot\92922a63-4aa8-4ca1-ac2a-df335b325320\scratchpad\corpus_survey"

# Actions whose legacy payload reliably carries BOTH player_id and object_ids
# (per mission's established facts) -> ledger claim sources.
CLAIM_SOURCES = ["ORDER", "MOVE", "WALL", "DELETE", "FORMATION"]
# Actions that carry player_id only (no useful object_ids) - not claim sources
# but still useful to note.
PLAYERID_ONLY = ["BUILD", "FLARE", "TRIBUTE", "DE_TRIBUTE", "BUY", "SELL", "RESIGN", "GAME"]
# Actions with object_ids but NO player_id - attribution targets.
QUEUE_ACTIONS = ["QUEUE", "MULTIQUEUE"]
NO_PLAYERID_OBJIDS = ["GATHER_POINT", "STANCE", "STOP", "FOLLOW", "GUARD",
                      "ATTACK_GROUND", "UNGARRISON", "REPAIR"]


def find_mgz_files():
    files = []
    for base in SAVEGAME_PATHS:
        if not os.path.isdir(base):
            continue
        for fn in sorted(os.listdir(base)):
            if fn.lower().endswith(".mgz"):
                files.append(os.path.join(base, fn))
    return files


def build_ledger_and_attribute(records):
    """Replicates the sampled-probe ledger mechanism.

    1. Walk claim-source actions (ORDER, MOVE, WALL, DELETE, FORMATION) in
       order; for each object_id in payload['object_ids'], record a claim by
       payload['player_id']. If a later claim on the same object_id names a
       DIFFERENT player, that's a conflict -> discard the id (mark as
       'conflicted', unattributable going forward).
    2. Attribute QUEUE/MULTIQUEUE via their building object_id(s) against the
       ledger.

    Returns a dict with:
        ledger: {obj_id: player_id}   (post-conflict-resolution)
        conflicts: list of (obj_id, first_player, new_player, source_action, t_ms)
        claim_source_counts: Counter of claim source -> #(obj_id, player) claim events
        queue_total, queue_attributed, queue_attributed_by_source (n/a — building id owner's source)
    """
    ledger: dict[int, int] = {}
    conflicted: set[int] = set()
    conflicts = []
    claim_source_counts = Counter()
    # Track, for each obj_id ultimately in the ledger, which action type FIRST
    # established the (winning) claim - for the "claim-source breakdown".
    claim_winner_source: dict[int, str] = {}

    for rec in records:
        if not rec["known"] or rec["payload"] is None:
            continue
        name = rec["action_name"]
        if name not in CLAIM_SOURCES:
            continue
        payload = rec["payload"]
        pid = payload.get("player_id")
        obj_ids = payload.get("object_ids") or []
        if pid is None:
            continue
        for oid in obj_ids:
            if oid is None or oid == 0:
                continue
            claim_source_counts[name] += 1
            if oid in conflicted:
                continue
            if oid in ledger:
                if ledger[oid] != pid:
                    conflicts.append({
                        "obj_id": oid,
                        "first_player": ledger[oid],
                        "new_player": pid,
                        "source_action": name,
                        "t_ms": rec["t_ms"],
                    })
                    conflicted.add(oid)
                    del ledger[oid]
                    claim_winner_source.pop(oid, None)
                # else: same player re-claiming, fine, no-op
            else:
                ledger[oid] = pid
                claim_winner_source[oid] = name

    # Now attribute QUEUE / MULTIQUEUE.
    queue_total = 0
    queue_attributed = 0
    queue_attr_source_breakdown = Counter()  # which claim-source originally attributed the building
    unattributed_building_ids = Counter()

    for rec in records:
        if not rec["known"] or rec["payload"] is None:
            continue
        name = rec["action_name"]
        if name not in QUEUE_ACTIONS:
            continue
        queue_total += 1
        payload = rec["payload"]
        obj_ids = payload.get("object_ids") or []
        attributed_player = None
        source = None
        for oid in obj_ids:
            if oid in ledger:
                attributed_player = ledger[oid]
                source = claim_winner_source.get(oid, "?")
                break
        if attributed_player is not None:
            queue_attributed += 1
            queue_attr_source_breakdown[source] += 1
        else:
            for oid in obj_ids:
                unattributed_building_ids[oid] += 1

    return {
        "ledger": ledger,
        "conflicts": conflicts,
        "claim_source_counts": claim_source_counts,
        "queue_total": queue_total,
        "queue_attributed": queue_attributed,
        "queue_attr_source_breakdown": queue_attr_source_breakdown,
        "unattributed_building_ids": unattributed_building_ids,
        "n_claims": sum(claim_source_counts.values()),
    }


def main():
    files = find_mgz_files()
    print(f"Found {len(files)} .mgz files", file=sys.stderr)

    per_file = []
    unknown_action_hist = Counter()  # action_id -> count across corpus
    unknown_action_samples = defaultdict(list)  # action_id -> list of (file, t_ms, raw_bytes hex, len)

    gather_point_events_all = []  # for investigation (b)
    tc_investigation_rows = []    # for investigation (c)

    skipped = []

    for path in files:
        fn = os.path.basename(path)
        try:
            records, total_ms, ops, pg_dur, pg_complete = walk.walk_body(path)
        except walk.UnreadableReplay as exc:
            skipped.append({"file": fn, "reason": str(exc)})
            print(f"SKIP {fn}: {exc}", file=sys.stderr)
            continue
        except Exception as exc:
            skipped.append({"file": fn, "reason": f"unexpected: {exc}"})
            print(f"SKIP {fn}: unexpected {exc}", file=sys.stderr)
            continue

        try:
            players = resolve_players(path)
            civs = resolve_player_civs(path)
        except Exception as exc:
            players = {}
            civs = {}

        n_players_named = sum(1 for pid, nm in players.items() if not nm.startswith("Player "))
        # actual n players in game -- infer from civs dict (has entries only for real slots) as backup
        n_players_est = max(len(civs), n_players_named) if civs or n_players_named else None

        duration_ms = pg_dur if pg_dur else total_ms

        result = build_ledger_and_attribute(records)

        # unknown action id histogram + samples
        for rec in records:
            if not rec["known"]:
                aid = rec["action_id"]
                unknown_action_hist[aid] += 1
                if len(unknown_action_samples[aid]) < 6:
                    unknown_action_samples[aid].append({
                        "file": fn,
                        "t_ms": rec["t_ms"],
                        "hex": rec["raw_bytes"].hex(),
                        "len": len(rec["raw_bytes"]),
                    })

        # stash records + ledger context temporarily for investigations b/c (in-memory, not written)
        per_file.append({
            "file": fn,
            "duration_ms": duration_ms,
            "n_players": n_players_est,
            "players": players,
            "civs": civs,
            "queue_total": result["queue_total"],
            "queue_attributed": result["queue_attributed"],
            "pct_attributed": (100.0 * result["queue_attributed"] / result["queue_total"]) if result["queue_total"] else None,
            "n_claims": result["n_claims"],
            "n_conflicts": len(result["conflicts"]),
            "claim_source_counts": dict(result["claim_source_counts"]),
            "queue_attr_source_breakdown": dict(result["queue_attr_source_breakdown"]),
            "conflicts_detail": result["conflicts"][:10],
            "_records": records,   # keep for investigation b/c below (dropped before json dump)
            "_ledger": result["ledger"],
        })

    # ---- Investigation (b): GATHER_POINT temporal adjacency to claim-source commands ----
    adjacency_report = investigate_gather_point_adjacency(per_file)

    # ---- Investigation (c): first-TC object id pattern ----
    tc_report = investigate_first_tc(per_file)

    # Build final per-file table (drop heavy _records/_ledger before dumping)
    per_file_public = []
    for row in per_file:
        r = {k: v for k, v in row.items() if not k.startswith("_")}
        per_file_public.append(r)

    # Aggregate
    pcts = [r["pct_attributed"] for r in per_file_public if r["pct_attributed"] is not None]
    total_queue = sum(r["queue_total"] for r in per_file_public)
    total_attr = sum(r["queue_attributed"] for r in per_file_public)
    total_conflicts = sum(r["n_conflicts"] for r in per_file_public)
    claim_source_totals = Counter()
    for r in per_file_public:
        claim_source_totals.update(r["claim_source_counts"])

    aggregate = {
        "n_files_found": len(files),
        "n_files_readable": len(per_file_public),
        "n_files_skipped": len(skipped),
        "skipped": skipped,
        "overall_pct_attributed": (100.0 * total_attr / total_queue) if total_queue else None,
        "total_queue_actions": total_queue,
        "total_attributed": total_attr,
        "pct_min": min(pcts) if pcts else None,
        "pct_median": sorted(pcts)[len(pcts)//2] if pcts else None,
        "pct_max": max(pcts) if pcts else None,
        "total_conflicts_corpus_wide": total_conflicts,
        "claim_source_totals": dict(claim_source_totals),
        "unknown_action_hist": dict(unknown_action_hist.most_common()),
    }

    out = {
        "per_file": per_file_public,
        "aggregate": aggregate,
        "unknown_action_samples": {str(k): v for k, v in unknown_action_samples.items()},
        "gather_point_adjacency": adjacency_report,
        "first_tc": tc_report,
    }

    with open(os.path.join(OUT_DIR, "survey_results.json"), "w") as f:
        json.dump(out, f, indent=2, default=str)

    print("WROTE", os.path.join(OUT_DIR, "survey_results.json"), file=sys.stderr)
    print(json.dumps(aggregate, indent=2, default=str))


def investigate_gather_point_adjacency(per_file):
    """GATHER_POINT's own payload structure (legacy parse_action):
        object_ids = [the producing BUILDING's object id]   (selection == the building)
        target_id  = the rally-point target (another object, or -1 if a bare tile)

    So GATHER_POINT's object_ids land in the SAME id-space we are trying to
    attribute for QUEUE/MULTIQUEUE (the producing building). The natural
    adjacency signal is therefore: does an ORDER action's `target_id` field
    (built-in receiver of intent, e.g. "villager ordered to garrison/repair
    building X") equal this same building id within a small time window? That
    ORDER carries a real player_id. We test that specific adjacency, and
    separately keep the original "shared object_ids with a claim-source event"
    test for completeness (it was tried first and found to add ~0 coverage,
    which is retained below for transparency).
    """
    WINDOW_MS = 2000
    total_gp = 0
    gp_building_ids_total = 0
    gp_covered_via_order_target = 0
    added_new_ledger_coverage = 0
    contradictions = 0
    examples = []

    # legacy shared-object_ids adjacency (as originally specified) — kept for comparison
    legacy_total_gp = 0
    legacy_with_adjacent_claim = 0

    for row in per_file:
        records = row["_records"]
        ledger = row["_ledger"]

        claim_events = []
        order_target_events = []  # (t_ms, player_id, target_id)
        for rec in records:
            if not rec["known"] or not rec["payload"]:
                continue
            if rec["action_name"] in CLAIM_SOURCES:
                pid = rec["payload"].get("player_id")
                oids = set(rec["payload"].get("object_ids") or [])
                if pid is not None:
                    claim_events.append((rec["t_ms"], pid, oids))
            if rec["action_name"] == "ORDER":
                pid = rec["payload"].get("player_id")
                tid = rec["payload"].get("target_id")
                if pid is not None and tid is not None and tid > 0:
                    order_target_events.append((rec["t_ms"], pid, tid))

        claim_events.sort(key=lambda x: x[0])
        order_target_events.sort(key=lambda x: x[0])

        gp_events = [rec for rec in records if rec["known"] and rec["action_name"] == "GATHER_POINT" and rec["payload"]]
        total_gp += len(gp_events)
        legacy_total_gp += len(gp_events)

        for gp in gp_events:
            gp_t = gp["t_ms"]
            gp_oids = set(gp["payload"].get("object_ids") or [])
            if not gp_oids:
                continue
            gp_building_ids_total += len(gp_oids)

            # --- legacy shared-object_ids test ---
            legacy_candidates = [(t, pid, oids) for (t, pid, oids) in claim_events
                                  if abs(t - gp_t) <= 250 and (oids & gp_oids)]
            if legacy_candidates:
                legacy_with_adjacent_claim += 1

            # --- ORDER.target_id == GATHER_POINT building id, within window ---
            hit_players = set()
            for (t, pid, tid) in order_target_events:
                if abs(t - gp_t) > WINDOW_MS:
                    continue
                if tid in gp_oids:
                    hit_players.add(pid)
            if hit_players:
                gp_covered_via_order_target += 1
                already_ledgered = [oid for oid in gp_oids if oid in ledger]
                if already_ledgered:
                    ledger_players = {ledger[oid] for oid in already_ledgered}
                    if not (ledger_players & hit_players):
                        contradictions += 1
                        if len(examples) < 8:
                            examples.append({
                                "file": row["file"], "t_ms": gp_t,
                                "gp_building_ids": list(gp_oids)[:5],
                                "order_target_players_nearby": list(hit_players),
                                "ledger_player_for_same_ids": {oid: ledger[oid] for oid in already_ledgered},
                            })
                else:
                    added_new_ledger_coverage += 1

    return {
        "window_ms": WINDOW_MS,
        "total_gather_point_actions": total_gp,
        "legacy_shared_objid_test": {
            "window_ms": 250,
            "total": legacy_total_gp,
            "with_adjacent_identity_claim": legacy_with_adjacent_claim,
            "pct": (100.0 * legacy_with_adjacent_claim / legacy_total_gp) if legacy_total_gp else None,
        },
        "order_target_id_test": {
            "gp_events_with_building_covered_by_nearby_order_target": gp_covered_via_order_target,
            "pct_of_gp_events": (100.0 * gp_covered_via_order_target / total_gp) if total_gp else None,
            "of_those_new_ledger_coverage_not_already_present": added_new_ledger_coverage,
            "contradictions_vs_existing_ledger": contradictions,
            "contradiction_examples": examples,
        },
    }


def investigate_first_tc(per_file):
    """Check whether starting-TC object ids follow a predictable pattern.

    Approach per file:
      - Find earliest QUEUE/MULTIQUEUE actions (by t_ms) whose unit_id looks
        like a villager (id 83 = Male Villager / 293 also common; we'll just
        take the earliest N distinct building object_ids referenced by ANY
        QUEUE/MULTIQUEUE in the first 60s of game time, ranked by first
        appearance time) - these are candidate starting TCs, one per player.
      - Cross-reference against the ledger: if the ledger already attributes
        that building id to a player (via ORDER/MOVE/WALL/DELETE/FORMATION
        touching it later), record the (obj_id -> player) mapping as ground
        truth where available.
      - Look for arithmetic patterns among the recovered obj_ids (sequential,
        constant offset, sorted-matches-slot-order, etc.)
    """
    EARLY_WINDOW_MS = 90_000  # first 90s - post-imperial games, TC queue starts immediately
    rows = []

    for row in per_file:
        records = row["_records"]
        ledger = row["_ledger"]

        # first-seen building object id (for QUEUE/MULTIQUEUE) within early window,
        # in order of first appearance
        first_seen: dict[int, int] = {}  # obj_id -> t_ms of first queue action referencing it
        for rec in records:
            if not rec["known"] or not rec["payload"]:
                continue
            if rec["action_name"] not in QUEUE_ACTIONS:
                continue
            if rec["t_ms"] > EARLY_WINDOW_MS:
                continue
            for oid in (rec["payload"].get("object_ids") or []):
                if oid and oid not in first_seen:
                    first_seen[oid] = rec["t_ms"]

        candidate_tcs = sorted(first_seen.items(), key=lambda kv: kv[1])
        # ledger agreement for these candidates
        ledger_hits = {oid: ledger.get(oid) for oid, _ in candidate_tcs if oid in ledger}

        rows.append({
            "file": row["file"],
            "n_players": row["n_players"],
            "candidate_building_ids_by_first_queue_order": candidate_tcs[:10],
            "ledger_agreement": ledger_hits,
        })

    # Look across files for arithmetic pattern in the SORTED candidate id sets
    # (e.g. does candidate #1 always look like base+0, candidate #2 base+1, etc.)
    all_first_ids = []
    for r in rows:
        ids_sorted_by_time = [oid for oid, _ in r["candidate_building_ids_by_first_queue_order"]]
        all_first_ids.append({"file": r["file"], "ids_by_time": ids_sorted_by_time})

    return {
        "early_window_ms": EARLY_WINDOW_MS,
        "per_file_candidates": rows,
        "raw_id_sequences": all_first_ids,
    }


if __name__ == "__main__":
    main()
