"""Checked-in ordered SQL migrations with content-drift rejection."""

import hashlib
import json
import re
from pathlib import Path

import psycopg
from psycopg import sql

from opsjobs.config import Config, secret

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def migrate(config, folder=MIGRATIONS):
    changed = []
    with psycopg.connect(**config.database()) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(2026100804)")
        if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = 'ops_app'").fetchone():
            conn.execute(
                sql.SQL(
                    "CREATE ROLE ops_app LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE"
                ).format(sql.Literal(secret("/run/secrets/app_password")))
            )
        conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        conn.execute("GRANT CONNECT ON DATABASE opsjobs TO ops_app")
        conn.execute("GRANT USAGE ON SCHEMA public TO ops_app")
        conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations
            (version integer PRIMARY KEY, checksum char(64) NOT NULL,
             applied_at timestamptz NOT NULL DEFAULT clock_timestamp())""")
        conn.execute("GRANT SELECT ON schema_migrations TO ops_app")
        existing = dict(conn.execute("SELECT version, checksum FROM schema_migrations").fetchall())
        files = sorted(folder.glob("*.sql"))
        versions = set()
        for path in files:
            match = re.fullmatch(r"([0-9]{3})_[a-z_]+\.sql", path.name)
            if path.is_symlink() or not match:
                raise ValueError("Invalid migration path")
            version = int(match[1])
            versions.add(version)
            content = path.read_text()
            checksum = hashlib.sha256(content.encode()).hexdigest()
            if version in existing:
                if existing[version] != checksum:
                    raise ValueError("Applied migration content changed")
                continue
            conn.execute(content)
            conn.execute(
                "INSERT INTO schema_migrations(version, checksum) VALUES (%s, %s)",
                (version, checksum),
            )
            changed.append(version)
        if not files or not set(existing) <= versions:
            raise ValueError("Missing applied migration")
    return changed


if __name__ == "__main__":
    print(json.dumps({"migrations_applied": migrate(Config.from_env())}))
