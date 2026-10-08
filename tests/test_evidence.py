"""Synthetic gate fixtures only; no fixture is project execution evidence."""

import contextlib
import copy
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import evidence  # noqa: E402

REVISION = "a" * 40
FINGERPRINT = "b" * 64


def assertions(names):
    return [{"name": name, "passed": True} for name in sorted(names)]


def command(argv, output=""):
    return {"argv": argv, "exit_code": 0, "timed_out": False, "output": output}


def fixtures():
    lock = json.loads((ROOT / "packages.lock.json").read_text())
    prepare = {
        "lab_id": evidence.LAB_ID,
        "passed": True,
        "command_passed": True,
        "expected_kernel": lock["expected_kernel"],
        "commands": [{"label": "apt-install", "exit_code": 0}],
        "assertions": assertions(
            {"ubuntu_24_04", "native_arm64", "signed_snapshot_selected"}
            | {"pinned_" + name for name in lock["packages"]}
        ),
    }
    compose = {
        "revision": REVISION,
        "lab_id": evidence.LAB_ID,
        "code_fingerprint": FINGERPRINT,
        "development": False,
        "passed": True,
        "vm_cleanup": "passed",
        "phases": {
            "prepare": prepare,
            "compose": {
                "lab_id": evidence.LAB_ID,
                "passed": True,
                "command_passed": True,
                "cleanup": "passed",
                "kernel": lock["expected_kernel"],
                "commands": [{"label": "sql-integration", "exit_code": 0}],
                "assertions": assertions(evidence.COMPOSE_CHECKS),
                "sql_integration": {
                    "lab_id": evidence.LAB_ID,
                    "profile": "real-postgresql",
                    "passed": True,
                    "cleanup_passed": True,
                    "migration_sha256": hashlib.sha256(
                        (ROOT / "migrations/001_jobs.sql").read_bytes()
                    ).hexdigest(),
                    "assertions": assertions(evidence.SQL_CHECKS),
                },
            },
        },
    }
    controller = {
        "revision": REVISION,
        "profile": "controller",
        "passed": True,
        "code_sha256": FINGERPRINT,
        "clean_at_start": True,
        "source_unchanged": True,
        "not_run": evidence.CONTROLLER_NOT_RUN.copy(),
        "commands": [command(["make", target]) for target in evidence.CONTROLLER_TARGETS],
    }
    clone = {
        "revision": REVISION,
        "profile": "clean-clone",
        "passed": True,
        "clean_at_start": True,
        "temporary_clone_removed": True,
        "not_run": [],
        "commands": [
            command(["git", "clone", "--no-local", "--", "$SOURCE_REPO", "$CLEAN_CLONE"]),
            command(["git", "rev-parse", "HEAD"], REVISION + "\n"),
            command(["make", "PYTHON=/synthetic/python3.14", "bootstrap"]),
            *[command(["make", target]) for target in evidence.CONTROLLER_TARGETS],
            command(["git", "status", "--porcelain"]),
        ],
        "assertions": assertions(
            {"clone_revision_matches_source", "clone_remains_clean_after_checks"}
        ),
    }
    return {"compose": compose, "controller": controller, "clone": clone}


class EvidenceContractTests(unittest.TestCase):
    def setUp(self):
        self.reports = fixtures()

    def test_complete_fixture_set_is_accepted_for_its_respective_profile(self):
        for kind, report in self.reports.items():
            with self.subTest(kind=kind):
                self.assertTrue(evidence.passed(report, kind, FINGERPRINT))
                self.assertFalse(evidence.passed(report, "unknown", FINGERPRINT))
                for other in self.reports.keys() - {kind}:
                    self.assertFalse(evidence.passed(report, other, FINGERPRINT))

    def test_truthy_success_is_never_a_boolean_pass(self):
        for kind, original in self.reports.items():
            for value in (1, "true", [True], None, False):
                with self.subTest(kind=kind, value=value):
                    report = copy.deepcopy(original)
                    report["passed"] = value
                    self.assertFalse(evidence.passed(report, kind, FINGERPRINT))

    def test_development_dirty_stale_or_unfinished_reports_fail(self):
        cases = (
            ("compose", "development", True),
            ("compose", "development", None),
            ("compose", "code_fingerprint", "c" * 64),
            ("compose", "vm_cleanup", "failed"),
            ("controller", "code_sha256", "c" * 64),
            ("controller", "clean_at_start", False),
            ("controller", "source_unchanged", False),
            ("clone", "clean_at_start", False),
            ("clone", "temporary_clone_removed", False),
            ("clone", "not_run", ["security"]),
        )
        for kind, field, value in cases:
            with self.subTest(kind=kind, field=field):
                report = copy.deepcopy(self.reports[kind])
                report[field] = value
                self.assertFalse(evidence.passed(report, kind, FINGERPRINT))

    def test_each_runtime_and_cache_acceptance_assertion_is_required(self):
        for missing in evidence.COMPOSE_CHECKS:
            with self.subTest(missing=missing):
                report = copy.deepcopy(self.reports["compose"])
                phase = report["phases"]["compose"]
                phase["assertions"] = [x for x in phase["assertions"] if x["name"] != missing]
                self.assertFalse(evidence.passed(report, "compose", FINGERPRINT))
        for name in (
            "cache_recovery_hit",
            "proxy_realized_private_ports",
            "database_runtime_nonroot",
        ):
            self.assertIn(name, evidence.COMPOSE_CHECKS)

    def test_failed_skipped_duplicate_or_empty_assertions_cannot_hide_behind_summary(self):
        for mutation in ("failed", "truthy", "skipped", "duplicate", "empty"):
            with self.subTest(mutation=mutation):
                report = copy.deepcopy(self.reports["compose"])
                checks = report["phases"]["compose"]["assertions"]
                if mutation == "failed":
                    checks[0]["passed"] = False
                elif mutation == "truthy":
                    checks[0]["passed"] = 1
                elif mutation == "skipped":
                    checks[0]["skipped"] = True
                elif mutation == "duplicate":
                    checks.append(checks[0].copy())
                else:
                    checks.clear()
                self.assertFalse(evidence.passed(report, "compose", FINGERPRINT))

    def test_preparation_requires_each_pin_correct_kernel_and_successful_command(self):
        for mutation in ("missing-pin", "wrong-kernel", "failed-assertion", "nonzero", "timeout"):
            with self.subTest(mutation=mutation):
                report = copy.deepcopy(self.reports["compose"])
                prepare = report["phases"]["prepare"]
                if mutation == "missing-pin":
                    prepare["assertions"] = [
                        x for x in prepare["assertions"] if x["name"] != "pinned_systemd"
                    ]
                elif mutation == "wrong-kernel":
                    prepare["expected_kernel"] = "6.8.0-old-generic"
                elif mutation == "failed-assertion":
                    prepare["assertions"][0]["passed"] = False
                elif mutation == "nonzero":
                    prepare["commands"][0]["exit_code"] = 1
                else:
                    prepare["commands"][0]["timeout"] = True
                self.assertFalse(evidence.passed(report, "compose", FINGERPRINT))

    def test_sql_requires_real_profile_all_21_assertions_and_owned_cleanup(self):
        self.assertEqual(len(evidence.SQL_CHECKS), 21)
        for missing in evidence.SQL_CHECKS:
            with self.subTest(missing=missing):
                report = copy.deepcopy(self.reports["compose"])
                sql = report["phases"]["compose"]["sql_integration"]
                sql["assertions"] = [x for x in sql["assertions"] if x["name"] != missing]
                self.assertFalse(evidence.passed(report, "compose", FINGERPRINT))
        for field, value in (
            ("profile", "mock"),
            ("cleanup_passed", False),
            ("passed", 1),
            ("lab_id", "foreign"),
            ("migration_sha256", "c" * 64),
            ("assertions", []),
        ):
            with self.subTest(field=field):
                report = copy.deepcopy(self.reports["compose"])
                report["phases"]["compose"]["sql_integration"][field] = value
                self.assertFalse(evidence.passed(report, "compose", FINGERPRINT))

    def test_command_count_cannot_replace_required_controller_or_clone_checks(self):
        for kind in ("controller", "clone"):
            with self.subTest(kind=kind):
                report = copy.deepcopy(self.reports[kind])
                security = next(x for x in report["commands"] if x["argv"] == ["make", "security"])
                security["argv"] = ["make", "doctor"]
                self.assertFalse(evidence.passed(report, kind, FINGERPRINT))
            for field, value in (("exit_code", False), ("timed_out", True), ("skipped", True)):
                with self.subTest(kind=kind, field=field):
                    report = copy.deepcopy(self.reports[kind])
                    report["commands"][0][field] = value
                    self.assertFalse(evidence.passed(report, kind, FINGERPRINT))

    def test_clone_requires_observed_matching_head_and_clean_worktree(self):
        for index, output in ((1, "c" * 40), (7, " M opsjobs/api.py\n")):
            report = copy.deepcopy(self.reports["clone"])
            report["commands"][index]["output"] = output
            self.assertFalse(evidence.passed(report, "clone", FINGERPRINT))
        report = copy.deepcopy(self.reports["clone"])
        report["assertions"] = []
        self.assertFalse(evidence.passed(report, "clone", FINGERPRINT))

    def test_malformed_or_foreign_reports_are_not_evidence(self):
        for value in (None, [], "passed", True, {"revision": 1}, {"passed": True}):
            for kind in self.reports:
                self.assertFalse(evidence.passed(value, kind, FINGERPRINT))
        for field in ("prepare", "compose"):
            report = copy.deepcopy(self.reports["compose"])
            report["phases"][field] = []
            self.assertFalse(evidence.passed(report, "compose", FINGERPRINT))

    def test_main_requires_ancestry_and_current_clone_code_but_allows_document_followup(self):
        for change in ("none", "documentation-only", "source", "unrelated-revision"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "evidence").mkdir()
                (root / "migrations").mkdir()
                for name in ("packages.lock.json", "migrations/001_jobs.sql"):
                    (root / name).write_bytes((ROOT / name).read_bytes())
                for kind, report in self.reports.items():
                    (root / "evidence" / (kind + ".json")).write_text(json.dumps(report))
                (root / "evidence" / "broken.json").write_text("{")

                def git(args, change=change):
                    if args[0] == "merge-base" and change == "unrelated-revision":
                        raise subprocess.CalledProcessError(1, args)
                    if args[0] == "diff" and change == "source":
                        return "opsjobs/api.py"
                    return ""

                with (
                    patch.object(evidence, "ROOT", root),
                    patch.object(evidence, "code_digest", return_value=FINGERPRINT),
                    patch.object(evidence, "git", side_effect=git),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    if change in {"source", "unrelated-revision"}:
                        with self.assertRaisesRegex(
                            SystemExit, "Required current evidence missing"
                        ):
                            evidence.main()
                    else:
                        evidence.main()
