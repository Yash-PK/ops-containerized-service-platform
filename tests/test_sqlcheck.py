"""Guard and cleanup tests; these mocks do not prove PostgreSQL behavior."""

import contextlib
import io
import json
import unittest
from unittest.mock import MagicMock, patch

from opsjobs import sqlcheck
from opsjobs.config import Config


class SQLCheckSafetyTests(unittest.TestCase):
    def test_dry_run_never_reads_credentials_or_connects(self):
        output = io.StringIO()
        with (
            contextlib.redirect_stdout(output),
            patch.object(sqlcheck.Config, "from_env") as config,
            patch.object(sqlcheck.psycopg, "connect") as connect,
        ):
            self.assertEqual(sqlcheck.main(["--lab-id", sqlcheck.LAB_ID]), 0)
        self.assertTrue(json.loads(output.getvalue())["dry_run"])
        config.assert_not_called()
        connect.assert_not_called()

    def test_execution_requires_exact_confirmation_before_credentials(self):
        cases = (
            ["--lab-id", "foreign"],
            ["--lab-id", sqlcheck.LAB_ID, "--execute"],
            ["--lab-id", sqlcheck.LAB_ID, "--confirm", "foreign", "--execute"],
        )
        for args in cases:
            with (
                self.subTest(args=args),
                contextlib.redirect_stderr(io.StringIO()),
                patch.object(sqlcheck.Config, "from_env") as config,
                self.assertRaises(SystemExit) as error,
            ):
                sqlcheck.main(args)
            self.assertEqual(error.exception.code, 2)
            config.assert_not_called()

    def test_foreign_database_or_app_configuration_rejected_before_connect(self):
        for config in (Config(db_host="unrelated", db_user="admin"), Config()):
            with (
                self.subTest(config=config),
                patch.object(sqlcheck.psycopg, "connect") as connect,
                self.assertRaises(sqlcheck.CheckError),
            ):
                sqlcheck.run(config)
            connect.assert_not_called()

    def test_isolated_search_path_rejects_injection(self):
        config = MagicMock()
        config.database.return_value = {"options": "-c statement_timeout=3000"}
        schema = "ops_sqlcheck_" + "a" * 32
        self.assertEqual(
            sqlcheck.SchemaConfig(config, schema).database(),
            {
                "options": "-c statement_timeout=3000 -c search_path=" + schema,
                "application_name": "opsjobs-sqlcheck",
            },
        )
        for invalid in ("public", schema + ",public", schema + " -c statement_timeout=0"):
            with self.subTest(invalid=invalid), self.assertRaises(sqlcheck.CheckError):
                sqlcheck.SchemaConfig(config, invalid)

    def setup_connections(self):
        setup = MagicMock()
        setup.execute.return_value.fetchone.side_effect = [("opsjobs",), ("18.6",)]
        cleanup, verification = MagicMock(), MagicMock()
        contexts = []
        for connection in (setup, cleanup, verification):
            context = MagicMock()
            context.__enter__.return_value = connection
            contexts.append(context)
        return setup, cleanup, contexts

    def test_failed_setup_still_removes_only_marked_owned_schema(self):
        setup, cleanup, contexts = self.setup_connections()
        identifier = MagicMock(hex="a" * 32)
        marker = sqlcheck.LAB_ID + ":" + identifier.hex
        with (
            patch.object(sqlcheck.Config, "database", return_value={}),
            patch.object(sqlcheck.psycopg, "connect", side_effect=contexts),
            patch.object(sqlcheck.uuid, "uuid4", return_value=identifier),
            patch.object(
                sqlcheck, "schema_identity", side_effect=[None, ("ops_app", marker), None]
            ),
            patch.object(sqlcheck, "Repository", side_effect=RuntimeError("private-data")),
        ):
            report = sqlcheck.run(Config(db_user="admin"))
        self.assertFalse(report["passed"])
        self.assertTrue(report["cleanup_passed"])
        self.assertEqual(report["error_type"], "RuntimeError")
        self.assertNotIn("private-data", json.dumps(report))
        self.assertTrue(setup.execute.called)
        cleanup.execute.assert_called_once()
        self.assertIn("DROP SCHEMA", str(cleanup.execute.call_args.args[0]))
        self.assertIn("ops_sqlcheck_" + identifier.hex, str(cleanup.execute.call_args.args[0]))

    def test_cleanup_refuses_changed_owner_or_marker(self):
        for identity in (("foreign", "marker"), ("ops_app", "foreign-marker")):
            _, cleanup, contexts = self.setup_connections()
            with (
                self.subTest(identity=identity),
                patch.object(sqlcheck.Config, "database", return_value={}),
                patch.object(sqlcheck.psycopg, "connect", side_effect=contexts),
                patch.object(sqlcheck, "schema_identity", side_effect=[None, identity]),
                patch.object(sqlcheck, "Repository", side_effect=RuntimeError),
            ):
                report = sqlcheck.run(Config(db_user="admin"))
            self.assertFalse(report["passed"])
            self.assertFalse(report["cleanup_passed"])
            self.assertEqual(report["cleanup_error_type"], "CheckError")
            cleanup.execute.assert_not_called()

    def test_collision_is_preserved_without_create_or_drop(self):
        setup, _, contexts = self.setup_connections()
        with (
            patch.object(sqlcheck.Config, "database", return_value={}),
            patch.object(sqlcheck.psycopg, "connect", side_effect=contexts) as connect,
            patch.object(sqlcheck, "schema_identity", return_value=("foreign", None)),
            patch.object(sqlcheck, "Repository") as repository,
        ):
            report = sqlcheck.run(Config(db_user="admin"))
        self.assertFalse(report["passed"])
        self.assertTrue(report["cleanup_passed"])
        self.assertEqual(report["error_type"], "CheckError")
        setup.execute.assert_called_once_with("SELECT current_database()")
        self.assertEqual(connect.call_count, 1)
        repository.assert_not_called()
