"""Pipeline 3 — S3/MinIO-backed player profile storage.

Stores two objects per player profile in bucket ``player-profiles``:

    profiles/{player_name}/profile.json   structured profile (machine-readable)
    profiles/{player_name}/profile.md     the same profile, human-readable

All access goes through boto3 with a configurable ``endpoint_url`` (see
``pipeline/config.py``). Locally this points at MinIO
(``docker compose -f infra/docker-compose.yml up -d``, S3 API on port 9000,
console on port 9001, login localadmin/localpassword123). Pointing the SAME
code at real AWS S3 is just a config change: set ``S3_ENDPOINT_URL=""`` and
provide real credentials via the standard AWS mechanisms (env vars,
~/.aws/credentials, or an IAM role) — no code changes.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .config import (
    AWS_REGION,
    S3_BUCKET_NAME,
    S3_ENDPOINT_URL,
    S3_LOCAL_ACCESS_KEY_ID,
    S3_LOCAL_SECRET_ACCESS_KEY,
)

BUCKET_NAME = S3_BUCKET_NAME


def _client():
    """Build a boto3 S3 client pointed at the configured target.

    Raises a clear, friendly error (not a raw traceback) if boto3 is missing.
    """
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - environment guard
        raise ImportError(
            "boto3 is not installed. Run:\n"
            "    pip install -r pipeline/requirements.txt"
        ) from exc

    kwargs = {"region_name": AWS_REGION}
    if S3_ENDPOINT_URL is not None:
        # Local dev: MinIO. Real creds are never used here — only against
        # real AWS, where S3_ENDPOINT_URL is unset and boto3 falls through to
        # the standard credential chain (env vars / ~/.aws/credentials / IAM).
        kwargs["endpoint_url"] = S3_ENDPOINT_URL
        kwargs["aws_access_key_id"] = S3_LOCAL_ACCESS_KEY_ID
        kwargs["aws_secret_access_key"] = S3_LOCAL_SECRET_ACCESS_KEY

    return boto3.client("s3", **kwargs)


def ensure_bucket(client=None) -> None:
    """Create the profiles bucket if it doesn't already exist.

    Idempotent: treats BucketAlreadyOwnedByYou / BucketAlreadyExists (and a
    plain 404-then-create race) as success rather than an error. Raises a
    clear, friendly error if the endpoint is unreachable — almost always
    because the Docker container (MinIO) is not running.
    """
    client = client or _client()

    try:
        client.head_bucket(Bucket=BUCKET_NAME)
        return  # already exists and we can see it
    except Exception:
        pass  # doesn't exist yet (or head_bucket isn't supported) - try create

    try:
        client.create_bucket(Bucket=BUCKET_NAME)
    except Exception as exc:
        error_code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
        if error_code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            return
        target = S3_ENDPOINT_URL or f"AWS region {AWS_REGION}"
        raise SystemExit(
            f"\nERROR: could not reach/create bucket '{BUCKET_NAME}' at {target}.\n"
            "Is the Docker container up? Start it with:\n"
            "    docker compose -f infra/docker-compose.yml up -d\n"
            f"(underlying error: {type(exc).__name__}: {exc})"
        ) from exc


def _profile_keys(player_name: str) -> tuple[str, str]:
    """Return the (json_key, markdown_key) for a player's profile."""
    safe_name = player_name.strip().replace("/", "_")
    base = f"profiles/{safe_name}"
    return f"{base}/profile.json", f"{base}/profile.md"


def put_profile(
    player_name: str,
    json_obj: dict,
    markdown_text: str,
    client=None,
) -> tuple[str, str]:
    """Write both the structured (.json) and human-readable (.md) profile.

    Overwrites any previous profile for this player (keys are stable, not
    timestamped) — re-running pipeline 3 for a player simply refreshes their
    profile. ``json_obj`` is stamped with a ``generated_at`` UTC ISO timestamp
    if not already present. Returns the (json_key, md_key) written.
    """
    client = client or _client()
    json_key, md_key = _profile_keys(player_name)

    json_obj = dict(json_obj)
    json_obj.setdefault("generated_at", datetime.now(timezone.utc).isoformat())

    client.put_object(
        Bucket=BUCKET_NAME,
        Key=json_key,
        Body=json.dumps(json_obj, indent=2, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )
    client.put_object(
        Bucket=BUCKET_NAME,
        Key=md_key,
        Body=markdown_text.encode("utf-8"),
        ContentType="text/markdown",
    )
    return json_key, md_key


def get_profile(player_name: str, client=None) -> tuple[dict, str]:
    """Fetch back a player's stored profile as ``(json_obj, markdown_text)``.

    Raises ``FileNotFoundError`` if no profile has been stored for this
    player yet (translated from S3's NoSuchKey).
    """
    client = client or _client()
    json_key, md_key = _profile_keys(player_name)

    try:
        json_resp = client.get_object(Bucket=BUCKET_NAME, Key=json_key)
        json_obj = json.loads(json_resp["Body"].read().decode("utf-8"))
    except Exception as exc:
        error_code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
        if error_code in ("NoSuchKey", "404"):
            raise FileNotFoundError(
                f"No stored profile found for player '{player_name}' "
                f"(expected key '{json_key}' in bucket '{BUCKET_NAME}')."
            ) from exc
        raise

    md_resp = client.get_object(Bucket=BUCKET_NAME, Key=md_key)
    markdown_text = md_resp["Body"].read().decode("utf-8")

    return json_obj, markdown_text


def list_profiles(client=None) -> list[str]:
    """Return the names of all players that have a stored profile.

    Enumerates ``profiles/{name}/profile.json`` keys in the bucket. Returns an
    empty list if the bucket is empty. Lets connection errors propagate — the
    caller decides how to degrade.
    """
    client = client or _client()
    names: list[str] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET_NAME, Prefix="profiles/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/profile.json"):
                name = key[len("profiles/"):-len("/profile.json")]
                if name:
                    names.append(name)
    return names
