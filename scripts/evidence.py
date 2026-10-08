"""Fail closed unless current implementation has real, clean-source local evidence."""

import json
import re

from lab import ROOT, code_digest, git


def passed(report, kind, fingerprint):
    if not re.fullmatch("[0-9a-f]{40}", report.get("revision", "")) or not report.get("passed"):
        return False
    if kind == "compose":
        phase = report.get("phases", {}).get("compose", {})
        names = {item.get("name") for item in phase.get("assertions", []) if item.get("passed")}
        required = {
            "worker_actual_digest",
            "data_survives_restart",
            "cache_outage_sql_fallback",
            "database_outage_write_503",
            "accepted_job_survives_outage_and_shutdown",
            "migration_idempotent",
            "seed_idempotent",
            "sql_integration",
            "containers_removed",
            "database_volume_removed",
        }
        return (
            report.get("code_fingerprint") == fingerprint
            and report.get("development") is False
            and report.get("vm_cleanup") == "passed"
            and phase.get("passed") is True
            and phase.get("cleanup") == "passed"
            and phase.get("sql_integration", {}).get("passed") is True
            and required <= names
            and all(item.get("passed") is True for item in phase.get("assertions", []))
            and report.get("phases", {}).get("prepare", {}).get("passed") is True
        )
    if kind == "controller":
        return (
            report.get("code_sha256") == fingerprint
            and report.get("clean_at_start") is True
            and report.get("source_unchanged") is True
            and len(report.get("commands", [])) == 4
            and all(item.get("exit_code") == 0 for item in report["commands"])
        )
    return (
        report.get("profile") == "clean-clone"
        and report.get("clean_at_start") is True
        and report.get("temporary_clone_removed") is True
        and not report.get("not_run")
        and len(report.get("commands", [])) >= 8
        and all(item.get("exit_code") == 0 for item in report["commands"])
        and all(item.get("passed") is True for item in report.get("assertions", []))
    )


def main():
    if git(["status", "--porcelain"]):
        raise SystemExit("Commit reviewed changes/evidence before the publishing gate")
    fingerprint = code_digest()
    found = set()
    for path in (ROOT / "evidence").glob("*.json"):
        report = json.loads(path.read_text())
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
                        *(__import__("lab").CODE_PATHS),
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
