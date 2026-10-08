"""Explicit application configuration; no inherited cloud or database credentials."""

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path


def secret(path):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or info.st_size > 128:
        raise ValueError("Secret must be a small regular file, not writable by group/others")
    value = path.read_text().strip()
    if not re.fullmatch(r"[a-f0-9]{48}", value):
        raise ValueError("Expected a generated 48-character hexadecimal credential")
    return value


@dataclass(frozen=True)
class Config:
    db_host: str = "database"
    db_user: str = "ops_app"
    db_password_file: str = "/run/secrets/app_password"
    cache_host: str = "cache"
    cache_password_file: str = "/run/secrets/cache_password"

    @classmethod
    def from_env(cls, environ=None):
        env = os.environ if environ is None else environ
        values = {
            "db_host": env.get("OPS_DB_HOST", "database"),
            "db_user": env.get("OPS_DB_USER", "ops_app"),
            "db_password_file": env.get("OPS_DB_PASSWORD_FILE", "/run/secrets/app_password"),
            "cache_host": env.get("OPS_CACHE_HOST", "cache"),
            "cache_password_file": env.get(
                "OPS_CACHE_PASSWORD_FILE", "/run/secrets/cache_password"
            ),
        }
        for name in ("db_host", "cache_host", "db_user"):
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,63}", values[name]):
                raise ValueError("Invalid " + name)
        return cls(**values)

    def database(self):
        return {
            "host": self.db_host,
            "port": 5432,
            "dbname": "opsjobs",
            "user": self.db_user,
            "password": secret(self.db_password_file),
            "connect_timeout": 3,
            "options": "-c statement_timeout=3000 -c lock_timeout=2000",
            "application_name": "opsjobs",
        }
