"""Repeatable synthetic jobs through the same durable enqueue contract."""

import json

from opsjobs.config import Config
from opsjobs.database import Repository

SEEDS = (
    ("seed-platform-001", "A small reliable service."),
    ("seed-platform-002", "Linux operations\nRecovery verified."),
)


def seed(repository):
    return [
        {"id": job["id"], "created": created}
        for key, text in SEEDS
        for job, created in [repository.enqueue(text, key)]
    ]


if __name__ == "__main__":
    print(json.dumps({"seed_jobs": seed(Repository(Config.from_env()))}))
