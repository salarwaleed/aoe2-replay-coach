"""Low-level ``.mgz`` replay parser for Voobly UserPatch VER 9.F recordings.

The high-level :class:`mgz.summary.Summary` reader fails on these files because
the Voobly mod alters the structured header layout (it is *not* encryption — the
header zlib-decompresses cleanly to ``VER 9.F``). We therefore skip the header
via its 4-byte length prefix and walk the **body** with the low-level
``mgz.fast`` parser, exactly as documented in TELEMETRY_PLAN.md §3.

Public surface
--------------
``parse_match_timeline(path) -> dict``
    Walk one replay's body into a per-player technical event timeline.
``resolve_players(path_or_raw) -> dict[int, str]``
    Best-effort player-name recovery from the zlib-decompressed header, with a
    clean ``Player N`` fallback.
``UnreadableReplay``
    Raised for files that are structurally corrupt at the body level.

Notes / quirks handled
----------------------
* **Action id 177 (0xB1)** is a Voobly anti-cheat heartbeat injected into the
  action stream. It is not a valid ``mgz`` Action, so we skip it *before*
  constructing the ``Action`` enum (which would otherwise raise ``ValueError``).
* These are **post-imperial** games — players start in Imperial Age with all
  techs, so RESEARCH (action 101) is absent *by design*, not an error.
* Duration is taken authoritatively from the POSTGAME ``duration`` field and
  cross-checked against the SYNC-accumulated total; if POSTGAME is missing we
  fall back to the SYNC sum.
"""

from __future__ import annotations

import io
import os
import struct
import zlib
from datetime import datetime

from mgz.body.actions import postgame as postgame_struct
from mgz.fast import parse_action, sync as fast_sync
from mgz.fast.enums import Action, Operation

from . import dat_ids
from .config import UNATTRIBUTED_PLAYER_ID

# Voobly anti-cheat heartbeat injected into the action stream.
_HEARTBEAT_ACTION_ID = 177
# POSTGAME action id (see mgz.fast.enums.Action.POSTGAME).
_POSTGAME_ACTION_ID = 255
# Bytes of leading meta/start block to skip after the header (per §3).
_BODY_PREAMBLE_BYTES = 24

# Actions that carry a meaningful player intent we want in the timeline.
# (MOVE/ORDER/etc. are intentionally excluded from v1 — they are high-volume and
# the reference signals do not yet use them. They remain easy to add later.)
_TIMELINE_ACTIONS = {
    Action.BUILD,
    Action.WALL,
    Action.GATE,
    Action.QUEUE,
    Action.MULTIQUEUE,
    Action.TRIBUTE,
    Action.DE_TRIBUTE,
    Action.STANCE,
    Action.FLARE,
    Action.RESIGN,
    Action.TOWN_BELL,
    Action.BACK_TO_WORK,
    Action.REPAIR,
    Action.DELETE,
    Action.UNGARRISON,
    Action.SELL,
    Action.BUY,
}


class UnreadableReplay(Exception):
    """Raised when a replay cannot be walked at the body level.

    Callers (the ingestion orchestrator) catch this, log it, and skip the file
    rather than aborting the whole run.
    """


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def match_id_from_path(path: str) -> str:
    """Filename stem, e.g. ``rec.20260531-235412``."""
    return os.path.splitext(os.path.basename(path))[0]


def date_from_path(path: str) -> str:
    """Extract a human date from the ``rec.YYYYMMDD-HHMMSS.mgz`` filename idiom.

    Mirrors bot.py (~line 2307). Returns the formatted date, or the raw token if
    the filename does not match the expected shape.
    """
    basename = os.path.basename(path)
    date_str = basename[4:12] if len(basename) > 16 else "unknown"
    try:
        return datetime.strptime(date_str, "%Y%m%d").strftime("%b %d %Y")
    except ValueError:
        return date_str


def _ms_to_str(t_ms: int) -> str:
    """Render elapsed game-time milliseconds as ``MM:SS`` (minutes may exceed 99)."""
    total_seconds = max(0, t_ms) // 1000
    return f"{total_seconds // 60:02d}:{total_seconds % 60:02d}"


def _read_raw(path_or_raw: str | bytes) -> bytes:
    if isinstance(path_or_raw, (bytes, bytearray)):
        return bytes(path_or_raw)
    with open(path_or_raw, "rb") as fh:
        return fh.read()


# ─────────────────────────────────────────────────────────────────────────────
# Player-name recovery (best effort)
# ─────────────────────────────────────────────────────────────────────────────
def resolve_players(path_or_raw: str | bytes) -> dict[int, str]:
    """Best-effort recovery of ``{player_id: name}`` from the replay header.

    Approach attempted
    ------------------
    The structured header parser fails, but the header *does* zlib-decompress
    cleanly (raw DEFLATE, no zlib wrapper). We decompress it and scan the decoded
    bytes for printable, name-shaped strings in the early player-metadata region.

    Reliability — IMPORTANT
    -----------------------
    In practice this turned out to be **unreliable** for these Voobly VER 9.F
    files: the player-name region of the decompressed header is interleaved with
    binary player-data, and the Voobly mod's altered layout means a byte scan
    pulls back short mojibake runs (e.g. ``'(<A'``, ``'E6>'``) rather than real
    names. Emitting those would be worse than no name at all, so the scanner is
    intentionally **strict**: a candidate must look like a plausible handle
    (letters, sane length, mostly-alphabetic). When nothing passes — which is the
    common case here — we fall back cleanly to ``{pid: f"Player {pid}"}`` for the
    standard 1..8 slots.

    The fallback is the expected outcome for most files; real names will only be
    recovered properly once the structured header is understood for this Voobly
    build. Downstream code treats these names as best-effort *metadata only*,
    never as keys (the keys are always numeric player ids).

    Returns
    -------
    ``{player_id: name}`` for ids 1..8.
    """
    fallback = {pid: f"Player {pid}" for pid in range(1, 9)}

    try:
        raw = _read_raw(path_or_raw)
        header_len = struct.unpack("<I", raw[:4])[0]
        # Voobly headers are raw DEFLATE streams; the stream may start a few
        # bytes in (after a save-meta int) depending on the build, so try a few
        # plausible offsets.
        header: bytes | None = None
        for start in (8, 4, 12):
            try:
                header = zlib.decompress(raw[start : 4 + header_len], -zlib.MAX_WBITS)
                break
            except zlib.error:
                continue
        if header is None:
            return fallback

        names = _scan_player_names(header)
        if not names:
            return fallback

        resolved = dict(fallback)
        for pid, name in zip(range(1, 9), names):
            resolved[pid] = name
        return resolved
    except Exception:
        # Name recovery must never break ingestion.
        return fallback


def _looks_like_name(text: str) -> bool:
    """Strict filter: does ``text`` plausibly look like a player handle?

    Deliberately conservative — we would rather return nothing (and let the
    ``Player N`` fallback apply) than surface binary mojibake as a "name".
    """
    if not (3 <= len(text) <= 20):
        return False
    letters = sum(c.isalpha() for c in text)
    # Require it to be mostly letters/spaces — handles can contain digits and a
    # few symbols, but a real name is not majority punctuation.
    if letters < max(3, len(text) * 0.6):
        return False
    # Reject runs containing characters typical of binary noise.
    if any(c in text for c in "{}[]<>\\|`~^"):
        return False
    return True


def _scan_player_names(header: bytes) -> list[str]:
    """Pull candidate player-name strings from a decompressed header.

    Returns plausible, de-duplicated name runs in order. Returns an empty list
    when nothing convincing is found (the common case for these files), which
    triggers the clean ``Player N`` fallback in :func:`resolve_players`.
    """
    candidates: list[str] = []
    seen: set[str] = set()
    run = bytearray()

    def flush() -> None:
        if run:
            try:
                text = run.decode("latin-1").strip()
            except UnicodeDecodeError:
                run.clear()
                return
            if (
                text
                and text not in seen
                and not text.startswith("VER ")
                and text not in {"Player"}
                and _looks_like_name(text)
            ):
                seen.add(text)
                candidates.append(text)
        run.clear()

    # Player metadata lives early in the header; limit the scan to avoid map and
    # scenario strings deeper in the structure.
    for byte in header[:4096]:
        if 0x20 <= byte <= 0x7E:
            run.append(byte)
        else:
            flush()
    flush()

    return candidates


# ─────────────────────────────────────────────────────────────────────────────
# Core body walk
# ─────────────────────────────────────────────────────────────────────────────
def parse_match_timeline(path: str) -> dict:
    """Walk one replay's body into a per-player technical event timeline.

    Returns
    -------
    dict with keys::

        match_id          str   filename stem
        date              str   human date from the filename
        duration_ms       int   authoritative (POSTGAME) or SYNC fallback
        duration_sync_ms  int   SYNC-accumulated total (cross-check)
        complete          bool  POSTGAME completion flag (False if no POSTGAME)
        players           dict  {pid: name} (best effort)
        events            list  [{t_ms, t_str, player_id, action, obj_id,
                                  obj_name, category, extras}]

    Raises
    ------
    UnreadableReplay
        If the body cannot be walked (corrupt op stream, no events recovered).
    """
    match_id = match_id_from_path(path)

    try:
        raw = _read_raw(path)
    except OSError as exc:
        raise UnreadableReplay(f"{match_id}: cannot read file: {exc}") from exc

    if len(raw) < 4:
        raise UnreadableReplay(f"{match_id}: file too small to contain a header")

    header_len = struct.unpack("<I", raw[:4])[0]
    body = raw[4 + header_len :]
    data = io.BytesIO(body)
    data.read(_BODY_PREAMBLE_BYTES)
    body_len = len(body)

    total_ms = 0
    events: list[dict] = []
    postgame_duration: int | None = None
    postgame_complete = False
    # Number of body operations decoded without error. A replay is "readable" if
    # we walked a meaningful run of its op stream — even if it yielded zero
    # *timeline* events (a very short game may contain only MOVE/ORDER ops, which
    # we intentionally do not record). Corruption shows up as an invalid op id or
    # a truncated op *before* any real progress, and that is what we treat as
    # UnreadableReplay.
    ops_processed = 0

    while True:
        chunk = data.read(4)
        if len(chunk) < 4:
            break  # clean EOF

        op_id = struct.unpack("<I", chunk)[0]
        try:
            op = Operation(op_id)
        except ValueError as exc:
            # Invalid operation id mid-stream. If we have already walked a real
            # run of the stream, treat it as a (recoverable) desync and keep what
            # we have; otherwise the file is genuinely corrupt (the 2 known-bad
            # files surface here at offset 24, having processed nothing).
            if ops_processed > 0:
                break
            raise UnreadableReplay(
                f"{match_id}: invalid operation id {op_id} at offset "
                f"{data.tell() - 4}/{body_len}"
            ) from exc

        try:
            if op == Operation.SYNC:
                increment, _, _ = fast_sync(data)
                total_ms += increment

            elif op == Operation.VIEWLOCK:
                data.read(12)

            elif op == Operation.ACTION:
                pg = _handle_action(data, total_ms, events)
                if pg is not None:
                    postgame_duration, postgame_complete = pg
                    break  # POSTGAME is the last meaningful op

            elif op == Operation.CHAT:
                _, length = struct.unpack("<II", data.read(8))
                data.read(length)

            elif op == Operation.START:
                # Variable-length start block; replicate mgz.fast.start logic.
                data.read(20)
                a, b, _ = struct.unpack("<III", data.read(12))
                if a != 0:  # AOC 1.0x
                    data.seek(-12, 1)
                if b == 2:  # DE
                    data.seek(-8, 1)

            elif op == Operation.SAVE:
                data.seek(-4, 1)
                pos = data.tell()
                length, _ = struct.unpack("<II", data.read(8))
                data.read(length - pos - 8)

            ops_processed += 1

        except struct.error as exc:
            # A truncated trailing op. If we already walked a real run of the
            # stream, treat it as end-of-stream truncation and keep our results;
            # otherwise the file is unreadable.
            if ops_processed > 0:
                break
            raise UnreadableReplay(
                f"{match_id}: truncated {op.name} op at offset "
                f"{data.tell()}/{body_len}: {exc}"
            ) from exc

    if ops_processed == 0:
        # We never decoded a single op — nothing usable in the body.
        raise UnreadableReplay(f"{match_id}: no decodable operations in body")

    duration_ms = postgame_duration if postgame_duration else total_ms

    return {
        "match_id": match_id,
        "date": date_from_path(path),
        "duration_ms": duration_ms,
        "duration_sync_ms": total_ms,
        "complete": postgame_complete,
        "players": resolve_players(raw),
        "events": events,
    }


def _handle_action(
    data: io.BytesIO, total_ms: int, events: list[dict]
) -> tuple[int, bool] | None:
    """Read one ACTION op, append an event if relevant, return POSTGAME info.

    Returns ``(duration_ms, complete)`` when the action is POSTGAME (signalling
    the caller to stop), otherwise ``None``.
    """
    length, = struct.unpack("<I", data.read(4))
    action_id = data.read(1)[0]
    action_bytes = data.read(length - 1)
    struct.unpack("<I", data.read(4))  # trailing sequence (consumed, unused)

    # Skip the Voobly heartbeat before it ever reaches the Action enum.
    if action_id == _HEARTBEAT_ACTION_ID:
        return None

    if action_id == _POSTGAME_ACTION_ID:
        return _parse_postgame(action_bytes + data.read())

    try:
        action_type = Action(action_id)
    except ValueError:
        # Unknown but non-fatal action id; skip it.
        return None

    if action_type not in _TIMELINE_ACTIONS:
        return None

    try:
        payload = parse_action(action_type, action_bytes)
    except struct.error:
        return None

    _append_event(events, action_type, payload, total_ms)
    return None


def _parse_postgame(payload_bytes: bytes) -> tuple[int, bool]:
    """Parse the POSTGAME action body for authoritative duration + complete flag.

    The construct struct exposes the duration two ways: ``duration_int`` (raw
    **seconds**) and ``duration`` (a ``HH:MM:SS`` *string* produced by
    ``TimeSecAdapter``). We use ``duration_int`` and convert to milliseconds.
    """
    try:
        pg = postgame_struct.parse(payload_bytes)
        seconds = getattr(pg, "duration_int", None)
        if seconds is None:
            # Fall back to parsing the HH:MM:SS string form.
            seconds = _hms_to_seconds(getattr(pg, "duration", None))
        duration_ms = int(seconds) * 1000 if seconds else 0
        complete = bool(getattr(pg, "complete", False))
        return duration_ms, complete
    except Exception:
        # POSTGAME present but unparseable — let the SYNC sum stand in.
        return 0, False


def _hms_to_seconds(text: object) -> int:
    """Convert a ``HH:MM:SS`` (or ``MM:SS``) string to seconds; 0 on failure."""
    if not isinstance(text, str):
        return 0
    try:
        parts = [int(p) for p in text.split(":")]
    except ValueError:
        return 0
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds


def _append_event(
    events: list[dict], action_type: Action, payload: dict, t_ms: int
) -> None:
    """Translate a parsed action payload into a timeline event record."""
    # In the legacy Voobly action format, QUEUE / MULTIQUEUE / STANCE / TOWN_BELL
    # etc. carry no player_id (the player is identified only by the producing
    # object, whose owner is not recoverable from the command stream). We keep an
    # honest sentinel rather than guessing. BUILD / WALL / GATE / TRIBUTE / RESIGN
    # / FLARE / DELETE *do* carry a real player_id.
    raw_player_id = payload.get("player_id")
    player_id = raw_player_id if raw_player_id is not None else UNATTRIBUTED_PLAYER_ID
    obj_id: int | None = None
    obj_name = ""
    category = dat_ids.UNKNOWN
    extras: dict = {}

    if action_type in (Action.BUILD, Action.WALL, Action.GATE):
        obj_id = payload.get("building_id")
        if obj_id is not None:
            obj_name, category = dat_ids.get_obj(obj_id)
        if "x" in payload and "y" in payload:
            extras["pos"] = [round(payload["x"], 1), round(payload["y"], 1)]

    elif action_type in (Action.QUEUE, Action.MULTIQUEUE):
        obj_id = payload.get("unit_id")
        if obj_id is not None:
            obj_name, category = dat_ids.get_obj(obj_id)
        if payload.get("amount"):
            extras["amount"] = payload["amount"]

    elif action_type in (Action.TRIBUTE, Action.DE_TRIBUTE):
        extras["to"] = payload.get("player_id_to")
        for res in ("food", "wood", "gold", "stone"):
            if payload.get(res):
                extras[res] = round(payload[res], 1)
        if payload.get("amount"):
            extras["amount"] = round(payload["amount"], 1)
        if payload.get("resource_id") is not None:
            extras["resource_id"] = payload["resource_id"]

    elif action_type in (Action.BUY, Action.SELL):
        extras["resource_id"] = payload.get("resource_id")
        extras["amount"] = payload.get("amount")

    elif action_type == Action.STANCE:
        extras["stance_id"] = payload.get("stance_id")
        extras["n_units"] = len(payload.get("object_ids", []))

    elif action_type == Action.FLARE:
        if "x" in payload and "y" in payload:
            extras["pos"] = [round(payload["x"], 1), round(payload["y"], 1)]

    # RESIGN, TOWN_BELL, BACK_TO_WORK, REPAIR, DELETE, UNGARRISON carry little
    # beyond player/objects; we still log them for behavioural signals.
    elif action_type in (Action.DELETE, Action.UNGARRISON):
        extras["n_units"] = len(payload.get("object_ids", []))

    events.append(
        {
            "t_ms": t_ms,
            "t_str": _ms_to_str(t_ms),
            "player_id": player_id,
            "action": action_type.name,
            "obj_id": obj_id,
            "obj_name": obj_name,
            "category": category,
            "extras": extras,
        }
    )
