"""Static civilization id -> name lookup.

Copied verbatim from ``age of empire discord bot/bot.py`` (~line 72,
``CIV_ID_TO_NAME``) so the replay-parser package has no import dependency on the
bot. Used by :mod:`pipeline.replay_parser` to label the ``civilization`` byte
recovered from the decompressed header's per-player stats block.
"""

from __future__ import annotations

CIV_ID_TO_NAME: dict[int, str] = {
    0: "Gaia", 1: "Aztecs", 2: "Britons", 3: "Byzantines", 4: "Celts", 5: "Chinese",
    6: "Franks", 7: "Goths", 8: "Huns", 9: "Japanese", 10: "Koreans", 11: "Mayans",
    12: "Mongols", 13: "Persians", 14: "Saracens", 15: "Spanish", 16: "Teutons",
    17: "Turkish", 18: "Vikings", 19: "Italians", 20: "Hindustani", 21: "Incas",
    22: "Magyars", 23: "Slavs", 24: "Portuguese", 25: "Ethiopians", 26: "Malians",
    27: "Berbers", 28: "Khmer", 29: "Malay", 30: "Burmese", 31: "Vietnamese",
    32: "Cumans", 33: "Lithuanians", 34: "Bulgarians", 35: "Tatars",
    36: "Burgundians", 37: "Sicilians", 38: "Poles", 39: "Bohemians",
    40: "Dravidians", 41: "Bengalis", 42: "Gurjaras", 43: "Romans",
    44: "Armenians", 45: "Georgians",
}
