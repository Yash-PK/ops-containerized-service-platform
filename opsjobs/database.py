"""PostgreSQL is the durable queue and source of truth; completion is fenced."""

import uuid

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from opsjobs.domain import Conflict, analyze

FIELDS = "id, status, attempts, result, error_code, created_at, updated_at"


def public(row):
    if row is None:
        return None
    return {
        key: value.isoformat()
        if hasattr(value, "isoformat")
        else str(value)
        if isinstance(value, uuid.UUID)
        else value
        for key, value in row.items()
        if key in {"id", "status", "attempts", "result", "error_code", "created_at", "updated_at"}
    }


class Repository:
    def __init__(self, config):
        self.config = config

    def connect(self):
        return psycopg.connect(**self.config.database(), row_factory=dict_row)

    def ready(self):
        with self.connect() as conn:
            return (
                conn.execute("SELECT max(version) AS version FROM schema_migrations").fetchone()[
                    "version"
                ]
                == 1
            )

    def enqueue(self, text, key):
        digest = analyze(text)["sha256"]
        with self.connect() as conn:
            row = conn.execute(
                f"""INSERT INTO jobs (id, idempotency_key, text_content, content_sha256)
                VALUES (%s, %s, %s, %s) ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING {FIELDS}""",
                (uuid.uuid4(), key, text, digest),
            ).fetchone()
            if row is not None:
                return public(row), True
            row = conn.execute(
                f"SELECT {FIELDS}, content_sha256 FROM jobs WHERE idempotency_key = %s", (key,)
            ).fetchone()
            if row["content_sha256"] != digest:
                raise Conflict("Idempotency key belongs to different content")
            return public(row), False

    def get(self, identifier):
        with self.connect() as conn:
            return public(
                conn.execute(f"SELECT {FIELDS} FROM jobs WHERE id = %s", (identifier,)).fetchone()
            )

    def claim(self):
        token = uuid.uuid4()
        with self.connect() as conn:
            conn.execute("""UPDATE jobs SET status = 'failed', error_code = 'retry_exhausted',
                lease_token = NULL, lease_until = NULL, updated_at = clock_timestamp()
                WHERE status = 'running' AND lease_until < clock_timestamp() AND attempts >= 3""")
            return conn.execute(
                """WITH candidate AS (
                    SELECT id FROM jobs WHERE attempts < 3 AND
                    (status = 'queued' OR (status = 'running' AND lease_until < clock_timestamp()))
                    ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1
                ) UPDATE jobs SET status = 'running', attempts = attempts + 1,
                  lease_token = %s, lease_until = clock_timestamp() + interval '30 seconds',
                  updated_at = clock_timestamp()
                FROM candidate WHERE jobs.id = candidate.id
                RETURNING jobs.id, jobs.text_content, jobs.lease_token""",
                (token,),
            ).fetchone()

    def complete(self, identifier, token, result):
        with self.connect() as conn:
            return (
                conn.execute(
                    """UPDATE jobs SET status = 'succeeded', result = %s, error_code = NULL,
                    lease_token = NULL, lease_until = NULL, updated_at = clock_timestamp()
                    WHERE id = %s AND lease_token = %s AND status = 'running'
                      AND lease_until > clock_timestamp()""",
                    (Jsonb(result), identifier, token),
                ).rowcount
                == 1
            )

    def retry(self, identifier, token):
        with self.connect() as conn:
            return (
                conn.execute(
                    """UPDATE jobs SET status =
                    CASE WHEN attempts < 3 THEN 'queued' ELSE 'failed' END,
                    error_code = 'processing_failed', lease_token = NULL, lease_until = NULL,
                    updated_at = clock_timestamp() WHERE id = %s AND lease_token = %s
                    AND status = 'running'""",
                    (identifier, token),
                ).rowcount
                == 1
            )
