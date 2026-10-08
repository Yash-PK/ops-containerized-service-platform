"""A bounded single-job worker; durable leases survive process replacement."""

import json
import signal
import threading
import time
from pathlib import Path

import psycopg

from opsjobs.config import Config
from opsjobs.database import Repository
from opsjobs.domain import analyze

HEARTBEAT = Path("/tmp/opsjobs-heartbeat")


def process_one(repository):
    job = repository.claim()
    if job is None:
        return False
    try:
        result = analyze(job["text_content"])
    except ValueError:
        repository.retry(job["id"], job["lease_token"])
        return True
    completed = repository.complete(job["id"], job["lease_token"], result)
    print(
        json.dumps(
            {"event": "job_completed" if completed else "lease_lost", "job_id": str(job["id"])}
        ),
        flush=True,
    )
    return True


def main():
    repository = Repository(Config.from_env())
    stop = threading.Event()
    for number in (signal.SIGTERM, signal.SIGINT):
        signal.signal(number, lambda _signum, _frame: stop.set())
    while not stop.is_set():
        try:
            worked = process_one(repository)
            HEARTBEAT.write_text(str(time.monotonic()))
            stop.wait(0.05 if worked else 0.25)
        except psycopg.Error:
            print(json.dumps({"event": "database_unavailable"}), flush=True)
            stop.wait(1)
    print(json.dumps({"event": "worker_stopped"}), flush=True)


if __name__ == "__main__":
    main()
