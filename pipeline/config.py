"""Static configuration for the ingestion + telemetry pipelines.

Nothing here performs I/O or imports heavy dependencies, so it is safe to import
from anywhere in the package (parser, signals, orchestrators, tests).

Most network/service settings are environment-overridable so the exact same code
runs against local dev services (Docker) and real cloud services.
"""

import os

# ── ChromaDB connection ──────────────────────────────────────────────────────
# Matches infra/docker-compose.yml (container ``aoe-chromadb``, port 8000).
CHROMA_HOST: str = os.environ.get("CHROMA_HOST", "localhost")
CHROMA_PORT: int = int(os.environ.get("CHROMA_PORT", "8000"))
COLLECTION_NAME: str = os.environ.get("COLLECTION_NAME", "raw_match_logs")

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


# ═════════════════════════════════════════════════════════════════════════════
# Pipeline 2 — Telemetry & Timelines
# ═════════════════════════════════════════════════════════════════════════════

# ── DynamoDB ─────────────────────────────────────────────────────────────────
# All DynamoDB access goes through boto3 with a configurable endpoint_url. THE
# KEY DESIGN POINT: identical code runs locally and in the cloud.
#
#   * Local dev (default): DYNAMODB_ENDPOINT_URL points at dynamodb-local
#     (Docker, host port 8001) with dummy credentials. No real AWS account used.
#   * Real AWS: set DYNAMODB_ENDPOINT_URL="" (empty) and provide real credentials
#     via the standard AWS mechanisms (env vars, ~/.aws/credentials, IAM role).
#     When the endpoint is empty, boto3 talks to the real regional endpoint and
#     the rest of the code is unchanged.
#
# An empty/whitespace env value is treated as "use real AWS" (endpoint_url=None).
_raw_dynamo_endpoint: str = os.environ.get(
    "DYNAMODB_ENDPOINT_URL", "http://localhost:8001"
)
DYNAMODB_ENDPOINT_URL: str | None = _raw_dynamo_endpoint.strip() or None

AWS_REGION: str = os.environ.get("AWS_REGION", "us-east-1")
DYNAMODB_TABLE_NAME: str = os.environ.get("DYNAMODB_TABLE_NAME", "match_timelines")

# Dummy credentials used ONLY when talking to dynamodb-local. boto3 still requires
# *some* credentials to sign requests even though dynamodb-local ignores them.
# These are never used against real AWS (real creds come from the environment).
DYNAMODB_LOCAL_ACCESS_KEY_ID: str = os.environ.get("AWS_ACCESS_KEY_ID", "local")
DYNAMODB_LOCAL_SECRET_ACCESS_KEY: str = os.environ.get(
    "AWS_SECRET_ACCESS_KEY", "local"
)

# ── Ollama (local LLM) ───────────────────────────────────────────────────────
OLLAMA_HOST: str = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
# Model used to rewrite raw log lines into event sentences. A small, fast model
# is plenty for this deterministic-style rewriting task.
OLLAMA_MODEL: str = os.environ.get("OLLAMA_MODEL", "llama3.2")
# Low temperature: we want faithful transcription, not creativity.
OLLAMA_TEMPERATURE: float = float(os.environ.get("OLLAMA_TEMPERATURE", "0.1"))
# Per-request timeout (seconds) for an Ollama generate call on one chunk.
OLLAMA_TIMEOUT: float = float(os.environ.get("OLLAMA_TIMEOUT", "120"))

# Suggested small models if none are installed (printed by llm_extract).
OLLAMA_SUGGESTED_MODELS: tuple[str, ...] = ("llama3.2", "qwen2.5:3b")
