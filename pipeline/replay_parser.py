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
from .civ_ids import CIV_ID_TO_NAME
from .config import UNATTRIBUTED_PLAYER_ID

# Voobly anti-cheat heartbeat injected into the action stream.
_HEARTBEAT_ACTION_ID = 177
# POSTGAME action id (see mgz.fast.enums.Action.POSTGAME).
_POSTGAME_ACTION_ID = 255
# Bytes of leading meta/start block to skip after the header (per §3).
_BODY_PREAMBLE_BYTES = 24

# Actions that carry a meaningful player intent we want in the timeline.
# (MOVE/ORDER/FORMATION are intentionally excluded from the *timeline* — they are
# high-volume and the reference signals do not yet use them. They are still
# decoded — see _OWNERSHIP_CLAIM_ACTIONS below — purely to feed the ownership
# ledger used to attribute QUEUE/MULTIQUEUE events; they never become events.)
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

# Actions whose payload can carry BOTH a real player_id and a non-empty
# object_ids list — i.e. actions that can prove "this object belongs to this
# player" (see the ownership ledger in _build_ownership_ledger). ORDER/MOVE/
# FORMATION are decoded *only* for this purpose (they are not in
# _TIMELINE_ACTIONS). WALL and DELETE are already decoded for the timeline, so
# their already-parsed payloads are reused for claims too, at no extra parse
# cost.
_OWNERSHIP_CLAIM_ACTIONS = {
    Action.ORDER,
    Action.MOVE,
    Action.FORMATION,
    Action.WALL,
    Action.DELETE,
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
# Player-name / civ / color recovery (best effort)
# ─────────────────────────────────────────────────────────────────────────────
# Empirically observed value of the per-player ``num_header_data`` field for
# these Voobly v1.6 recordings. When it holds, the civ/color/spawn block sits at
# a fixed offset from the start of the player's stats block (see
# ``_PS_BLOCK_OFFSET`` below). When a file has a different value we fall back to
# scanning a window for a block that passes the sanity checks.
_EXPECTED_NUM_HEADER_DATA = 478
# Offset (in bytes) from ``ps_start`` to the civ/color/spawn block, valid when
# ``num_header_data == _EXPECTED_NUM_HEADER_DATA``.
_PS_BLOCK_OFFSET = 1925
# Fallback scan window (relative to ps_start) used when num_header_data differs
# from the expected value.
_PS_SCAN_START = 1700
_PS_SCAN_END = 2200
_MAP_COORD_MAX = 300


def _decompress_header(raw: bytes) -> bytes | None:
    """Best-effort raw-DEFLATE decompress of the replay header.

    Voobly headers are raw DEFLATE streams (no zlib wrapper); the stream start
    offset varies a little by build, so a few plausible starts are tried.
    """
    if len(raw) < 4:
        return None
    header_len = struct.unpack("<I", raw[:4])[0]
    for start in (8, 4, 12):
        try:
            return zlib.decompress(raw[start : 4 + header_len], -zlib.MAX_WBITS)
        except zlib.error:
            continue
    return None


def _find_name_candidates(data: bytes) -> list[tuple[int, str]]:
    """Find ``player_name`` occurrences inside the header's ``attributes`` struct.

    Each candidate is an Int16ul length field (``name_len`` including the
    terminator) immediately followed by ASCII text of length ``name_len - 1``,
    then a ``0x00`` terminator byte. Returns ``(name_text_offset, name)`` pairs in
    header order, excluding the synthetic ``GAIA`` player.
    """
    n = len(data)
    out: list[tuple[int, str]] = []
    i = 0
    while i < n - 2:
        ln = struct.unpack_from("<H", data, i)[0]
        if 2 <= ln <= 24:
            s = data[i + 2 : i + 2 + ln - 1]
            term_ok = (i + 2 + ln - 1) < n and data[i + 2 + ln - 1] == 0
            if (
                term_ok
                and len(s) == ln - 1
                and all(32 <= b < 127 for b in s)
                and any(chr(b).isalnum() for b in s)
            ):
                name = s.decode("ascii")
                # Reject very short / mostly-non-alphanumeric runs: these are
                # spurious matches against binary noise elsewhere in the header
                # (e.g. a lone "R") rather than real player handles, and can
                # coincidentally pass the downstream civ/color/spawn sanity
                # checks too. Real handles in practice are >= 2 chars.
                alnum = sum(1 for b in s if chr(b).isalnum())
                if name.upper() != "GAIA" and len(s) >= 2 and alnum >= 2:
                    out.append((i + 2, name))
        i += 1
    return out


def _parse_player_stats(data: bytes, name_off: int, namelen_field_off: int) -> dict | None:
    """Walk forward from a confirmed player-name occurrence to recover the
    civilization id, player color, and spawn location from the per-player
    ``player_stats`` block. Returns ``None`` if the walk runs out of bounds or
    the recovered ``num_header_data`` is implausible.
    """
    n = len(data)
    namelen = struct.unpack_from("<H", data, namelen_field_off)[0]
    pos = name_off + (namelen - 1)
    try:
        pos += 1  # pad 0x00
        pos += 1  # pad 0x16
        if pos + 4 > n:
            return None
        num_header_data = struct.unpack_from("<I", data, pos)[0]
        ps_start = pos + 4 + 1  # +4 for the u32 field itself, +1 for pad 0x21
        if not (0 <= num_header_data <= 2000):
            return None

        offsets: list[int]
        if num_header_data == _EXPECTED_NUM_HEADER_DATA:
            offsets = [_PS_BLOCK_OFFSET]
        else:
            offsets = list(range(_PS_SCAN_START, _PS_SCAN_END))

        for off in offsets:
            block_pos = ps_start + off
            rec = _try_parse_ps_block(data, block_pos)
            if rec is not None:
                return rec
        return None
    except (struct.error, IndexError):
        return None


def _try_parse_ps_block(data: bytes, pos: int) -> dict | None:
    """Parse and sanity-check an 11-byte civ/color/spawn block at ``pos``."""
    n = len(data)
    if pos < 0 or pos + 11 > n:
        return None
    try:
        spawn_x = struct.unpack_from("<H", data, pos)[0]
        spawn_y = struct.unpack_from("<H", data, pos + 2)[0]
        culture = data[pos + 4]
        civ = data[pos + 5]
        game_status = data[pos + 6]
        resigned = data[pos + 7]
        # data[pos + 8] is an unused pad byte.
        color = data[pos + 9]
    except (struct.error, IndexError):
        return None

    if not (0 < spawn_x < _MAP_COORD_MAX and 0 < spawn_y < _MAP_COORD_MAX):
        return None
    if not (0 <= civ <= 90):
        return None
    if not (0 <= color <= 7):
        return None

    return {
        "civ_id": civ,
        "civ_name": CIV_ID_TO_NAME.get(civ, f"Civ{civ}"),
        "color": color,
        "culture": culture,
        "spawn": (spawn_x, spawn_y),
        "game_status": game_status,
        "resigned": resigned,
    }


def _extract_player_records(header: bytes) -> list[dict]:
    """Recover per-player ``{name, civ_id, civ_name, color, ...}`` records from a
    decompressed header, in header (i.e. slot) order, de-duplicated by name.
    """
    records: list[dict] = []
    seen_names: set[str] = set()
    for name_off, name in _find_name_candidates(header):
        if name in seen_names:
            continue
        namelen_field_off = name_off - 2
        rec = _parse_player_stats(header, name_off, namelen_field_off)
        if rec is None:
            continue
        seen_names.add(name)
        records.append({"name": name, **rec})
    return records


def resolve_players(path_or_raw: str | bytes) -> dict[int, str]:
    """Best-effort recovery of ``{player_id: name}`` from the replay header.

    The structured ``mgz`` header parser fails on these Voobly VER 9.F files, but
    the header does zlib-decompress cleanly (raw DEFLATE, no zlib wrapper). We
    decompress it, locate each player's ``name`` field inside the ``attributes``
    struct, and walk forward through the known struct layout to the per-player
    stats block to recover real names (and, via :func:`resolve_player_civs`,
    civ/color/spawn).

    Falls back to ``{pid: f"Player {pid}"}`` for the standard 1..8 slots
    whenever recovery fails for any reason — this function must never raise.

    Returns
    -------
    ``{player_id: name}`` for ids 1..8.
    """
    fallback = {pid: f"Player {pid}" for pid in range(1, 9)}
    try:
        raw = _read_raw(path_or_raw)
        header = _decompress_header(raw)
        if header is None:
            return fallback

        records = _extract_player_records(header)
        if not records:
            return fallback

        resolved = dict(fallback)
        for pid, rec in zip(range(1, 9), records):
            resolved[pid] = rec["name"]
        return resolved
    except Exception:
        # Name recovery must never break ingestion.
        return fallback


def resolve_player_civs(path_or_raw: str | bytes) -> dict[int, dict]:
    """Best-effort recovery of ``{player_id: {civ_id, civ_name, color, ...}}``.

    Companion to :func:`resolve_players`, built from the same header walk.
    Players for whom the civ/color/spawn block could not be recovered (or for
    slots beyond the number of header records found) are simply absent from the
    returned dict — callers should treat a missing key as "unknown".

    Returns
    -------
    ``{player_id: {civ_id, civ_name, color, culture, spawn, game_status,
    resigned}}`` for whichever of ids 1..8 were successfully recovered.
    """
    try:
        raw = _read_raw(path_or_raw)
        header = _decompress_header(raw)
        if header is None:
            return {}

        records = _extract_player_records(header)
        civs: dict[int, dict] = {}
        for pid, rec in zip(range(1, 9), records):
            civs[pid] = {k: v for k, v in rec.items() if k != "name"}
        return civs
    except Exception:
        # Civ recovery must never break ingestion.
        return {}


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
        ownership         dict  {claims, conflicts, queue_attributed,
                                  queue_total} — see _build_ownership_ledger
                                  and _attribute_queue_events.

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
    # Ownership ledger: object_id -> player_id, built from every action whose
    # payload proves "this player controls this object" (ORDER/MOVE/FORMATION/
    # WALL/DELETE). Used after the walk to attribute QUEUE/MULTIQUEUE events to
    # the player who provably controls the producing building. See
    # _record_ownership_claims and _attribute_queue_events.
    ledger: dict[int, int] = {}
    ledger_conflicts = 0
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
                pg, conflict = _handle_action(data, total_ms, events, ledger)
                ledger_conflicts += conflict
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

    queue_attributed, queue_total = _attribute_queue_events(events, ledger)

    return {
        "match_id": match_id,
        "date": date_from_path(path),
        "duration_ms": duration_ms,
        "duration_sync_ms": total_ms,
        "complete": postgame_complete,
        "players": resolve_players(raw),
        "player_civs": resolve_player_civs(raw),
        "events": events,
        "ownership": {
            "claims": len(ledger),
            "conflicts": ledger_conflicts,
            "queue_attributed": queue_attributed,
            "queue_total": queue_total,
        },
    }


def _handle_action(
    data: io.BytesIO, total_ms: int, events: list[dict], ledger: dict[int, int]
) -> tuple[tuple[int, bool] | None, int]:
    """Read one ACTION op, append an event if relevant, return POSTGAME info.

    Also feeds the ownership ``ledger`` (``object_id -> player_id``) from any
    action that proves ownership (see ``_OWNERSHIP_CLAIM_ACTIONS``), whether or
    not that action type is also a timeline event.

    Returns ``(postgame_info, conflict_count)``, where ``postgame_info`` is
    ``(duration_ms, complete)`` when the action is POSTGAME (signalling the
    caller to stop) or ``None`` otherwise, and ``conflict_count`` is ``1`` if
    this action caused an existing ledger entry to be discarded due to a
    conflicting claim (0 otherwise; see ``_record_ownership_claims``).
    """
    length, = struct.unpack("<I", data.read(4))
    action_id = data.read(1)[0]
    action_bytes = data.read(length - 1)
    struct.unpack("<I", data.read(4))  # trailing sequence (consumed, unused)

    # Skip the Voobly heartbeat before it ever reaches the Action enum.
    if action_id == _HEARTBEAT_ACTION_ID:
        return None, 0

    if action_id == _POSTGAME_ACTION_ID:
        return _parse_postgame(action_bytes + data.read()), 0

    try:
        action_type = Action(action_id)
    except ValueError:
        # Unknown but non-fatal action id; skip it.
        return None, 0

    is_timeline = action_type in _TIMELINE_ACTIONS
    is_claim = action_type in _OWNERSHIP_CLAIM_ACTIONS
    if not is_timeline and not is_claim:
        return None, 0

    try:
        payload = parse_action(action_type, action_bytes)
    except struct.error:
        return None, 0

    conflict = 0
    if is_claim:
        conflict = _record_ownership_claims(ledger, payload)

    if is_timeline:
        _append_event(events, action_type, payload, total_ms)

    return None, conflict


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


def _fix_wall_coord(v: int) -> int:
    """Undo the vendored ``mgz`` library's signed-byte wraparound for WALL tile
    coordinates: any coordinate past tile 127 is read back as negative (e.g.
    ``-64`` instead of ``192``). We do not patch ``mgz`` itself — this is a local
    correction applied only when building the WALL event's ``extras``.
    """
    return v + 256 if v < 0 else v


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
        if action_type == Action.WALL:
            # The vendored mgz library reads WALL tile coordinates as signed
            # bytes, so any coordinate past tile 127 wraps negative. Correct it
            # locally here (see _fix_wall_coord) without patching mgz.
            if "x" in payload and "y" in payload:
                extras["pos"] = [
                    _fix_wall_coord(payload["x"]),
                    _fix_wall_coord(payload["y"]),
                ]
            if "x_end" in payload:
                extras["x_end"] = _fix_wall_coord(payload["x_end"])
            if "y_end" in payload:
                extras["y_end"] = _fix_wall_coord(payload["y_end"])
        elif "x" in payload and "y" in payload:
            extras["pos"] = [round(payload["x"], 1), round(payload["y"], 1)]

    elif action_type in (Action.QUEUE, Action.MULTIQUEUE):
        obj_id = payload.get("unit_id")
        if obj_id is not None:
            obj_name, category = dat_ids.get_obj(obj_id)
        if payload.get("amount"):
            extras["amount"] = payload["amount"]
        # The producing building(s) — no player_id is carried by QUEUE/
        # MULTIQUEUE itself, so this is the only lead we have towards
        # attribution. Captured here and consumed by _attribute_queue_events
        # after the full body walk (once the ownership ledger is complete).
        building_ids = payload.get("object_ids")
        if building_ids:
            extras["building_ids"] = list(building_ids)

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


# ─────────────────────────────────────────────────────────────────────────────
# Ownership ledger — attributing QUEUE/MULTIQUEUE via provable building control
# ─────────────────────────────────────────────────────────────────────────────
# QUEUE/MULTIQUEUE (unit production) actions carry no player_id in this legacy
# Voobly action format — only the id(s) of the producing building. But other
# action types (ORDER, MOVE, FORMATION, WALL, DELETE) *do* carry both a real
# player_id and the object_ids being acted on. Whenever one of those actions
# targets an object we have not seen before, that is provable evidence that the
# object belongs to that player — we call this a "claim". After the full body
# walk, any QUEUE/MULTIQUEUE event whose producing building(s) all resolve, in
# the ledger, to one single player is attributed to that player.
#
# This is deliberately conservative:
#   * A claim is only ever recorded from a payload that has BOTH a real
#     player_id and a non-empty object_ids list (see _OWNERSHIP_CLAIM_ACTIONS).
#   * If the SAME object_id is ever claimed by two DIFFERENT player_ids, we do
#     not guess which one is right — we drop that object_id from the ledger
#     entirely (see the conflict branch below) and count the conflict for
#     observability. In practice this should be rare-to-never: it would need
#     object-id reuse after a building/unit is destroyed and a different
#     player's object happens to be assigned the same id later in the same
#     match. Nothing currently detects object destruction/reuse explicitly, so
#     this discard-on-conflict rule is the safety net for that edge case.
#   * Coverage is inherently partial: a building that is only ever queued from
#     and never otherwise touched by ORDER/MOVE/FORMATION/WALL/DELETE in the
#     whole match will simply never appear in the ledger, and its QUEUE events
#     stay under the UNATTRIBUTED_PLAYER_ID sentinel. That is intentional —
#     the design goal is "attribute what is provable", not "attribute
#     everything".
#   * A rare unhandled edge case: a building captured via Monk conversion
#     changes owner mid-match. Since v1 ledger semantics are whole-match (first
#     claim wins, no per-timestamp resolution), a captured building's later
#     QUEUE events would still be attributed to whichever player first claimed
#     it — which could be the *original* owner, not the new one, if the new
#     owner never issues an ORDER/MOVE/FORMATION/WALL/DELETE against it before
#     the corresponding QUEUE event. This is a known, accepted gap; the
#     alternative (tracking per-timestamp ownership) is out of scope for v1.
def _record_ownership_claims(ledger: dict[int, int], payload: dict) -> int:
    """Record ``object_id -> player_id`` claims from one action's payload.

    Only acts when the payload has both a real ``player_id`` and a non-empty
    ``object_ids`` list. Returns ``1`` if this call caused a conflicting
    object_id to be discarded from the ledger, ``0`` otherwise.
    """
    player_id = payload.get("player_id")
    object_ids = payload.get("object_ids")
    if player_id is None or not object_ids:
        return 0

    conflict = 0
    for obj_id in object_ids:
        existing = ledger.get(obj_id)
        if existing is None:
            ledger[obj_id] = player_id
        elif existing != player_id:
            # Conflicting claims for the same object_id: never guess. Remove it
            # entirely so no QUEUE event can be (mis-)attributed via it.
            del ledger[obj_id]
            conflict += 1
    return conflict


def _attribute_queue_events(
    events: list[dict], ledger: dict[int, int]
) -> tuple[int, int]:
    """Post-walk attribution pass for QUEUE/MULTIQUEUE events.

    For every still-unattributed QUEUE/MULTIQUEUE event whose captured
    ``extras["building_ids"]`` all resolve, in ``ledger``, to the same single
    player, set that event's ``player_id`` to that player and mark
    ``extras["attributed_via"] = "ownership_ledger"`` so downstream consumers
    can tell a ledger-derived attribution apart from a genuine payload
    ``player_id``. Events with no building_ids, building_ids not present in
    the ledger, or building_ids owned by more than one player are left
    untouched (sentinel stays).

    Returns
    -------
    ``(queue_attributed, queue_total)`` — counts across all QUEUE/MULTIQUEUE
    events in ``events`` (attributed here or already attributed some other
    way, out of the total), for the caller's ``ownership`` summary.
    """
    queue_total = 0
    queue_attributed = 0
    for event in events:
        if event["action"] not in ("QUEUE", "MULTIQUEUE"):
            continue
        queue_total += 1

        if event["player_id"] != UNATTRIBUTED_PLAYER_ID:
            queue_attributed += 1
            continue

        building_ids = event["extras"].get("building_ids")
        if not building_ids:
            continue

        # Require EVERY building_id to resolve in the ledger (not just some),
        # and all of them to resolve to the SAME player.
        if not all(bid in ledger for bid in building_ids):
            continue
        owners = {ledger[bid] for bid in building_ids}
        if len(owners) == 1:
            (owner,) = owners
            event["player_id"] = owner
            event["extras"]["attributed_via"] = "ownership_ledger"
            queue_attributed += 1

    return queue_attributed, queue_total
