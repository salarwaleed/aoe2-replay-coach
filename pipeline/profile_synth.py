"""Pipeline 3 — player profile synthesis via a local Ollama LLM.

Unlike pipeline 2's sentence rewriting (mechanical, has a deterministic
fallback), profile synthesis genuinely requires an LLM: turning a list of raw
per-match event sentences into a coherent strategic read (playstyle, economy,
aggression, defense, teamwork, tendencies, caveats) is a judgement task with
no faithful template equivalent. So there is **no fallback path** here — if
Ollama or the configured model isn't available, :func:`synthesize_profile`
raises :class:`OllamaNotReadyError` with a clear, actionable message instead
of silently producing a fake/garbage profile.

Public entry point: ``synthesize_profile(player_name, events) -> dict``.
"""

from __future__ import annotations

import json
import re

from .config import (
    OLLAMA_HOST,
    PROFILE_OLLAMA_MODEL,
    PROFILE_OLLAMA_TEMPERATURE,
    PROFILE_OLLAMA_TIMEOUT,
)

# Sections every synthesized profile must have. Used both to build the
# prompt's expected output shape and to validate/parse the model's response.
PROFILE_SECTIONS: tuple[str, ...] = (
    "playstyle",
    "economy",
    "aggression",
    "defense",
    "teamwork",
    "tendencies",
    "caveats",
)

# Hard cap on how many event sentences go into the prompt. A prolific player
# across many matches can have thousands of events; qwen2.5:7b has a finite
# context window and synthesis quality degrades long before that limit
# anyway. We keep the EARLIEST and LATEST events (career arc) plus an evenly
# spaced sample of the middle, rather than truncating to just the start.
MAX_EVENTS_IN_PROMPT = 600


class OllamaNotReadyError(RuntimeError):
    """Raised when Ollama is unreachable or the configured model isn't pulled.

    This is a typed, expected error (not a crash) — callers should catch it
    and report a clear "model not ready yet" message rather than letting a
    traceback surface, since the model may simply still be downloading.
    """


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


def ollama_profile_model_ready() -> tuple[bool, str]:
    """Check whether Ollama is reachable AND the profiling model is pulled.

    Returns ``(ready, message)``. Does not raise — callers decide whether a
    "not ready" result is fatal (profile_synth.synthesize_profile turns it
    into :class:`OllamaNotReadyError`; the orchestrator can check this first
    to print a friendly status without attempting a call).
    """
    models = _ollama_models_available()
    if not models:
        return False, (
            f"Ollama at {OLLAMA_HOST} is unreachable or has no models installed.\n"
            f"If you just started a pull, it may still be downloading. Check with:\n"
            f"    ollama list\n"
            f"If not pulling yet, start it with:\n"
            f"    ollama pull {PROFILE_OLLAMA_MODEL}"
        )
    matches = [
        m for m in models if m == PROFILE_OLLAMA_MODEL or m.startswith(f"{PROFILE_OLLAMA_MODEL}:")
    ]
    if not matches:
        return False, (
            f"Configured PROFILE_OLLAMA_MODEL='{PROFILE_OLLAMA_MODEL}' is not among "
            f"installed models {models}.\n"
            f"It may still be downloading — check progress with:\n"
            f"    ollama list\n"
            f"If not pulling yet, start it with:\n"
            f"    ollama pull {PROFILE_OLLAMA_MODEL}"
        )
    return True, f"Ollama ready with model '{matches[0]}'."


def _sample_events(sentences: list[str], max_n: int) -> list[str]:
    """Down-sample a long sentence list while preserving chronological order
    and the start/end of the player's history (career arc matters more than
    a uniformly random sample for a strategic read)."""
    if len(sentences) <= max_n:
        return sentences

    head_n = max_n // 4
    tail_n = max_n // 4
    mid_n = max_n - head_n - tail_n

    head = sentences[:head_n]
    tail = sentences[-tail_n:]
    middle_pool = sentences[head_n : len(sentences) - tail_n]
    if mid_n <= 0 or not middle_pool:
        return head + tail

    step = max(1, len(middle_pool) // mid_n)
    middle = middle_pool[::step][:mid_n]
    return head + middle + tail


def _build_prompt(player_name: str, sentences: list[str], n_matches: int) -> str:
    sampled = _sample_events(sentences, MAX_EVENTS_IN_PROMPT)
    numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sampled))
    sampled_note = (
        f"(showing a representative sample of {len(sampled)} of {len(sentences)} "
        "total recorded events, in chronological order)"
        if len(sentences) > len(sampled)
        else f"(all {len(sentences)} recorded events, in chronological order)"
    )

    return f"""You are an Age of Empires II analyst. Below is a chronological log of
in-game events for ONE player, "{player_name}", pulled from {n_matches} replay(s).

IMPORTANT DATA LIMITATION — read carefully:
Only a subset of action types could be attributed to a specific player by the
upstream parser: BUILD, WALL, GATE, TRIBUTE, RESIGN, FLARE, DELETE. Unit
training/queueing (QUEUE/MULTIQUEUE) and several other actions could NOT be
attributed to a player and are excluded entirely from this log. This means:
  - You have NO reliable data on army composition, unit counts, or what units
    this player trained. NEVER claim or imply anything about army composition,
    unit choices, tech/unique-unit usage, or military unit counts.
  - You DO have reliable data on: building choices and timing (economy/defense
    structures, Town Centers, walls/gates), resource tributes between players
    (teamwork signal), deletions, map flares (scouting/communication signal),
    and resignations (game-ending behavior).
  - If the log is sparse or one-sided, say so explicitly rather than inventing
    detail to fill a section.

Event log {sampled_note}:
{numbered}

Write a strategic player profile for {player_name} based ONLY on what the log
above actually shows. Respond with EXACTLY these seven sections, each as a
markdown heading followed by 2-5 sentences of prose (not bullet lists), in
this exact order and using these exact headings:

## Playstyle
## Economy
## Aggression
## Defense
## Teamwork
## Tendencies
## Caveats

The "Caveats" section MUST explicitly state that army composition and unit
training cannot be assessed from this data (because QUEUE actions are
unattributed), and should note any other gaps you noticed (e.g. few matches,
short logs, no tribute activity, etc.). Do not add any other sections, intro,
or outro text — output only the seven headings and their prose, nothing else."""


def _call_ollama(prompt: str) -> str:
    import requests

    resp = requests.post(
        f"{OLLAMA_HOST}/api/generate",
        json={
            "model": PROFILE_OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": PROFILE_OLLAMA_TEMPERATURE},
        },
        timeout=PROFILE_OLLAMA_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json().get("response", "")


# Matches "## Playstyle" (case-insensitive, tolerant of trailing whitespace)
_HEADING_RE = re.compile(
    r"^\s*#{1,3}\s*(" + "|".join(PROFILE_SECTIONS) + r")\s*$",
    re.IGNORECASE,
)


def _parse_sections(text: str) -> dict[str, str]:
    """Split the model's markdown response into {section_name: prose}.

    Tolerant of minor formatting drift (heading level, case, surrounding
    whitespace) since this is free-form LLM output, not a strict grammar.
    Missing sections are recorded as an empty string rather than raising —
    the orchestrator/caller can decide if that's acceptable, but a model
    that skips one section out of seven shouldn't sink the whole profile.
    """
    sections: dict[str, list[str]] = {name: [] for name in PROFILE_SECTIONS}
    current: str | None = None

    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            current = m.group(1).lower()
            continue
        if current is not None and line.strip():
            sections[current].append(line.strip())

    return {name: " ".join(lines).strip() for name, lines in sections.items()}


def synthesize_profile(
    player_name: str,
    sentences: list[str],
    n_matches: int,
) -> dict:
    """Build a strategic profile for one player from their event sentences.

    ``sentences`` must already be filtered to this player's attributed
    events (player_id != -1) and sorted chronologically (callers: see
    ``pipeline3_profiles.py``, which pulls + sorts them from DynamoDB).

    Returns a dict with keys: ``player_name``, ``n_matches``, ``n_events``,
    and one key per :data:`PROFILE_SECTIONS` entry holding that section's
    prose.

    Raises :class:`OllamaNotReadyError` if Ollama / the configured model is
    not available — this is NOT silently swallowed into a fake profile,
    since synthesis genuinely needs the LLM.
    """
    ready, message = ollama_profile_model_ready()
    if not ready:
        raise OllamaNotReadyError(message)

    if not sentences:
        raise ValueError(f"No attributed events given for player '{player_name}'.")

    prompt = _build_prompt(player_name, sentences, n_matches)

    try:
        response_text = _call_ollama(prompt)
    except Exception as exc:
        raise OllamaNotReadyError(
            f"Ollama call failed for model '{PROFILE_OLLAMA_MODEL}' at {OLLAMA_HOST}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    if not response_text.strip():
        raise OllamaNotReadyError(
            f"Ollama returned an empty response for model '{PROFILE_OLLAMA_MODEL}'. "
            "The model may still be loading/downloading; try again shortly."
        )

    sections = _parse_sections(response_text)

    profile = {
        "player_name": player_name,
        "n_matches": n_matches,
        "n_events": len(sentences),
        "model": PROFILE_OLLAMA_MODEL,
        **sections,
    }
    return profile


def profile_to_markdown(profile: dict) -> str:
    """Render a profile dict (as returned by :func:`synthesize_profile`) as a
    human-readable markdown document."""
    lines = [
        f"# Player Profile: {profile['player_name']}",
        "",
        f"*Synthesized from {profile['n_events']} attributed events across "
        f"{profile['n_matches']} match(es), model `{profile['model']}`.*",
        "",
    ]
    for section in PROFILE_SECTIONS:
        title = section.capitalize() if section != "tendencies" else "Tendencies & Strengths"
        lines.append(f"## {title}")
        lines.append("")
        lines.append(profile.get(section, "").strip() or "_(no content generated)_")
        lines.append("")
    return "\n".join(lines)
