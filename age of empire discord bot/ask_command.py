"""!ask <player_name> — read a synthesized strategic profile from MinIO/S3 and
show it as a Discord embed.

This is a SEPARATE system from the existing `!profile` command in bot.py:
  - `!profile` reads `profiles.json` (local win-rate/favourite-civ stats built
    by `!analyze` from raw .mgz files).
  - `!ask` reads a player's *synthesized* strategic profile (playstyle,
    economy, aggression, defense, teamwork, tendencies, caveats) written by
    pipeline 3 (`pipeline/pipeline3_profiles.py` + `pipeline/profile_synth.py`)
    and stored in MinIO/S3 via `pipeline/s3_store.py`.

Per the original design doc (TELEMETRY_PLAN.md, step 6: "Add the Discord
`!ask <player>` Discord command -> read profile.txt -> Gemini/Openclaw call"),
`!ask` was meant to also answer free-form questions about a player via a cloud
LLM. No cloud LLM endpoint/key/model is configured yet (.env.example only has
DISCORD_TOKEN), so that part is intentionally NOT wired up — see
`_call_cloud_llm` below. `!ask <player>` on its own is a complete, useful
command: it fetches the stored profile and renders it, no external API needed.
"""

from __future__ import annotations

import os
import sys

import discord

# ── Make the `pipeline` package importable ──────────────────────────────────
# `pipeline/` lives at the project root, one directory above this file
# (`age of empire discord bot/`). bot.py is normally launched with its own
# directory as cwd (see run_bot.bat), so a plain `import pipeline` would fail
# unless the project root is on sys.path. Insert it (once) based on this
# file's own location, which works regardless of cwd.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from pipeline.s3_store import get_profile  # noqa: E402  (after sys.path fixup)

# ─────────────────────────────────────────────────────────────────────────────
# COLOUR — distinct from bot.py's existing palette (C_DRAFT/C_TEAMS/C_CIV/...)
# so `!ask` embeds are visually distinguishable from other commands.
# ─────────────────────────────────────────────────────────────────────────────
C_ASK = 0x1ABC9C  # teal

# Sections in display order, paired with a heading icon/title. Matches
# pipeline.profile_synth.PROFILE_SECTIONS, but kept as a local literal (rather
# than importing PROFILE_SECTIONS) so this module's rendering order/labels are
# an explicit, independent presentation choice.
_SECTION_DISPLAY: tuple[tuple[str, str], ...] = (
    ("playstyle", "🎮 Playstyle"),
    ("economy", "🌾 Economy"),
    ("aggression", "⚔️ Aggression"),
    ("defense", "🛡️ Defense"),
    ("teamwork", "🤝 Teamwork"),
    ("tendencies", "🔁 Tendencies & Strengths"),
    ("caveats", "⚠️ Caveats"),
)

# Discord embed field value hard limit is 1024 chars. Profile sections are
# prose paragraphs (typically a few hundred chars — see verification), but we
# guard against a pathologically long synthesis output rather than letting
# discord.py raise on send.
_FIELD_VALUE_LIMIT = 1024
_TRUNCATION_SUFFIX = "… (truncated)"


def _clip(text: str, limit: int = _FIELD_VALUE_LIMIT) -> str:
    """Clip text to fit a Discord embed field, leaving room for a suffix."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text or "_(no content generated)_"
    return text[: limit - len(_TRUNCATION_SUFFIX)].rstrip() + _TRUNCATION_SUFFIX


def build_ask_embed(player_name: str, profile: dict) -> discord.Embed:
    """Build the `!ask` embed from a profile dict as returned by
    `pipeline.s3_store.get_profile()` (the json_obj half of its return tuple).

    Pure/synchronous and side-effect free, so it can be unit-tested without a
    running Discord bot or event loop.
    """
    display_name = profile.get("player_name", player_name)
    n_matches = profile.get("n_matches", "?")
    n_events = profile.get("n_events", "?")
    model = profile.get("model", "unknown")

    embed = discord.Embed(
        title=f"🧠 Player Profile: {display_name}",
        description=(
            f"Synthesized from **{n_events}** attributed events across "
            f"**{n_matches}** match(es) — model `{model}`."
        ),
        color=C_ASK,
    )

    for key, label in _SECTION_DISPLAY:
        embed.add_field(name=label, value=_clip(profile.get(key, "")), inline=False)

    generated_at = profile.get("generated_at")
    footer = "Strategic profile synthesized by local LLM (pipeline 3)"
    if generated_at:
        footer += f" | Generated {generated_at}"
    embed.set_footer(text=footer)

    return embed


def build_not_found_embed(player_name: str) -> discord.Embed:
    """Embed shown when no stored profile exists yet for this player."""
    return discord.Embed(
        title="❌ No Profile Found",
        description=(
            f"No synthesized profile found for **{player_name}**.\n\n"
            "Profiles are built by the offline pipeline "
            "(`pipeline/pipeline3_profiles.py`) and stored in MinIO — this "
            "player may not have been processed yet, or the name may not "
            "match exactly."
        ),
        color=0xE74C3C,  # red
    )


def build_error_embed(player_name: str, exc: Exception) -> discord.Embed:
    """Embed shown when the MinIO/S3 lookup itself fails (connection issue,
    bucket missing, etc.) — distinct from the "no profile yet" case."""
    return discord.Embed(
        title="❌ Could Not Fetch Profile",
        description=(
            f"Failed to read **{player_name}**'s profile from storage.\n"
            f"`{type(exc).__name__}: {exc}`\n\n"
            "Is the MinIO container running? "
            "(`docker compose -f infra/docker-compose.yml up -d`)"
        ),
        color=0xE74C3C,  # red
    )


def fetch_and_build_embed(player_name: str) -> discord.Embed:
    """End-to-end: fetch a player's profile from MinIO and build the embed to
    send. Never raises — all failure modes are translated into an embed so the
    Discord command handler can always do a single `ctx.send(embed=...)`.
    """
    try:
        profile, _markdown_text = get_profile(player_name)
    except FileNotFoundError:
        return build_not_found_embed(player_name)
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see docstring
        return build_error_embed(player_name, exc)

    return build_ask_embed(player_name, profile)


# ─────────────────────────────────────────────────────────────────────────────
# STUB — free-form question answering via a cloud LLM (NOT wired up yet)
# ─────────────────────────────────────────────────────────────────────────────
# Per TELEMETRY_PLAN.md, `!ask <player> <question>` was eventually meant to
# pass the stored profile + a free-form question to a cloud LLM ("Gemini via
# Openclaw") for a deep behavioural answer. No endpoint, API key, or model is
# configured yet (age of empire discord bot/.env.example only defines
# DISCORD_TOKEN), and adding a real network call here would silently break or
# hang the command. This function is intentionally NOT called from anywhere
# in the live command path — `!ask <player>` (no question) is fully satisfied
# by `fetch_and_build_embed` above, with no external API dependency.
#
# To wire this up later:
#   1. Add OPENCLAW_ENDPOINT, OPENCLAW_API_KEY, OPENCLAW_MODEL to
#      age of empire discord bot/.env.example and pipeline/config.py.
#   2. Implement the real HTTP call below (e.g. via `requests`, already a
#      pipeline dependency).
#   3. Have the !ask command pass an optional trailing `question` argument
#      through to this function only when present, keeping the no-question
#      path unchanged.
def _call_cloud_llm(prompt: str) -> str:
    """Stub for the eventual cloud-LLM free-form question flow. NOT wired into
    the live `!ask` command path. Raises NotImplementedError until the
    required env vars are configured.
    """
    raise NotImplementedError(
        "_call_cloud_llm is not implemented yet. Free-form question answering "
        "requires a cloud LLM endpoint that isn't configured in this project. "
        "Set OPENCLAW_ENDPOINT, OPENCLAW_API_KEY, and OPENCLAW_MODEL "
        "(env vars / pipeline/config.py) and implement the HTTP call here "
        "before wiring this into the !ask command."
    )
