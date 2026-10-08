"""Exercise the guest upload programs against disposable local fixture paths.

The harness redirects their three fixed guest paths and substitutes the current
test UID for root. It never invokes SSH, sudo, a provider, or a VM. File contents,
sequence, symlink and mode validation run as written in the guest programs.
"""

import base64
import contextlib
import hashlib
import io
import json
import os
import shlex
import stat
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import lab  # noqa: E402


def encode(value):
    return base64.b64encode(zlib.compress(json.dumps(value).encode())).decode()


class GuestFixture:
    def __init__(self, root):
        self.root = root.resolve()
        self.marker = self.root / "provider.json"
        self.staging = self.root / "upload"
        self.destination = self.root / "project"
        self.marker.write_text(
            json.dumps(
                {"lab_id": "ops-fleet-reference", "managed_by": "ops-linux-fleet-automation"}
            )
        )
        self.marker.chmod(0o600)

    def run(self, item):
        code = item["argv"][3]
        for source, target in (
            ("/etc/ops-fleet-lab.json", self.marker),
            ("/var/lib/ops-container-platform-upload", self.staging),
            ("/var/lib/ops-container-platform", self.destination),
        ):
            code = code.replace(repr(source), repr(str(target)))
        code = code.replace("EXPECTED_UID=0", "EXPECTED_UID=" + str(os.geteuid()))
        output = io.StringIO()
        with (
            patch.object(sys, "argv", ["fixture", *item["argv"][4:]]),
            contextlib.redirect_stdout(output),
        ):
            exec(compile(code, "<guest-upload-fixture>", "exec"), {})
        return output.getvalue().strip()


class TransferTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = GuestFixture(Path(temporary.name))
        self.content = b"synthetic fixture application\n"
        self.encoded = encode({"opsjobs/api.py": base64.b64encode(self.content).decode()})
        self.plan = lab.transfer_plan(self.encoded)

    def test_complete_transfer_preserves_bytes_modes_and_removes_only_owned_staging(self):
        unrelated = self.fixture.root / "unrelated"
        unrelated.write_text("preserve")
        for item in self.plan:
            self.assertEqual(self.fixture.run(item), item["response"])
            if item["label"] != "install-payload":
                self.assertEqual(stat.S_IMODE(self.fixture.staging.stat().st_mode), 0o700)
                for path in self.fixture.staging.iterdir():
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual((self.fixture.destination / "opsjobs/api.py").read_bytes(), self.content)
        self.assertEqual(stat.S_IMODE(self.fixture.destination.stat().st_mode), 0o700)
        self.assertEqual(
            stat.S_IMODE((self.fixture.destination / "owner.json").stat().st_mode), 0o600
        )
        self.assertFalse(self.fixture.staging.exists())
        self.assertEqual(unrelated.read_text(), "preserve")

    def test_real_payload_commands_are_small_including_shell_quoting_and_installer(self):
        encoded = lab.payload()
        plan = lab.transfer_plan(encoded)
        self.assertGreater(len(encoded), 16000)
        self.assertGreater(len(plan), 3)
        pieces = []
        for item in plan:
            actual = len(shlex.join(item["argv"]).encode())
            self.assertEqual(actual, item["bytes"])
            self.assertLessEqual(actual, 16000)
            self.assertTrue(all(len(x.encode()) <= 16000 for x in item["argv"]))
            if item["label"].startswith("upload-part-"):
                pieces.append(item["argv"][-1])
            self.assertEqual(self.fixture.run(item), item["response"])
        self.assertEqual("".join(pieces), encoded)
        self.assertFalse(self.fixture.staging.exists())

    def test_preflight_rejects_invalid_content_without_loading_provider(self):
        invalid = (
            "!",
            "A" * 64001,
            encode({"../escape": "eA=="}),
            encode({"opsjobs/api.py": "bad!"}),
            encode({"opsjobs/api.py": 7}),
            encode({"unknown.py": "eA=="}),
            encode([]),
            base64.b64encode(zlib.compress(b'{"Dockerfile":"","Dockerfile":""}')).decode(),
            base64.b64encode(zlib.compress(b"x" * 1000001)).decode(),
            base64.b64encode(zlib.compress(b'{"Dockerfile":""}') + b"extra").decode(),
        )
        for encoded in invalid:
            with self.subTest(encoded=encoded[:60]), self.assertRaises(lab.LabError):
                lab.transfer_plan(encoded)
        with (
            patch.object(lab.platform, "system", return_value="Darwin"),
            patch.object(lab.platform, "machine", return_value="arm64"),
            patch.object(lab, "git", side_effect=["", "a" * 40]),
            patch.object(lab, "payload", return_value="!"),
            patch.object(lab, "load_provider") as provider,
            self.assertRaises(lab.LabError),
        ):
            lab.execute(self.fixture.root)
        provider.assert_not_called()

    def test_overlarge_program_fails_preflight_before_upload(self):
        with patch.object(lab, "UPLOAD_PART", "x" * 16000), self.assertRaises(lab.LabError):
            lab.transfer_plan(self.encoded)

    def test_staging_start_refuses_existing_directory_and_symlink(self):
        self.fixture.staging.mkdir()
        preserved = self.fixture.staging / "foreign"
        preserved.write_text("preserve")
        with self.assertRaises(ValueError):
            self.fixture.run(self.plan[0])
        self.assertEqual(preserved.read_text(), "preserve")
        preserved.unlink()
        self.fixture.staging.rmdir()
        self.fixture.staging.symlink_to(self.fixture.root)
        with self.assertRaises(ValueError):
            self.fixture.run(self.plan[0])
        self.assertTrue(self.fixture.staging.is_symlink())

    def test_wrong_provider_or_preexisting_project_prevents_staging(self):
        original = self.fixture.marker.read_text()
        self.fixture.marker.write_text('{"lab_id":"foreign"}')
        with self.assertRaises(ValueError):
            self.fixture.run(self.plan[0])
        self.assertFalse(self.fixture.staging.exists())
        self.fixture.marker.write_text(original)
        self.fixture.destination.mkdir()
        with self.assertRaises(ValueError):
            self.fixture.run(self.plan[0])
        self.assertFalse(self.fixture.staging.exists())

    def test_identity_sequence_and_content_are_checked_before_part_creation(self):
        self.fixture.run(self.plan[0])
        for index, replacement in (
            (4, "c" * 64),
            (5, "2"),
            (6, "1"),
            (7, "1"),
            (8, "d" * 64),
            (9, "!"),
        ):
            item = {**self.plan[1], "argv": self.plan[1]["argv"].copy()}
            item["argv"][index] = replacement
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.fixture.run(item)
            self.assertEqual({p.name for p in self.fixture.staging.iterdir()}, {"owner.json"})
        self.fixture.run(self.plan[1])
        with self.assertRaises(ValueError):
            self.fixture.run(self.plan[1])

    def test_missing_or_corrupt_stored_part_cannot_create_project(self):
        self.fixture.run(self.plan[0])
        with self.assertRaises(ValueError):
            self.fixture.run(self.plan[-1])
        self.fixture.run(self.plan[1])
        part = self.fixture.staging / "part-0000.b64"
        value = part.read_bytes()
        part.write_bytes(b"A" + value[1:])
        with self.assertRaises(ValueError):
            self.fixture.run(self.plan[-1])
        self.assertFalse(self.fixture.destination.exists())
        self.assertTrue(part.exists())

    def test_foreign_ownership_or_manifest_identity_refuses_installer(self):
        self.fixture.run(self.plan[0])
        self.fixture.run(self.plan[1])
        original_lstat = Path.lstat
        for target in (
            self.fixture.staging,
            self.fixture.staging / "owner.json",
            self.fixture.staging / "part-0000.b64",
        ):

            def lstat(path, *, target=target):
                value = original_lstat(path)
                if path == target:
                    return SimpleNamespace(
                        st_mode=value.st_mode,
                        st_uid=value.st_uid + 1,
                        st_nlink=value.st_nlink,
                        st_size=value.st_size,
                    )
                return value

            with self.subTest(target=target.name), patch.object(Path, "lstat", lstat):
                with self.assertRaises(ValueError):
                    self.fixture.run(self.plan[-1])
            self.assertFalse(self.fixture.destination.exists())
        owner = self.fixture.staging / "owner.json"
        record = json.loads(owner.read_text())
        record["lab_id"] = "foreign"
        owner.write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            self.fixture.run(self.plan[-1])
        self.assertTrue(owner.exists())

    def test_out_of_order_parts_are_rejected_and_broken_acknowledgement_stops_upload(self):
        plan = lab.transfer_plan(lab.payload())
        self.fixture.run(plan[0])
        with self.assertRaises(ValueError):
            self.fixture.run(plan[2])
        self.assertEqual({p.name for p in self.fixture.staging.iterdir()}, {"owner.json"})
        provider = SimpleNamespace(tool="not-executed")
        provider.run = lambda *_args, **_kwargs: "unexpected acknowledgement"
        report = {"completed_commands": [], "passed": False}
        with self.assertRaisesRegex(lab.LabError, "acknowledgement mismatch"):
            lab.install_payload(provider, plan, report)
        self.assertFalse(report["passed"])
        self.assertEqual(report["completed_commands"], [])

    def test_symlink_unsafe_mode_and_foreign_file_are_never_followed_or_deleted(self):
        self.fixture.run(self.plan[0])
        self.fixture.run(self.plan[1])
        part = self.fixture.staging / "part-0000.b64"
        original = part.read_bytes()
        outside = self.fixture.root / "outside"
        outside.write_bytes(original)
        outside.chmod(0o600)
        part.unlink()
        part.symlink_to(outside)
        with self.assertRaises(ValueError):
            self.fixture.run(self.plan[-1])
        self.assertTrue(part.is_symlink())
        self.assertEqual(outside.read_bytes(), original)
        part.unlink()
        part.write_bytes(original)
        part.chmod(0o644)
        with self.assertRaises(ValueError):
            self.fixture.run(self.plan[-1])
        part.chmod(0o600)
        foreign = self.fixture.staging / "foreign"
        foreign.write_text("preserve")
        with self.assertRaises(ValueError):
            self.fixture.run(self.plan[-1])
        self.assertEqual(foreign.read_text(), "preserve")
        self.assertFalse(self.fixture.destination.exists())

    def test_guest_independently_rejects_hash_valid_disallowed_payload(self):
        encoded = encode({"../escape": "eA=="})
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        identity = [digest, "1", str(len(encoded))]

        def item(code, extra):
            return {"argv": ["sudo", "/usr/bin/python3", "-c", code, *identity, *extra]}

        self.fixture.run(item(lab.UPLOAD_START, []))
        self.fixture.run(item(lab.UPLOAD_PART, ["0", digest, encoded]))
        with self.assertRaises(ValueError):
            self.fixture.run(item(lab.INSTALLER, []))
        self.assertFalse(self.fixture.destination.exists())
        self.assertFalse((self.fixture.root / "escape").exists())
