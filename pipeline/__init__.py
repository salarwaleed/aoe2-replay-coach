"""Pipeline 1 — Raw Ingestion.

Parses local Age of Empires II ``.mgz`` replay files (Voobly UserPatch VER 9.F)
into raw per-player technical event logs, chunks them, embeds them, and stages
them in a Dockerized ChromaDB instance for a later synthesis pipeline.
"""

__all__ = ["config", "dat_ids", "replay_parser"]
