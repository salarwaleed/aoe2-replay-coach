"""Reference telemetry signals.

These two signals exist to prove the registry pattern end-to-end. They are real,
useful extractors drawn from the TELEMETRY_PLAN.md catalogue, but the point is
the *shape*: a pure function over the parsed ``events`` list, registered with the
``@register`` decorator, returning flat records — added without touching the
parser or the ingestion orchestrator.

Both are computed per player.
"""

from __future__ import annotations

from collections import defaultdict

from . import register

# Town Center building ids (see pipeline.dat_ids). 109 / 490 both appear in the
# v1.6 data as Town Center BUILD ids.
_TOWN_CENTER_IDS = {109, 490}
_BUILD_ACTIONS = {"BUILD"}


@register(
    name="build_by_category",
    tier=1,
    tag="ECO",
    description="Per-player BUILD counts grouped by structure category (eco/military/defensive).",
)
def build_by_category(events: list[dict]) -> list[dict]:
    """Count each player's BUILD actions by structure category.

    A coarse fingerprint of a player's macro emphasis: how much they invested in
    economy vs military vs defensive structures.
    """
    # player_id -> category -> count
    counts: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for ev in events:
        if ev["action"] not in _BUILD_ACTIONS or ev["obj_id"] is None:
            continue
        counts[ev["player_id"]][ev["category"]] += 1

    records: list[dict] = []
    for player_id, by_cat in sorted(counts.items()):
        total = sum(by_cat.values())
        records.append(
            {
                "player_id": player_id,
                "total_builds": total,
                "eco": by_cat.get("eco", 0),
                "military": by_cat.get("military", 0),
                "defensive": by_cat.get("defensive", 0),
                "unknown": by_cat.get("unknown", 0),
            }
        )
    return records


@register(
    name="town_center_timing",
    tier=1,
    tag="ECO",
    description="Per-player timing of the 2nd and 3rd Town Center (boom commitment).",
)
def town_center_timing(events: list[dict]) -> list[dict]:
    """Extract the timestamp of each player's 2nd and 3rd Town Center.

    A direct boom-commitment signal: in post-imperial games the starting TC is
    implicit, so the Nth *built* TC marks how aggressively a player expanded
    their economy. We report the 2nd and 3rd TC times (the 1st built TC is the
    "2nd overall" given the implicit starting TC).
    """
    # player_id -> sorted list of TC build times (ms)
    tc_times: dict[int, list[int]] = defaultdict(list)

    for ev in events:
        if ev["action"] != "BUILD":
            continue
        if ev["obj_id"] in _TOWN_CENTER_IDS:
            tc_times[ev["player_id"]].append(ev["t_ms"])

    records: list[dict] = []
    for player_id, times in sorted(tc_times.items()):
        times.sort()
        # times[0] is the first *additional* TC the player built = their 2nd TC
        # overall (the starting TC is implicit / not in the BUILD stream).
        second_tc = times[0] if len(times) >= 1 else None
        third_tc = times[1] if len(times) >= 2 else None
        records.append(
            {
                "player_id": player_id,
                "additional_tcs_built": len(times),
                "second_tc_ms": second_tc,
                "third_tc_ms": third_tc,
                "second_tc_str": _fmt(second_tc),
                "third_tc_str": _fmt(third_tc),
            }
        )
    return records


def _fmt(t_ms: int | None) -> str | None:
    if t_ms is None:
        return None
    s = t_ms // 1000
    return f"{s // 60:02d}:{s % 60:02d}"
