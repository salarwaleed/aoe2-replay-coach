"""Pipeline 2 — raw log line -> event-sentence extraction.

Each ChromaDB chunk (see ``pipeline1_ingest.py``) holds a fixed window of one
player's raw technical log lines, e.g.::

    t=04:15 p=1 BUILD Watch Tower(id=79) [DEF] pos=[34.0, 12.0]
    t=06:02 p=? QUEUE Knight(id=38) [MIL] amount=3

This module turns each line into a single, factual, chronological English
sentence, e.g. ``At 04:15, player 1 built a Watch Tower.``

Two extraction paths exist:

1. **Ollama** (preferred): a local LLM rewrites the whole chunk in one call.
   Faithful but not byte-deterministic — see ``_build_prompt`` for the
   constraints we give the model (no invention, preserve time/player order).
2. **Deterministic fallback**: a plain template renderer keyed off the action
   keyword. Always available, always produces the same output for the same
   input, and is what actually runs when Ollama has no model pulled (the
   common state on a fresh dev machine).

``extract_sentences(raw_text)`` is the single public entry point; it tries
Ollama first (if reachable and a model is installed) and falls back
automatically, logging clearly which path ran.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import OLLAMA_HOST, OLLAMA_MODEL, OLLAMA_SUGGESTED_MODELS, OLLAMA_TEMPERATURE, OLLAMA_TIMEOUT

# ─────────────────────────────────────────────────────────────────────────────
# Line parsing
# ─────────────────────────────────────────────────────────────────────────────

# t=04:15 p=1 BUILD Watch Tower(id=79) [DEF] pos=[34.0, 12.0]
# t=06:02 p=? QUEUE Knight(id=38) [MIL] amount=3
# t=01:04 p=? BACK_TO_WORK
_LINE_RE = re.compile(
    r"^t=(?P<t_str>\S+)\s+p=(?P<pid>\?|-?\d+)\s+(?P<action>[A-Z_]+)"
    r"(?:\s+(?P<obj_name>.+?)\(id=(?P<obj_id>-?\d+)\)\s*\[(?P<tag>[A-Z]+)\])?"
    r"(?P<extras>.*)$"
)
_EXTRA_RE = re.compile(r"(\w+)=(\[[^\]]*\]|\S+)")


@dataclass
class ParsedEvent:
    t_str: str
    t_ms: int
    player_id: int
    action: str
    obj_name: str | None
    category_tag: str | None
    extras: dict[str, str]
    raw_line: str


def _t_str_to_ms(t_str: str) -> int:
    """Convert ``MM:SS`` (or ``HH:MM:SS``) back to milliseconds."""
    parts = [int(p) for p in t_str.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts
    return ((h * 60 + m) * 60 + s) * 1000


def parse_line(line: str) -> ParsedEvent | None:
    """Parse one raw log line into a :class:`ParsedEvent`, or ``None`` if it
    doesn't match the expected grammar (defensive — never raises)."""
    line = line.strip()
    if not line:
        return None
    m = _LINE_RE.match(line)
    if not m:
        return None

    pid_raw = m.group("pid")
    player_id = -1 if pid_raw == "?" else int(pid_raw)
    extras = dict(_EXTRA_RE.findall(m.group("extras") or ""))

    return ParsedEvent(
        t_str=m.group("t_str"),
        t_ms=_t_str_to_ms(m.group("t_str")),
        player_id=player_id,
        action=m.group("action"),
        obj_name=m.group("obj_name"),
        category_tag=m.group("tag"),
        extras=extras,
        raw_line=line,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Deterministic fallback renderer
# ─────────────────────────────────────────────────────────────────────────────
def _player_phrase(player_id: int) -> str:
    return "an unattributed unit" if player_id == -1 else f"player {player_id}"


def render_template_sentence(ev: ParsedEvent) -> str:
    """Render one parsed event as a factual sentence using fixed templates.

    Deliberately conservative: every sentence states only what the line
    contains, with no invented detail.
    """
    who = _player_phrase(ev.player_id)
    prefix = f"At {ev.t_str},"

    action = ev.action
    obj = ev.obj_name
    extras = ev.extras

    if action in ("QUEUE", "MULTIQUEUE"):
        amount = extras.get("amount", "1")
        plural = "s" if amount != "1" else ""
        return f"{prefix} {who} queued {amount} {obj}{plural}."
    if action == "BUILD":
        return f"{prefix} {who} built a {obj}."
    if action == "WALL":
        return f"{prefix} {who} placed a wall section."
    if action == "DELETE":
        n = extras.get("n_units", "1")
        return f"{prefix} {who} deleted {n} unit(s)."
    if action == "REPAIR":
        return f"{prefix} {who} repaired a building or unit."
    if action == "STANCE":
        n = extras.get("n_units")
        stance_id = extras.get("stance_id")
        target = f" for {n} unit(s)" if n else ""
        return f"{prefix} {who} set stance {stance_id}{target}."
    if action == "UNGARRISON":
        n = extras.get("n_units", "1")
        return f"{prefix} {who} ungarrisoned {n} unit(s)."
    if action == "BACK_TO_WORK":
        return f"{prefix} {who} sent idle villagers back to work."
    if action == "TOWN_BELL":
        return f"{prefix} {who} rang the town bell."
    if action == "GATE":
        return f"{prefix} {who} toggled a gate."
    if action == "FLARE":
        return f"{prefix} {who} sent a map flare."
    if action == "RESIGN":
        return f"{prefix} {who} resigned."
    if action == "TRIBUTE":
        to = extras.get("to")
        amount = extras.get("amount")
        resource_id = extras.get("resource_id")
        return (
            f"{prefix} {who} sent a tribute of {amount} "
            f"(resource {resource_id}) to player {to}."
        )
    if action == "BUY":
        amount = extras.get("amount")
        resource_id = extras.get("resource_id")
        return f"{prefix} {who} bought {amount} unit(s) of resource {resource_id} at the market."
    if action == "SELL":
        amount = extras.get("amount")
        resource_id = extras.get("resource_id")
        return f"{prefix} {who} sold {amount} unit(s) of resource {resource_id} at the market."

    # Unknown/unmapped action: degrade gracefully rather than invent meaning.
    obj_part = f" involving {obj}" if obj else ""
    return f"{prefix} {who} performed {action}{obj_part}."


def render_fallback(lines: list[str]) -> list[tuple[ParsedEvent, str]]:
    """Deterministic path: parse + template-render every line in the chunk."""
    out: list[tuple[ParsedEvent, str]] = []
    for line in lines:
        ev = parse_line(line)
        if ev is None:
            continue
        out.append((ev, render_template_sentence(ev)))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Ollama
# ─────────────────────────────────────────────────────────────────────────────
_OLLAMA_AVAILABILITY_CACHE: dict[str, bool] = {}


def _ollama_models_available() -> list[str]:
    """Return installed Ollama model names, or [] if Ollama is unreachable."""
    try:
        import requests

        resp = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def ollama_is_ready() -> tuple[bool, str]:
    """Check once whether Ollama is reachable AND has a usable model pulled.

    Returns ``(ready, message)``. Cached per-process so the orchestrator can
    call this once and log it, rather than probing per-chunk.
    """
    models = _ollama_models_available()
    if not models:
        return False, (
            f"Ollama at {OLLAMA_HOST} is unreachable or has no models installed. "
            f"Pull a small model to enable LLM extraction, e.g.:\n"
            f"    ollama pull {OLLAMA_SUGGESTED_MODELS[0]}\n"
            f"(or: ollama pull {OLLAMA_SUGGESTED_MODELS[1]})"
        )
    # Match configured model by prefix (Ollama tags often include ":latest").
    matches = [m for m in models if m == OLLAMA_MODEL or m.startswith(f"{OLLAMA_MODEL}:")]
    if not matches:
        return False, (
            f"Configured OLLAMA_MODEL='{OLLAMA_MODEL}' is not among installed "
            f"models {models}. Pull it with:\n    ollama pull {OLLAMA_MODEL}"
        )
    return True, f"Ollama ready with model '{matches[0]}'."


def _build_prompt(lines: list[str]) -> str:
    numbered = "\n".join(f"{i + 1}. {line}" for i, line in enumerate(lines))
    return f"""You convert raw Age of Empires II replay log lines into plain factual
English sentences, one sentence per input line, in the SAME order as the input.

Rules:
- Output exactly one line per input line, in the same order, numbered 1. 2. 3. ...
- Each sentence MUST start with "At <time>," and state the player (e.g. "player 1")
  or "an unattributed unit" if the player is "?".
- State only facts present in the line (action, object name, amounts, targets).
  Do NOT invent strategy commentary, intent, or outcomes.
- Keep each sentence short (one clause).
- Do not merge, skip, or reorder lines.

Input lines:
{numbered}

Output (numbered, one sentence per line):"""


def _call_ollama(prompt: str) -> str:
    import requests

    resp = requests.post(
        f"{OLLAMA_HOST}/api/generate",
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": OLLAMA_TEMPERATURE},
        },
        timeout=OLLAMA_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json().get("response", "")


_NUMBERED_RE = re.compile(r"^\s*\d+[.\)]\s*(.+)$")


def _parse_numbered_sentences(text: str, expected_n: int) -> list[str] | None:
    """Parse the model's numbered output back into a flat sentence list.

    Returns ``None`` (triggering fallback) if the model didn't return exactly
    ``expected_n`` usable lines — we'd rather fall back deterministically than
    silently misalign sentences with events.
    """
    sentences: list[str] = []
    for raw_line in text.splitlines():
        m = _NUMBERED_RE.match(raw_line)
        if m:
            sentences.append(m.group(1).strip())
    if len(sentences) != expected_n:
        return None
    return sentences


def render_with_ollama(lines: list[str]) -> list[tuple[ParsedEvent, str]] | None:
    """Try the Ollama path for one chunk's lines.

    Returns ``None`` on any failure (unreachable, bad output shape, etc.) so
    the caller can fall back to the deterministic renderer.
    """
    parsed = [parse_line(line) for line in lines]
    valid = [(ev, line) for ev, line in zip(parsed, lines) if ev is not None]
    if not valid:
        return []

    valid_lines = [line for _, line in valid]
    try:
        prompt = _build_prompt(valid_lines)
        response = _call_ollama(prompt)
    except Exception:
        return None

    sentences = _parse_numbered_sentences(response, len(valid_lines))
    if sentences is None:
        return None

    return [(ev, sentence) for (ev, _), sentence in zip(valid, sentences)]


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────
def extract_sentences(raw_text: str, use_ollama: bool) -> tuple[list[tuple[ParsedEvent, str]], str]:
    """Extract (event, sentence) pairs from one chunk's raw text.

    Returns ``(pairs, path_used)`` where ``path_used`` is ``"ollama"`` or
    ``"fallback"`` — the orchestrator logs this so it's always clear which
    path produced a given chunk's sentences.
    """
    lines = raw_text.splitlines()

    if use_ollama:
        result = render_with_ollama(lines)
        if result is not None:
            return result, "ollama"
        # Ollama call failed or returned a malformed response for this chunk
        # specifically (it passed the upfront readiness check) — degrade
        # gracefully rather than losing the chunk.

    return render_fallback(lines), "fallback"
