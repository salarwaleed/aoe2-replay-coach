"""Static genie-DAT id → (name, category) lookup.

The Voobly UserPatch header does not parse with mgz's structured reader, so the
body walk yields *raw genie object ids* with no names attached. This module ships
a hand-curated id→name table for the building (BUILD) and unit (QUEUE/MULTIQUEUE)
ids actually observed across the 22 readable v1.6 replays, plus a handful of
common neighbours.

Categories are deliberately coarse — ``eco`` | ``military`` | ``defensive`` —
because that is the granularity the telemetry signals care about (see
TELEMETRY_PLAN.md §5). Anything not in the table resolves to
``("Unknown", "unknown")`` so the pipeline never crashes; the renderer appends the
raw id (``Unknown(id=N)``) so unmapped ids still surface clearly in the logs for
later reconciliation.

Only ids identified with high confidence against canonical AoE2 genie ids are
named. Genuinely ambiguous ids are left out on purpose — see README "unmapped
ids to resolve".
"""

from __future__ import annotations

# Category constants (kept as plain strings for ChromaDB-friendliness).
ECO = "eco"
MILITARY = "military"
DEFENSIVE = "defensive"
UNKNOWN = "unknown"

# ── Buildings (BUILD / WALL / GATE building_id) ──────────────────────────────
# Canonical AoE2 building object ids.
_BUILDINGS: dict[int, tuple[str, str]] = {
    12: ("Barracks", MILITARY),
    49: ("Siege Workshop", MILITARY),
    50: ("Farm", ECO),
    68: ("Mill", ECO),
    70: ("House", ECO),
    72: ("Palisade Wall", DEFENSIVE),
    79: ("Watch Tower", DEFENSIVE),
    82: ("Castle", DEFENSIVE),
    84: ("Market", ECO),
    87: ("Archery Range", MILITARY),
    101: ("Stable", MILITARY),
    103: ("Blacksmith", MILITARY),
    104: ("Monastery", MILITARY),
    109: ("Town Center", ECO),
    117: ("Stone Wall", DEFENSIVE),
    155: ("Fortified Wall", DEFENSIVE),
    199: ("Fish Trap", ECO),
    209: ("University", ECO),
    234: ("Outpost", DEFENSIVE),
    276: ("Wonder", ECO),
    487: ("Gate", DEFENSIVE),
    490: ("Town Center", ECO),
    562: ("Lumber Camp", ECO),
    584: ("Mining Camp", ECO),
    598: ("Outpost", DEFENSIVE),
    621: ("Palisade Gate", DEFENSIVE),
    792: ("Gate", DEFENSIVE),
    # Dock / harbour family (water maps).
    45: ("Dock", ECO),
}

# ── Trainable units (QUEUE / MULTIQUEUE unit_id) ─────────────────────────────
# Canonical AoE2 unit object ids.
_UNITS: dict[int, tuple[str, str]] = {
    4: ("Archer", MILITARY),
    5: ("Hand Cannoneer", MILITARY),
    7: ("Skirmisher", MILITARY),
    8: ("Longbowman", MILITARY),  # civ unique (Britons)
    11: ("Mangudai", MILITARY),   # civ unique (Mongols)
    13: ("Fishing Ship", ECO),
    17: ("Trade Cog", ECO),
    24: ("Crossbowman", MILITARY),
    25: ("Teutonic Knight", MILITARY),  # civ unique (Teutons)
    35: ("Battering Ram", MILITARY),
    36: ("Bombard Cannon", MILITARY),
    38: ("Knight", MILITARY),
    39: ("Cavalry Archer", MILITARY),
    40: ("Cataphract", MILITARY),  # civ unique (Byzantines)
    41: ("Huskarl", MILITARY),     # civ unique (Goths)
    46: ("Janissary", MILITARY),   # civ unique (Turks)
    73: ("Chu Ko Nu", MILITARY),   # civ unique (Chinese)
    74: ("Militia / Man-at-Arms line", MILITARY),
    75: ("Man-at-Arms", MILITARY),
    77: ("Two-Handed Swordsman", MILITARY),
    83: ("Villager", ECO),
    93: ("Spearman", MILITARY),
    # NOTE: genie id 101 = Stable (a building). It is intentionally NOT in this
    # units table: it never appears as a QUEUE unit_id in the data (verified 0
    # occurrences), and including it here previously shadowed the buildings entry
    # in the merged DAT_IDS, mislabeling BUILD id=101 (Stable, x341) as a TC.
    106: ("Longboat", MILITARY),   # civ unique (Vikings)
    125: ("Monk", MILITARY),
    128: ("Trade Cart", ECO),
    250: ("Longboat", MILITARY),
    279: ("Scorpion", MILITARY),
    280: ("Mangonel", MILITARY),
    281: ("Throwing Axeman", MILITARY),  # civ unique (Franks)
    282: ("Mameluke", MILITARY),         # civ unique (Saracens)
    329: ("Cavalier", MILITARY),
    331: ("Samurai", MILITARY),          # civ unique (Japanese)
    358: ("Cannon Galleon", MILITARY),
    420: ("Cannon Galleon", MILITARY),
    422: ("Battering Ram (capped)", MILITARY),
    440: ("Petard", MILITARY),
    448: ("Scout Cavalry", MILITARY),
    453: ("Demolition Ship", MILITARY),
    473: ("Two-Handed Swordsman", MILITARY),
    492: ("Arbalester", MILITARY),
    527: ("Demolition Ship", MILITARY),
    528: ("Heavy Demolition Ship", MILITARY),
    539: ("Galley", MILITARY),
    542: ("Heavy Scorpion", MILITARY),
    545: ("Galley", MILITARY),
    546: ("War Galley", MILITARY),
    548: ("Galleon", MILITARY),
    691: ("Galleon", MILITARY),
    692: ("Berserk", MILITARY),          # civ unique (Vikings)
    694: ("Camel Rider", MILITARY),
    725: ("Eagle Scout / Eagle line", MILITARY),
    751: ("Eagle Warrior", MILITARY),
    752: ("Heavy Camel Rider", MILITARY),
    755: ("Jaguar Warrior", MILITARY),   # civ unique (Aztecs)
    757: ("Heavy Camel Rider", MILITARY),
    759: ("War Elephant", MILITARY),     # civ unique (Persians)
    760: ("War Elephant", MILITARY),     # civ unique (Persians)
    763: ("Plumed Archer", MILITARY),    # civ unique (Mayans)
    771: ("Tarkan", MILITARY),           # civ unique (Huns)
    773: ("Tarkan", MILITARY),           # civ unique (Huns)
    774: ("Huskarl", MILITARY),          # civ unique (Goths, elite slot)
    775: ("Tarkan", MILITARY),
    827: ("Conquistador", MILITARY),     # civ unique (Spanish)
    831: ("Conquistador", MILITARY),     # civ unique (Spanish)
    866: ("War Wagon", MILITARY),        # civ unique (Koreans)
    879: ("Kamayuk", MILITARY),          # civ unique (Incas)
    881: ("Kamayuk", MILITARY),          # civ unique (Incas)
    882: ("Boyar", MILITARY),            # civ unique (Slavs)
    886: ("Elite Boyar", MILITARY),      # civ unique (Slavs)
    1001: ("Organ Gun", MILITARY),       # civ unique (Portuguese)
    1004: ("Caravel", MILITARY),         # civ unique (Portuguese)
    1007: ("Camel Archer", MILITARY),    # civ unique (Berbers)
    1010: ("Genitour", MILITARY),        # civ unique (Berbers)
    1013: ("Gbeto", MILITARY),           # civ unique (Malians)
    1016: ("Shotel Warrior", MILITARY),  # civ unique (Ethiopians)
    1103: ("Fire Galley", MILITARY),
    1104: ("Demolition Raft", MILITARY),
    1120: ("Siege Tower", MILITARY),
    1132: ("Ballista Elephant", MILITARY),  # civ unique (Khmer)
    1134: ("Karambit Warrior", MILITARY),   # civ unique (Malay)
    1155: ("Arambai", MILITARY),            # civ unique (Burmese)
    1158: ("Rattan Archer", MILITARY),      # civ unique (Vietnamese)
    1225: ("Konnik", MILITARY),             # civ unique (Bulgarians)
    1226: ("Konnik", MILITARY),             # civ unique (Bulgarians)
    1228: ("Kipchak", MILITARY),            # civ unique (Cumans)
    1231: ("Leitis", MILITARY),             # civ unique (Lithuanians)
    1241: ("Keshik", MILITARY),             # civ unique (Tatars)
    1243: ("Keshik", MILITARY),             # civ unique (Tatars)
    1253: ("Flaming Camel", MILITARY),      # civ unique (Tatars)
    1370: ("Steppe Lancer", MILITARY),
    1372: ("Steppe Lancer", MILITARY),
    1570: ("Coustillier", MILITARY),        # civ unique (Burgundians)
    1655: ("Serjeant", MILITARY),           # civ unique (Sicilians)
    1658: ("Serjeant", MILITARY),           # civ unique (Sicilians)
}

# Guard against a building id and a unit id colliding: a single flat lookup
# cannot serve two different names for the same genie id, and a silent dict-merge
# override is exactly the bug that mislabeled BUILD id=101. If you ever need an id
# in both tables, the parser must disambiguate by action kind instead.
_COLLISIONS = set(_BUILDINGS) & set(_UNITS)
assert not _COLLISIONS, f"dat_ids: id(s) defined in both buildings and units: {sorted(_COLLISIONS)}"

# Public table: union of buildings and units.
DAT_IDS: dict[int, tuple[str, str]] = {**_BUILDINGS, **_UNITS}


def get_obj(obj_id: int | None) -> tuple[str, str]:
    """Resolve a raw genie object id to ``(name, category)``.

    Returns a **bare** name (no embedded id) — e.g. ``("Mill", "eco")`` or
    ``("Unknown", "unknown")`` for unmapped (or ``None``) ids. The numeric id is
    appended once by the renderer (``render_event_line``), which keeps mapped and
    unmapped ids formatted consistently as ``Name(id=N)`` and avoids the
    double-id render (``Unknown(id=N)(id=N)``).
    """
    if obj_id is None:
        return ("Unknown", UNKNOWN)
    mapped = DAT_IDS.get(obj_id)
    if mapped is not None:
        return mapped
    return ("Unknown", UNKNOWN)


def is_building(obj_id: int) -> bool:
    """True if ``obj_id`` is a known building id."""
    return obj_id in _BUILDINGS


def category_tag(category: str) -> str:
    """Short uppercase tag for log rendering (e.g. ``[ECO]``)."""
    return {
        ECO: "ECO",
        MILITARY: "MIL",
        DEFENSIVE: "DEF",
        UNKNOWN: "UNK",
    }.get(category, "UNK")
