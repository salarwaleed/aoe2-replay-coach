"""Static configuration for Pipeline 1.

Nothing here performs I/O or imports heavy dependencies, so it is safe to import
from anywhere in the package (parser, signals, orchestrator, tests).
"""

# ── ChromaDB connection ──────────────────────────────────────────────────────
# Matches infra/docker-compose.yml (container ``aoe-chromadb``, port 8000).
CHROMA_HOST: str = "localhost"
CHROMA_PORT: int = 8000
COLLECTION_NAME: str = "raw_match_logs"

# ── Replay sources ───────────────────────────────────────────────────────────
# Copied verbatim from bot.py (~line 2272). Only the active Voobly v1.6 folder is
# scanned; the base-game SaveGame folder was intentionally dropped upstream.
SAVEGAME_PATHS: list[str] = [
    r"D:\Program Files (x86)\Microsoft Games\Age of Empires II\Voobly Mods\AOC\Data Mods\v1.6 Game Data\SaveGame",
]

# Two of the 24 recordings are structurally corrupt at the body level (the op
# stream desynchronises and yields an invalid operation id). They are skipped by
# filename before any parse is attempted so the run never crashes on them.
UNREADABLE_FILES: frozenset[str] = frozenset(
    {
        "rec.20260621-015219.mgz",
        "rec.20260625-204143.mgz",
    }
)

# ── Chunking ─────────────────────────────────────────────────────────────────
# Number of events per ChromaDB document (a rolling window of one player's
# technical log). 40 events ≈ a readable, embedding-sized slice of a match.
CHUNK_SIZE: int = 40

# Sentinel player id used when an action carries no player attribution. In the
# legacy Voobly action format, QUEUE / MULTIQUEUE / STANCE / TOWN_BELL and a few
# others identify the player only via the producing object (whose owner is not
# recoverable from the command stream). Such events are bucketed under this
# sentinel rather than guessed. See README "Player attribution limitation".
UNATTRIBUTED_PLAYER_ID: int = -1
