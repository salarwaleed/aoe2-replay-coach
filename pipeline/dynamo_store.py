"""Pipeline 2 — DynamoDB-backed match timeline storage.

Stores one item per timeline event in table ``match_timelines``:

    partition key: match_id (S)
    sort key:      sk (S)  =  f"{t_ms:010d}#p{player_id}#{seq}"

Zero-padding ``t_ms`` to 10 digits makes the sort key lexically sortable in
exact chronological order (10 digits covers ~115 days of milliseconds, far
beyond any match length). ``player_id`` is embedded mid-string purely for
readability/debugging; it does not affect chronological ordering since it
sits after the time component. ``seq`` disambiguates same-millisecond events
within a chunk so repeated upserts of the same source produce the same key
(idempotent) instead of duplicating items.

All access goes through boto3 with a configurable ``endpoint_url`` (see
``pipeline/config.py``). Locally this points at DynamoDB Local
(``docker compose -f infra/docker-compose.yml up -d``, port 8001). Pointing
the SAME code at real AWS is just a config change: set
``DYNAMODB_ENDPOINT_URL=""`` and provide real credentials via the standard AWS
mechanisms (env vars, ~/.aws/credentials, or an IAM role) — no code changes.
"""

from __future__ import annotations

from .config import (
    AWS_REGION,
    DYNAMODB_ENDPOINT_URL,
    DYNAMODB_LOCAL_ACCESS_KEY_ID,
    DYNAMODB_LOCAL_SECRET_ACCESS_KEY,
    DYNAMODB_TABLE_NAME,
)

TABLE_NAME = DYNAMODB_TABLE_NAME


def _client():
    """Build a boto3 DynamoDB client/resource pointed at the configured target.

    Raises a clear, friendly error (not a raw traceback) if boto3 is missing
    or the endpoint is unreachable.
    """
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - environment guard
        raise SystemExit(
            "boto3 is not installed. Run:\n"
            "    pip install -r pipeline/requirements.txt"
        ) from exc

    kwargs = {"region_name": AWS_REGION}
    if DYNAMODB_ENDPOINT_URL is not None:
        # Local dev: DynamoDB Local ignores credentials but boto3 still
        # requires *some* values to sign the request.
        kwargs["endpoint_url"] = DYNAMODB_ENDPOINT_URL
        kwargs["aws_access_key_id"] = DYNAMODB_LOCAL_ACCESS_KEY_ID
        kwargs["aws_secret_access_key"] = DYNAMODB_LOCAL_SECRET_ACCESS_KEY
    # else: real AWS — boto3 picks up creds from the standard chain
    # (env vars / ~/.aws/credentials / IAM role).

    return boto3.resource("dynamodb", **kwargs)


def _connect_table():
    """Return the ``match_timelines`` table, creating it if absent.

    Raises a clear, friendly error if the endpoint is unreachable — almost
    always because the Docker container is not running (local dev) or
    credentials/region are misconfigured (real AWS).
    """
    resource = _client()

    try:
        existing = {t.name for t in resource.tables.all()}
    except Exception as exc:
        target = DYNAMODB_ENDPOINT_URL or f"AWS region {AWS_REGION}"
        raise SystemExit(
            f"\nERROR: could not reach DynamoDB at {target}.\n"
            "Is the Docker container up? Start it with:\n"
            "    docker compose -f infra/docker-compose.yml up -d\n"
            f"(underlying error: {type(exc).__name__}: {exc})"
        ) from exc

    if TABLE_NAME not in existing:
        table = resource.create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {"AttributeName": "match_id", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "match_id", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()
        return table

    return resource.Table(TABLE_NAME)


def make_sort_key(t_ms: int, player_id: int, seq: int) -> str:
    """Build the chronologically-sortable sort key for one event.

    ``t_ms`` zero-padded to 10 digits dominates the sort, so items come back
    from a Query in time order regardless of player_id or seq. ``player_id``
    can be -1 (unattributed) — that's fine, it never affects ordering since
    it's embedded after the time component, not used as a numeric sort term.
    """
    return f"{t_ms:010d}#p{player_id}#{seq}"


def put_events(table, match_id: str, events: list[dict]) -> int:
    """Upsert a batch of timeline events for one match.

    Each ``events`` item must have: t_ms, t_str, player_id, player_name,
    action, obj_name, category, sentence, source_chunk_id. The sort key is
    deterministic (time + player + seq), so re-running on the same source
    chunk overwrites the same items rather than duplicating them — the whole
    pipeline is safe to re-run.

    Returns the number of items written.
    """
    if not events:
        return 0

    with table.batch_writer(overwrite_by_pkeys=["match_id", "sk"]) as batch:
        for seq, ev in enumerate(events):
            sk = make_sort_key(ev["t_ms"], ev["player_id"], seq)
            batch.put_item(
                Item={
                    "match_id": match_id,
                    "sk": sk,
                    "t_ms": ev["t_ms"],
                    "t_str": ev["t_str"],
                    "player_id": ev["player_id"],
                    "player_name": ev["player_name"],
                    "action": ev["action"],
                    "obj_name": ev.get("obj_name") or "",
                    "category": ev.get("category") or "",
                    "sentence": ev["sentence"],
                    "source_chunk_id": ev["source_chunk_id"],
                }
            )
    return len(events)


def query_match_timeline(table, match_id: str, limit: int | None = None) -> list[dict]:
    """Query one match's events in chronological order (ascending sort key)."""
    kwargs = {
        "KeyConditionExpression": "match_id = :m",
        "ExpressionAttributeValues": {":m": match_id},
        "ScanIndexForward": True,
    }
    if limit is not None:
        kwargs["Limit"] = limit

    items: list[dict] = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        last_key = resp.get("LastEvaluatedKey")
        if not last_key or (limit is not None and len(items) >= limit):
            break
        kwargs["ExclusiveStartKey"] = last_key
    return items
