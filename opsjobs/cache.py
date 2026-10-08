"""Cache only immutable successful results; failure falls back to PostgreSQL."""

import datetime
import json
import re

import valkey

from opsjobs.config import secret

MAX_CACHE_BYTES = 16384
JOB_FIELDS = {"id", "status", "attempts", "result", "error_code", "created_at", "updated_at"}
RESULT_FIELDS = {"sha256", "bytes", "characters", "words", "lines"}


def completed_record(value, identifier):
    """Treat cached bytes as untrusted derived state, never as durable completion."""
    if not isinstance(value, dict) or set(value) != JOB_FIELDS:
        return False
    if (
        value["id"] != identifier
        or value["status"] != "succeeded"
        or value["error_code"] is not None
    ):
        return False
    if type(value["attempts"]) is not int or not 1 <= value["attempts"] <= 3:
        return False
    result = value["result"]
    if not isinstance(result, dict) or set(result) != RESULT_FIELDS:
        return False
    if not isinstance(result["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", result["sha256"]):
        return False
    if any(type(result[name]) is not int for name in RESULT_FIELDS - {"sha256"}):
        return False
    if not 1 <= result["characters"] <= result["bytes"] <= 4096:
        return False
    if not 1 <= result["words"] <= result["characters"]:
        return False
    if not 1 <= result["lines"] <= result["characters"]:
        return False
    try:
        timestamps = []
        for name in ("created_at", "updated_at"):
            if not isinstance(value[name], str) or len(value[name]) > 64:
                return False
            parsed = datetime.datetime.fromisoformat(value[name])
            if parsed.utcoffset() is None:
                return False
            timestamps.append(parsed)
        return timestamps[0] <= timestamps[1]
    except ValueError:
        return False


def unique_object(pairs):
    value = {}
    for name, item in pairs:
        if name in value:
            raise ValueError("Duplicate cached field")
        value[name] = item
    return value


def reject_constant(_value):
    raise ValueError("Non-finite cached number")


class ResultCache:
    def __init__(self, config):
        self.client = valkey.Valkey(
            host=config.cache_host,
            port=6379,
            password=secret(config.cache_password_file),
            socket_connect_timeout=0.3,
            socket_timeout=0.3,
            decode_responses=True,
            retry_on_timeout=False,
            max_connections=16,
        )

    def get(self, identifier):
        try:
            # GETRANGE bounds the response before a corrupted oversized value is
            # materialized in this process. Its inclusive endpoint adds one byte
            # so truncation is detected instead of accepting a valid prefix.
            value = self.client.getrange("job:" + identifier, 0, MAX_CACHE_BYTES)
            if not value or len(value.encode("utf-8")) > MAX_CACHE_BYTES:
                return None
            result = json.loads(
                value, object_pairs_hook=unique_object, parse_constant=reject_constant
            )
            return result if completed_record(result, identifier) else None
        except valkey.ValkeyError, ValueError, TypeError, RecursionError:
            return None

    def put(self, value):
        if value["status"] != "succeeded":
            return
        try:
            self.client.set("job:" + value["id"], json.dumps(value), ex=60)
        except valkey.ValkeyError:
            pass  # Optional cache never changes acceptance or durable state.
