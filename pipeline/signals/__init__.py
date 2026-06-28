"""Signal registry.

This package is the extensibility seam for telemetry. Future signals are added as
pure ``extract(events) -> list[record]`` functions decorated with
:func:`register` — no changes to the parser or the ingestion orchestrator are
required.

Usage
-----
>>> from pipeline.signals import register, SIGNALS
>>> @register(name="my_signal", tier=2, tag="ECO", description="...")
... def my_signal(events):
...     return [...]

``SIGNALS`` is the populated registry (``{name: Signal}``) once the modules that
define signals have been imported. :func:`run_all` applies every registered
signal to a match's events.
"""

from __future__ import annotations

from typing import Callable

from .base import ExtractFn, Signal

# Public registry: signal name -> Signal.
SIGNALS: dict[str, Signal] = {}


def register(
    *, name: str, tier: int, tag: str, description: str = ""
) -> Callable[[ExtractFn], ExtractFn]:
    """Decorator that registers an ``extract`` function as a :class:`Signal`.

    Raises
    ------
    ValueError
        If ``name`` is already registered (signals must be uniquely named).
    """

    def decorator(fn: ExtractFn) -> ExtractFn:
        if name in SIGNALS:
            raise ValueError(f"signal {name!r} is already registered")
        SIGNALS[name] = Signal(
            name=name, tier=tier, tag=tag, extract=fn, description=description
        )
        return fn

    return decorator


def run_all(events: list[dict]) -> dict[str, list[dict]]:
    """Run every registered signal over ``events``.

    Returns ``{signal_name: [records...]}``.
    """
    return {name: sig.run(events) for name, sig in SIGNALS.items()}


# Import the bundled reference signals so they self-register on package import.
# (Kept at the bottom to avoid a circular import with ``register``.)
from . import reference  # noqa: E402,F401

__all__ = ["SIGNALS", "Signal", "register", "run_all"]
