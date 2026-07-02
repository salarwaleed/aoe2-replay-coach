"""Shared body-walker for the corpus survey.

Mirrors D:\\my-portfolio\\discord bot\\pipeline\\replay_parser.py's structure
(4-byte header-length prefix, 24-byte body preamble, SYNC/VIEWLOCK/ACTION/CHAT
ops, skip Voobly heartbeat action id 177, POSTGAME id 255) but:
  - records EVERY action (not just the curated _TIMELINE_ACTIONS subset)
  - keeps raw action_bytes for actions whose id is NOT in mgz's Action enum
  - keeps object_ids/player_id from the legacy parse_action for the actions
    named in the mission (ORDER, MOVE, WALL, DELETE, FORMATION, BUILD, FLARE,
    TRIBUTE/DE_TRIBUTE, BUY, SELL, RESIGN, TOWN_BELL, GAME, QUEUE, MULTIQUEUE,
    GATHER_POINT, STANCE, STOP, FOLLOW, GUARD, ATTACK_GROUND, UNGARRISON, REPAIR)

This does NOT import pipeline/ (read-only mission; we don't want a dependency
on the bot's package initialisation). We re-implement the tiny bit of
structure we need directly against the installed `mgz` package.
"""
from __future__ import annotations

import io
import struct
import sys

sys.path.insert(0, r"D:\AppData\Roaming\Python\Python313\site-packages")

from mgz.fast import parse_action, sync as fast_sync
from mgz.fast.enums import Action, Operation

_HEARTBEAT_ACTION_ID = 177
_POSTGAME_ACTION_ID = 255
_BODY_PREAMBLE_BYTES = 24


class UnreadableReplay(Exception):
    pass


def read_raw(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def walk_body(path: str, raw: bytes | None = None):
    """Walk one replay's body, yielding raw per-action records.

    Returns (records, total_ms, ops_processed, postgame_duration, postgame_complete)

    records: list of dicts:
        {
            't_ms': int,
            'action_id': int,
            'known': bool,          # whether action_id is a valid mgz Action
            'action_name': str,     # Action.name or f"UNKNOWN_{id}"
            'payload': dict | None, # legacy parse_action() result if known & parseable
            'raw_bytes': bytes,     # action_bytes (post length+id, pre trailing seq)
        }
    """
    match_id = path
    if raw is None:
        raw = read_raw(path)

    if len(raw) < 4:
        raise UnreadableReplay(f"{match_id}: file too small")

    header_len = struct.unpack("<I", raw[:4])[0]
    body = raw[4 + header_len:]
    data = io.BytesIO(body)
    data.read(_BODY_PREAMBLE_BYTES)
    body_len = len(body)

    total_ms = 0
    records = []
    ops_processed = 0
    postgame_duration = None
    postgame_complete = False

    while True:
        chunk = data.read(4)
        if len(chunk) < 4:
            break

        op_id = struct.unpack("<I", chunk)[0]
        try:
            op = Operation(op_id)
        except ValueError as exc:
            if ops_processed > 0:
                break
            raise UnreadableReplay(
                f"{match_id}: invalid operation id {op_id} at offset {data.tell()-4}/{body_len}"
            ) from exc

        try:
            if op == Operation.SYNC:
                increment, _, _ = fast_sync(data)
                total_ms += increment

            elif op == Operation.VIEWLOCK:
                data.read(12)

            elif op == Operation.ACTION:
                pg = _handle_action(data, total_ms, records)
                if pg is not None:
                    postgame_duration, postgame_complete = pg
                    ops_processed += 1
                    break

            elif op == Operation.CHAT:
                _, length = struct.unpack("<II", data.read(8))
                data.read(length)

            elif op == Operation.START:
                data.read(20)
                a, b, _ = struct.unpack("<III", data.read(12))
                if a != 0:
                    data.seek(-12, 1)
                if b == 2:
                    data.seek(-8, 1)

            elif op == Operation.SAVE:
                data.seek(-4, 1)
                pos = data.tell()
                length, _ = struct.unpack("<II", data.read(8))
                data.read(length - pos - 8)

            ops_processed += 1

        except struct.error as exc:
            if ops_processed > 0:
                break
            raise UnreadableReplay(
                f"{match_id}: truncated {op.name} op at offset {data.tell()}/{body_len}: {exc}"
            ) from exc

    if ops_processed == 0:
        raise UnreadableReplay(f"{match_id}: no decodable operations in body")

    return records, total_ms, ops_processed, postgame_duration, postgame_complete


def _handle_action(data: io.BytesIO, total_ms: int, records: list) -> tuple | None:
    length, = struct.unpack("<I", data.read(4))
    action_id = data.read(1)[0]
    action_bytes = data.read(length - 1)
    struct.unpack("<I", data.read(4))  # trailing sequence

    if action_id == _HEARTBEAT_ACTION_ID:
        return None

    if action_id == _POSTGAME_ACTION_ID:
        return _parse_postgame_duration(action_bytes + data.read())

    try:
        action_type = Action(action_id)
    except ValueError:
        records.append({
            "t_ms": total_ms,
            "action_id": action_id,
            "known": False,
            "action_name": f"UNKNOWN_{action_id}",
            "payload": None,
            "raw_bytes": action_bytes,
        })
        return None

    payload = None
    try:
        payload = parse_action(action_type, action_bytes)
    except struct.error:
        payload = None
    except Exception:
        payload = None

    records.append({
        "t_ms": total_ms,
        "action_id": action_id,
        "known": True,
        "action_name": action_type.name,
        "payload": payload,
        "raw_bytes": action_bytes,
    })
    return None


def _parse_postgame_duration(payload_bytes: bytes):
    try:
        from mgz.body.actions import postgame as postgame_struct
        pg = postgame_struct.parse(payload_bytes)
        seconds = getattr(pg, "duration_int", None)
        if seconds is None:
            text = getattr(pg, "duration", None)
            seconds = 0
            if isinstance(text, str):
                parts = [int(p) for p in text.split(":")]
                for p in parts:
                    seconds = seconds * 60 + p
        duration_ms = int(seconds) * 1000 if seconds else 0
        complete = bool(getattr(pg, "complete", False))
        return duration_ms, complete
    except Exception:
        return 0, False
