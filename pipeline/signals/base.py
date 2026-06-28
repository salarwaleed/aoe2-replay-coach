"""Signal protocol shared by all telemetry extractors.

A *signal* is a pure function over the ``events`` list produced by
:func:`pipeline.replay_parser.parse_match_timeline`. It returns zero or more flat
*records* (plain dicts) describing something behaviourally meaningful — e.g. how
many military buildings a player built, or when their 2nd Town Center went down.

Signals are intentionally decoupled from the parser and the ingestion
orchestrator: a new signal is added by writing one ``extract`` function and
registering it (see :mod:`pipeline.signals`), with no edits anywhere else. This
is the extensibility seam called for in TELEMETRY_PLAN.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol


class ExtractFn(Protocol):
    """Callable signature every signal must satisfy."""

    def __call__(self, events: list[dict]) -> list[dict]:  # pragma: no cover
        ...


@dataclass(frozen=True)
class Signal:
    """A registered telemetry signal.

    Attributes
    ----------
    name:
        Unique identifier, e.g. ``"build_by_category"``.
    tier:
        Importance tier (1 = defining, 2 = supporting, 3 = minor), per the
        TELEMETRY_PLAN.md catalogue.
    tag:
        Domain tag — one of ``ECO`` / ``MIL`` / ``DEF`` / ``MAP`` / ``PSY``.
    extract:
        Pure function ``events -> list[record]``.
    description:
        Human-readable one-liner.
    """

    name: str
    tier: int
    tag: str
    extract: ExtractFn
    description: str = ""

    def run(self, events: list[dict]) -> list[dict]:
        """Apply this signal to a match's events, tagging each record."""
        records = self.extract(events)
        for record in records:
            record.setdefault("signal", self.name)
            record.setdefault("tier", self.tier)
            record.setdefault("tag", self.tag)
        return records
