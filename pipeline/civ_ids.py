"""Static civilization id -> name lookup.

Ids 1-20 were originally listed alphabetically, which does not match the id
order this Voobly build actually encodes in replay headers (classic AoC
release order). Corrected against ``aocref``'s bundled reference data and
verified against two live ground-truth test matches (civ=15 confirmed Aztecs
via an observed Elite Eagle Warrior; civ=29 confirmed Malay by the player who
recorded the match). Ids 32+ are Definitive-Edition-only civs with no
equivalent in this pre-DE Voobly build and are left unverified/unused.

Used by :mod:`pipeline.replay_parser` to label the ``civilization`` byte
recovered from the decompressed header's per-player stats block.
"""

from __future__ import annotations

CIV_ID_TO_NAME: dict[int, str] = {
    0: "Gaia", 1: "Britons", 2: "Franks", 3: "Goths", 4: "Teutons", 5: "Japanese",
    6: "Chinese", 7: "Byzantines", 8: "Persians", 9: "Saracens", 10: "Turks", 11: "Vikings",
    12: "Mongols", 13: "Celts", 14: "Spanish", 15: "Aztecs", 16: "Mayans",
    17: "Huns", 18: "Koreans", 19: "Italians", 20: "Indians", 21: "Incas",
    22: "Magyars", 23: "Slavs", 24: "Portuguese", 25: "Ethiopians", 26: "Malians",
    27: "Berbers", 28: "Khmer", 29: "Malay", 30: "Burmese", 31: "Vietnamese",
    32: "Cumans", 33: "Lithuanians", 34: "Bulgarians", 35: "Tatars",
    36: "Burgundians", 37: "Sicilians", 38: "Poles", 39: "Bohemians",
    40: "Dravidians", 41: "Bengalis", 42: "Gurjaras", 43: "Romans",
    44: "Armenians", 45: "Georgians",
}
