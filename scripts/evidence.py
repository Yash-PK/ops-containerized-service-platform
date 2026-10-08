"""Fail closed unless current implementation has real, clean-source local evidence."""

import hashlib
import json
import re

from lab import CODE_PATHS, LAB_ID, ROOT, code_digest, git

CONTROLLER_TARGETS = ("doctor", "validate", "demo", "security")
CONTROLLER_NOT_RUN = ["real VM profiles; see separately recorded integration report"]
COMPOSE_CHECKS = {
    "patched_kernel_booted",
    "engine_platform",
    "no_foreign_docker_socket",
    "engine_version_pinned",
    "engine_label",
    "engine_private_data",
    "engine_apparmor",
    "compose_pinned",
    "buildx_pinned",
    "submit_accepted",
    "separate_worker_required",
    "idempotency_replay",
    "idempotency_conflict",
    "invalid_payload_rejected",
    "worker_actual_digest",
    "completed_result_cache_hit",
    "data_survives_restart",
    "cache_outage_sql_fallback",
    "cache_recovered",
    "cache_recovery_hit",
    "durable_before_outage",
    "database_outage_write_503",
    "database_outage_bounded",
    "live_during_database_outage",
    "unready_during_database_outage",
    "api_sigterm_clean_exit",
    "accepted_job_survives_outage_and_shutdown",
    "migration_idempotent",
    "seed_idempotent",
    "sql_integration",
    "migration_success",
    "backend_internal",
    "frontend_internal",
    "edge_only_proxy",
    "application_versions_pinned",
    "containers_removed",
    "database_volume_removed",
} | {
    service + "_" + check
    for service in ("api", "worker", "database", "cache", "proxy")
    for check in (
        "memory_limit",
        "cpu_limit",
        "no_privileged",
        "apparmor",
        "private_ports",
        "realized_private_ports",
        "runtime_nonroot",
    )
}
SQL_CHECKS = {
    "owned-application-database",
    "schema-collision-absent",
    "normal-app-role-in-isolated-schema",
    "concurrent-idempotency-one-durable-row",
    "idempotency-content-conflict-rejected",
    "concurrent-submissions-created-exactly-one-row",
    "first-claim-owns-fixture",
    "expired-lease-reclaimed-with-new-token",
    "stale-completion-fenced",
    "stale-retry-fenced",
    "current-lease-completes",
    "reclaimed-result-persisted",
    "bounded-retry-claim-1",
    "bounded-retry-claim-2",
    "bounded-retry-claim-3",
    "retry-limit-prevents-fourth-claim",
    "retry-exhaustion-durable-failure",
    "transaction-failure-injected-after-insert",
    "failed-enqueue-transaction-rolled-back",
    "enqueue-recovers-after-rollback",
    "owned-schema-removed",
}


def unskipped(value, *, allowed_not_run=None):
    return (
        isinstance(value, dict)
        and value.get("not_run", []) == (allowed_not_run or [])
        and value.get("skipped", False) is False
        and value.get("skip", False) is False
        and value.get("development", False) is False
        and value.get("dry_run", False) is False
        and value.get("status") not in ("skipped", "not_run", "failed", "blocked", "pending")
        and not any(
            value.get(name)
            for name in ("error", "error_type", "cleanup_error", "cleanup_error_type")
        )
    )


def assertions_passed(values, required):
    if not isinstance(values, list) or not values:
        return False
    names = set()
    for item in values:
        if not unskipped(item) or item.get("passed") is not True:
            return False
        name = item.get("name")
        if not isinstance(name, str) or not name or name in names:
            return False
        names.add(name)
    return required <= names


def commands_passed(values):
    return (
        isinstance(values, list)
        and bool(values)
        and all(
            unskipped(item)
            and type(item.get("exit_code")) is int
            and item["exit_code"] == 0
            and item.get("timed_out", False) is False
            and item.get("timeout", False) is False
            for item in values
        )
    )


def passed(report, kind, fingerprint):
    if (
        kind not in {"compose", "controller", "clone"}
        or not isinstance(report, dict)
        or not isinstance(report.get("revision"), str)
        or not re.fullmatch("[0-9a-f]{40}", report["revision"])
        or report.get("passed") is not True
        or not unskipped(
            report, allowed_not_run=CONTROLLER_NOT_RUN if kind == "controller" else None
        )
    ):
        return False
    if kind == "compose":
        phases = report.get("phases")
        if not isinstance(phases, dict):
            return False
        phase, prepare = phases.get("compose"), phases.get("prepare")
        if any(
            not unskipped(value)
            or value.get("lab_id") != LAB_ID
            or value.get("passed") is not True
            or value.get("command_passed") is not True
            or not commands_passed(value.get("commands"))
            for value in (phase, prepare)
        ):
            return False
        package_lock = json.loads((ROOT / "packages.lock.json").read_text())
        preparation_checks = {"ubuntu_24_04", "native_arm64", "signed_snapshot_selected"} | {
            "pinned_" + name for name in package_lock["packages"]
        }
        sql = phase.get("sql_integration")
        return (
            report.get("lab_id") == LAB_ID
            and report.get("code_fingerprint") == fingerprint
            and report.get("development") is False
            and report.get("vm_cleanup") == "passed"
            and phase.get("cleanup") == "passed"
            and prepare.get("expected_kernel") == package_lock["expected_kernel"]
            and phase.get("kernel") == package_lock["expected_kernel"]
            and assertions_passed(prepare.get("assertions"), preparation_checks)
            and assertions_passed(phase.get("assertions"), COMPOSE_CHECKS)
            and unskipped(sql)
            and sql.get("lab_id") == LAB_ID
            and sql.get("profile") == "real-postgresql"
            and sql.get("migration_sha256")
            == hashlib.sha256((ROOT / "migrations/001_jobs.sql").read_bytes()).hexdigest()
            and sql.get("passed") is True
            and sql.get("cleanup_passed") is True
            and assertions_passed(sql.get("assertions"), SQL_CHECKS)
        )
    if kind == "controller":
        return (
            report.get("profile") == "controller"
            and report.get("code_sha256") == fingerprint
            and report.get("clean_at_start") is True
            and report.get("source_unchanged") is True
            and commands_passed(report.get("commands"))
            and [item.get("argv") for item in report["commands"]]
            == [["make", target] for target in CONTROLLER_TARGETS]
        )
    if not (
        report.get("profile") == "clean-clone"
        and report.get("clean_at_start") is True
        and report.get("temporary_clone_removed") is True
        and report.get("not_run") == []
        and commands_passed(report.get("commands"))
        and len(report["commands"]) == 8
        and assertions_passed(
            report.get("assertions"),
            {"clone_revision_matches_source", "clone_remains_clean_after_checks"},
        )
    ):
        return False
    argv = [item.get("argv") for item in report["commands"]]
    return (
        argv[0] == ["git", "clone", "--no-local", "--", "$SOURCE_REPO", "$CLEAN_CLONE"]
        and argv[1] == ["git", "rev-parse", "HEAD"]
        and isinstance(argv[2], list)
        and len(argv[2]) == 3
        and argv[2][0] == "make"
        and isinstance(argv[2][1], str)
        and argv[2][1].startswith("PYTHON=")
        and argv[2][2] == "bootstrap"
        and argv[3:7] == [["make", target] for target in CONTROLLER_TARGETS]
        and argv[7] == ["git", "status", "--porcelain"]
        and isinstance(report["commands"][1].get("output"), str)
        and report["commands"][1]["output"].strip() == report["revision"]
        and isinstance(report["commands"][7].get("output"), str)
        and not report["commands"][7]["output"].strip()
    )


def main():
    if git(["status", "--porcelain"]):
        raise SystemExit("Commit reviewed changes/evidence before the publishing gate")
    fingerprint = code_digest()
    found = set()
    for path in (ROOT / "evidence").glob("*.json"):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            report = json.loads(path.read_text())
        except ValueError, OSError:
            continue
        for kind in ("compose", "controller", "clone"):
            if not passed(report, kind, fingerprint):
                continue
            # The report must name an actual ancestor, never an invented revision.
            try:
                git(["merge-base", "--is-ancestor", report["revision"], "HEAD"])
            except Exception:
                continue
            if kind == "clone":
                current = git(
                    [
                        "diff",
                        "--name-only",
                        report["revision"],
                        "HEAD",
                        "--",
                        *CODE_PATHS,
                    ]
                )
                if current:
                    continue
            found.add(kind)
    if found != {"compose", "controller", "clone"}:
        raise SystemExit(
            "Required current evidence missing: "
            + ", ".join(sorted({"compose", "controller", "clone"} - found))
        )
    print("Current implementation: controller, clean clone and real Compose evidence PASS")


if __name__ == "__main__":
    main()
