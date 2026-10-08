"""Real PostgreSQL assertions in a uniquely owned, temporary lab schema.

Invoke inside the owned Compose migration container with its admin Config and
the generated app-password secret. No external database target is accepted.
These tests use the application role and real Repository transactions; a passing
unit mock is not a substitute for executing this profile against PostgreSQL.
"""

import argparse
import datetime
import hashlib
import json
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import psycopg
from psycopg import sql

from opsjobs.config import Config
from opsjobs.database import Repository
from opsjobs.domain import Conflict, analyze

LAB_ID = "ops-container-platform-reference"
MIGRATION = Path(__file__).resolve().parents[1] / "migrations/001_jobs.sql"


class CheckError(RuntimeError):
    """A bounded integration assertion failed."""


class InjectedRollback(RuntimeError):
    """A synthetic failure after INSERT and before commit."""


def now():
    return datetime.datetime.now(datetime.UTC).isoformat()


class SchemaConfig:
    def __init__(self, config, schema):
        if not re.fullmatch(r"ops_sqlcheck_[0-9a-f]{32}", schema):
            raise CheckError("Invalid isolated schema identity")
        self.config = config
        self.schema = schema

    def database(self):
        values = self.config.database()
        values["options"] += " -c search_path=" + self.schema
        values["application_name"] = "opsjobs-sqlcheck"
        return values


def check(report, name, passed):
    report["assertions"].append({"name": name, "passed": bool(passed)})
    if not passed:
        raise CheckError(name)


def schema_identity(connection, schema):
    return connection.execute(
        """SELECT r.rolname, obj_description(n.oid, 'pg_namespace')
           FROM pg_namespace n JOIN pg_roles r ON r.oid = n.nspowner WHERE n.nspname = %s""",
        (schema,),
    ).fetchone()


def expire(repository, identifier):
    with repository.connect() as connection:
        count = connection.execute(
            "UPDATE jobs SET lease_until = clock_timestamp() - interval '1 second' WHERE id = %s",
            (identifier,),
        ).rowcount
    if count != 1:
        raise CheckError("Fixture lease not found")


def exercise(repository, report):
    # Four independent connections race on the same unique key. PostgreSQL must
    # commit exactly one row and return the same durable ID to each submitter.
    barrier = threading.Barrier(4)

    def submit():
        barrier.wait(timeout=5)
        return repository.enqueue("Concurrent synthetic input.", "sqlcheck-concurrent")

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(submit) for _ in range(4)]
        results = [future.result(timeout=15) for future in futures]
    identifier = results[0][0]["id"]
    check(
        report,
        "concurrent-idempotency-one-durable-row",
        sum(created for _, created in results) == 1
        and {job["id"] for job, _ in results} == {identifier},
    )
    try:
        repository.enqueue("Conflicting content.", "sqlcheck-concurrent")
    except Conflict:
        conflict = True
    else:
        conflict = False
    check(report, "idempotency-content-conflict-rejected", conflict)
    with repository.connect() as connection:
        count = connection.execute("SELECT count(*) AS total FROM jobs").fetchone()["total"]
        connection.execute(
            "UPDATE jobs SET status = 'failed', error_code = 'fixture_finished' WHERE id = %s",
            (identifier,),
        )
    check(report, "concurrent-submissions-created-exactly-one-row", count == 1)

    job, _ = repository.enqueue("Lease fencing synthetic input.", "sqlcheck-fencing")
    first = repository.claim()
    check(report, "first-claim-owns-fixture", first is not None and str(first["id"]) == job["id"])
    expire(repository, first["id"])
    second = repository.claim()
    check(
        report,
        "expired-lease-reclaimed-with-new-token",
        second is not None
        and second["id"] == first["id"]
        and second["lease_token"] != first["lease_token"],
    )
    expected = analyze(second["text_content"])
    check(
        report,
        "stale-completion-fenced",
        repository.complete(first["id"], first["lease_token"], expected) is False,
    )
    check(
        report,
        "stale-retry-fenced",
        repository.retry(first["id"], first["lease_token"]) is False,
    )
    check(
        report,
        "current-lease-completes",
        repository.complete(second["id"], second["lease_token"], expected) is True,
    )
    persisted = repository.get(job["id"])
    check(
        report,
        "reclaimed-result-persisted",
        persisted["status"] == "succeeded"
        and persisted["attempts"] == 2
        and persisted["result"] == expected,
    )

    exhausted, _ = repository.enqueue("Exhaustion synthetic input.", "sqlcheck-exhaustion")
    for attempt in range(1, 4):
        claim = repository.claim()
        check(
            report,
            f"bounded-retry-claim-{attempt}",
            claim is not None
            and str(claim["id"]) == exhausted["id"]
            and repository.get(exhausted["id"])["attempts"] == attempt,
        )
        expire(repository, claim["id"])
    check(report, "retry-limit-prevents-fourth-claim", repository.claim() is None)
    failed = repository.get(exhausted["id"])
    check(
        report,
        "retry-exhaustion-durable-failure",
        failed["status"] == "failed"
        and failed["attempts"] == 3
        and failed["error_code"] == "retry_exhausted",
    )

    # Interpose only the row-to-public conversion. The INSERT and transaction
    # context are the real Repository implementation, so the fault proves that
    # an exception before returning from enqueue rolls back its inserted row.
    try:
        with patch("opsjobs.database.public", side_effect=InjectedRollback):
            repository.enqueue("Rollback synthetic input.", "sqlcheck-rollback")
    except InjectedRollback:
        injected = True
    else:
        injected = False
    check(report, "transaction-failure-injected-after-insert", injected)
    with repository.connect() as connection:
        count = connection.execute(
            "SELECT count(*) AS total FROM jobs WHERE idempotency_key = %s",
            ("sqlcheck-rollback",),
        ).fetchone()["total"]
    check(report, "failed-enqueue-transaction-rolled-back", count == 0)
    recovered, created = repository.enqueue("Rollback synthetic input.", "sqlcheck-rollback")
    check(report, "enqueue-recovers-after-rollback", created and recovered["status"] == "queued")


def run(config):
    if config.db_host != "database" or config.db_user == "ops_app":
        raise CheckError("Use the owned Compose database and its migration/admin configuration")
    if MIGRATION.is_symlink() or not MIGRATION.is_file():
        raise CheckError("A regular checked-in migration is required")
    content = MIGRATION.read_text()
    schema = "ops_sqlcheck_" + uuid.uuid4().hex
    marker = LAB_ID + ":" + uuid.uuid4().hex
    report = {
        "schema_version": 1,
        "lab_id": LAB_ID,
        "profile": "real-postgresql",
        "started_at": now(),
        "migration_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "assertions": [],
        "cleanup_passed": False,
        "passed": False,
    }
    may_have_created = False
    try:
        with psycopg.connect(**config.database()) as connection:
            database = connection.execute("SELECT current_database()").fetchone()[0]
            check(report, "owned-application-database", database == "opsjobs")
            check(report, "schema-collision-absent", schema_identity(connection, schema) is None)
            report["postgresql_version"] = connection.execute("SHOW server_version").fetchone()[0]
            may_have_created = True
            connection.execute(
                sql.SQL("CREATE SCHEMA {} AUTHORIZATION ops_app").format(sql.Identifier(schema))
            )
            connection.execute(
                sql.SQL("COMMENT ON SCHEMA {} IS {}").format(
                    sql.Identifier(schema), sql.Literal(marker)
                )
            )
            connection.execute(
                sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema))
            )
            connection.execute(content)
        app_config = replace(
            config, db_user="ops_app", db_password_file="/run/secrets/app_password"
        )
        repository = Repository(SchemaConfig(app_config, schema))
        with repository.connect() as connection:
            identity = connection.execute(
                "SELECT current_user AS name, current_schema() AS schema"
            ).fetchone()
            check(
                report,
                "normal-app-role-in-isolated-schema",
                identity == {"name": "ops_app", "schema": schema},
            )
        exercise(repository, report)
    except Exception as error:
        # Do not serialize driver exceptions, queries, connection strings or
        # credential-bearing bootstrap SQL into public container logs.
        report["error_type"] = type(error).__name__
    finally:
        try:
            if may_have_created:
                with psycopg.connect(**config.database()) as connection:
                    identity = schema_identity(connection, schema)
                    if identity is not None:
                        if identity != ("ops_app", marker):
                            raise CheckError("Schema ownership changed; cleanup refused")
                        connection.execute(
                            sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                        )
                with psycopg.connect(**config.database()) as connection:
                    check(
                        report, "owned-schema-removed", schema_identity(connection, schema) is None
                    )
            report["cleanup_passed"] = True
        except Exception as error:
            report["cleanup_error_type"] = type(error).__name__
    report["finished_at"] = now()
    report["passed"] = (
        bool(report["assertions"])
        and all(item["passed"] for item in report["assertions"])
        and report["cleanup_passed"]
        and "error_type" not in report
        and "cleanup_error_type" not in report
    )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-id", required=True)
    parser.add_argument("--confirm")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    if args.lab_id != LAB_ID or (args.execute and args.confirm != LAB_ID):
        parser.error("An explicit matching lab identity and confirmation are required")
    if not args.execute:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "lab_id": LAB_ID,
                    "resources": "one isolated owned PostgreSQL schema",
                }
            )
        )
        return 0
    try:
        report = run(Config.from_env())
    except Exception as error:
        print(json.dumps({"passed": False, "error_type": type(error).__name__}))
        return 1
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
