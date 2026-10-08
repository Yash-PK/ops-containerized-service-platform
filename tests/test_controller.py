"""Safety cases must reject changes before allocating a VM or touching secrets."""

import base64
import json
import stat
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import lab  # noqa: E402
from credentials import NAMES, generate  # noqa: E402
from paths import bounded  # noqa: E402

from opsjobs.config import Config, secret  # noqa: E402


class SafetyTests(unittest.TestCase):
    def test_guest_runtime_parents_private_and_no_symlink_adoption(self):
        from guest import common

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            with patch.object(common, "ROOT", root), patch.object(common, "boundary"):
                common.Context()
                self.assertEqual(stat.S_IMODE((root / ".runtime").stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE((root / ".runtime/logs").stat().st_mode), 0o700)
                (root / ".runtime/logs").rmdir()
                (root / ".runtime/logs").symlink_to(root)
                with self.assertRaises(common.LabError):
                    common.Context()

    def test_exact_target_and_confirmation(self):
        lab.target(lab.LAB_ID, None, False)
        lab.target(lab.LAB_ID, lab.LAB_ID, True)
        for target, confirm in [
            ("foreign", lab.LAB_ID),
            (lab.LAB_ID, None),
            (lab.LAB_ID, "foreign"),
        ]:
            with self.assertRaises(lab.LabError):
                lab.target(target, confirm, True)

    def test_secret_generation_permissions_unique_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            folder = generate(root)
            values = {secret(folder / name) for name in NAMES}
            self.assertEqual(len(values), 3)
            self.assertEqual(stat.S_IMODE(folder.stat().st_mode), 0o700)
            for name in NAMES:
                self.assertEqual(stat.S_IMODE((folder / name).stat().st_mode), 0o444)
            with self.assertRaises(ValueError):
                generate(root)
            self.assertEqual(values, {secret(folder / name) for name in NAMES})

    def test_reject_runtime_symlink_and_unsafe_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / ".runtime").symlink_to(root)
            with self.assertRaises(ValueError):
                generate(root)
            (root / ".runtime").unlink()
            (root / ".runtime").mkdir(mode=0o755)
            with self.assertRaises(ValueError):
                generate(root)

    def test_reject_secret_symlink_writable_bad_format(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "password"
            path.write_text("a" * 48)
            path.chmod(0o666)
            with self.assertRaises(ValueError):
                secret(path)
            path.chmod(0o600)
            link = path.with_name("link")
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                secret(link)
            path.write_text("not-a-credential")
            with self.assertRaises(ValueError):
                secret(path)

    def test_config_ignores_unrelated_credentials_and_rejects_host_injection(self):
        config = Config.from_env({"PGHOST": "external", "PGPASSWORD": "unrelated"})
        self.assertEqual(config.db_host, "database")
        with self.assertRaises(ValueError):
            Config.from_env({"OPS_DB_HOST": "host port=99"})

    def test_evidence_no_overwrite_and_no_symlink_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            revision = "a" * 40
            path = lab.report_path(root, False, revision)
            path.parent.mkdir()
            path.write_text("preserve")
            with self.assertRaises(lab.LabError):
                lab.report_path(root, False, revision)
            self.assertEqual(path.read_text(), "preserve")
            with self.assertRaises(lab.LabError):
                lab.report_path(root, False, "uncommitted")
            (root / "link").symlink_to(root)
            with self.assertRaises(ValueError):
                bounded(root, root / "link/escape")

    def test_payload_only_allowlisted_runtime_no_private_content(self):
        value = json.loads(zlib.decompress(base64.b64decode(lab.payload())))
        self.assertIn("opsjobs/api.py", value)
        self.assertIn("compose.json", value)
        self.assertFalse(any(name.startswith((".runtime", ".git", ".venv")) for name in value))
        self.assertLess(len(lab.payload()), 64000)
        lock = json.loads(base64.b64decode(value["packages.lock.json"]))
        self.assertNotIn("indexes", lock)
        self.assertTrue(all(set(item) == {"version"} for item in lock["packages"].values()))

    def test_no_vm_on_unsupported_controller(self):
        with patch.object(lab.platform, "system", return_value="Linux"):
            with patch.object(lab, "load_provider") as provider:
                with self.assertRaises(lab.LabError):
                    lab.execute()
                provider.assert_not_called()

    def test_dirty_formal_source_fails_before_provider(self):
        with (
            patch.object(lab.platform, "system", return_value="Darwin"),
            patch.object(lab.platform, "machine", return_value="arm64"),
            patch.object(lab, "git", return_value=" M source.py"),
            patch.object(lab, "load_provider") as provider,
        ):
            with self.assertRaises(lab.LabError):
                lab.execute()
            provider.assert_not_called()

    def test_file_context_excludes_runtime_and_credentials(self):
        ignore = (ROOT / ".dockerignore").read_text().splitlines()
        self.assertEqual(ignore[0], "**")
        self.assertFalse(any(".runtime" in line for line in ignore if line.startswith("!")))
        compose = json.loads((ROOT / "compose.json").read_text())
        for name, service in compose["services"].items():
            self.assertNotIn("privileged", service)
            if name != "proxy":
                self.assertNotIn("ports", service)
        self.assertEqual(compose["services"]["proxy"]["ports"], ["127.0.0.1:8080:8080"])
        self.assertTrue(
            all(compose["networks"][name]["internal"] for name in ("frontend", "backend"))
        )
        self.assertFalse(compose["networks"]["edge"]["internal"])
        self.assertEqual(
            [
                name
                for name, service in compose["services"].items()
                if "edge" in service["networks"]
            ],
            ["proxy"],
        )
