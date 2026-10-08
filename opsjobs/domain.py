"""Deterministic work and bounded public input contracts."""

import hashlib
import re
import uuid

MAX_TEXT_BYTES = 4096


class InvalidInput(ValueError):
    """A public input violates the documented contract."""


class Conflict(ValueError):
    """An idempotency key was reused with different content."""


def payload(value):
    if not isinstance(value, dict) or set(value) != {"text"}:
        raise InvalidInput("Expected exactly one field: text")
    text = value["text"]
    if not isinstance(text, str) or not text.strip():
        raise InvalidInput("text must be a nonempty string")
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError as error:
        raise InvalidInput("text must contain valid Unicode") from error
    if len(encoded) > MAX_TEXT_BYTES or "\x00" in text:
        raise InvalidInput("text exceeds 4096 UTF-8 bytes or contains NUL")
    return text


def idempotency_key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", value):
        raise InvalidInput("Idempotency-Key must contain 8–80 letters, digits, _ or -")
    return value


def job_id(value):
    try:
        result = str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError) as error:
        raise InvalidInput("Invalid job ID") from error
    if result != value:
        raise InvalidInput("Job ID must be canonical lowercase UUID")
    return result


def analyze(text):
    """No shell commands, external URLs or arbitrary code are accepted."""
    payload({"text": text})
    return {
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "bytes": len(text.encode("utf-8")),
        "characters": len(text),
        "words": len(text.split()),
        "lines": len(text.splitlines()),
    }
