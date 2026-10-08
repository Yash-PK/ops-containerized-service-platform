"""Failure-path ownership tests with no VM, engine or host mutation."""

import contextlib
import io
import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import lab  # noqa: E402

from guest import scenario  # noqa: E402
from guest.common import LabError as GuestError  # noqa: E402


class ProviderError(RuntimeError):
    pass


class FakeProvider:
    tool = "never-executed-provider"

    def __init__(self, root):
        self.root = root
        self.instances = {}
        self.events = []
        self.fail_start = False
        self.fail_destroy = False

    def exclusive(self):
        return contextlib.nullcontext()

    def state(self, **_kwargs):
        return {"instances": self.instances.copy()}

    def start(self, distro):
        self.events.append("start")
        self.instances[distro] = {"owned": True}
        if self.fail_start:
            raise ProviderError("synthetic start failure after inventory")

    def stop(self, _distro):
        self.events.append("stop")

    def destroy(self, distro):
        self.events.append("destroy")
        if self.fail_destroy:
            raise ProviderError("synthetic cleanup failure")
        del self.instances[distro]

    def run(self, _args, **_kwargs):
        self.events.append("install")
        return "guest-payload-installed"

    def child(self, name):
        return self.root / name

    def directory(self, name):
        path = self.root / name
        path.mkdir()
        return path


class ControllerLifecycleTests(unittest.TestCase):
    def simulate(self, root, provider, *, phases=None, fingerprints=None):
        module = SimpleNamespace(Lab=lambda _root: provider, LabError=ProviderError)
        with (
            patch.object(lab.platform, "system", return_value="Darwin"),
            patch.object(lab.platform, "machine", return_value="arm64"),
            patch.object(lab, "git", side_effect=["", "a" * 40]),
            patch.object(lab, "payload", return_value="synthetic-transport"),
            patch.object(lab, "code_digest", side_effect=fingerprints or ["same", "same"]),
            patch.object(lab, "load_provider", return_value=module),
            patch.object(lab, "phase", side_effect=phases or [{"passed": True}] * 2),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = lab.execute(root)
        report = json.loads((root / "evidence" / ("a" * 12 + "-compose-vm.json")).read_text())
        return result, report

    def test_success_reboots_owned_vm_before_compose_and_destroys_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            provider = FakeProvider(root)
            code, report = self.simulate(root, provider)
        self.assertEqual(code, 0)
        self.assertTrue(report["passed"])
        self.assertEqual(provider.events, ["start", "install", "stop", "start", "destroy"])
        self.assertFalse(provider.instances)

    def test_start_prepare_and_compose_failures_preserve_report_and_cleanup(self):
        for failure in ("start", "prepare", "compose"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                provider = FakeProvider(root)
                provider.fail_start = failure == "start"
                phases = [{"passed": failure != "prepare"}, {"passed": failure != "compose"}]
                code, report = self.simulate(root, provider, phases=phases)
                self.assertEqual(code, 1)
                self.assertFalse(report["passed"])
                self.assertEqual(report["vm_cleanup"], "passed")
                self.assertEqual(provider.events[-1], "destroy")
                self.assertFalse(provider.instances)
                if failure in {"start", "prepare"}:
                    self.assertNotIn("stop", provider.events)

    def test_changed_source_or_fingerprint_error_never_loses_failure_evidence(self):
        for after in ("changed", OSError("synthetic unreadable source")):
            with self.subTest(after=after), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                provider = FakeProvider(root)
                code, report = self.simulate(root, provider, fingerprints=["before", after])
                self.assertEqual(code, 1)
                self.assertFalse(report["passed"])
                self.assertEqual(report["vm_cleanup"], "passed")
                self.assertFalse(provider.instances)

    def test_cleanup_failure_invalidates_otherwise_successful_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            provider = FakeProvider(root)
            provider.fail_destroy = True
            code, report = self.simulate(root, provider)
        self.assertEqual(code, 1)
        self.assertFalse(report["passed"])
        self.assertEqual(report["vm_cleanup"], "failed")
        self.assertIn("ubuntu", provider.instances)

    def test_existing_inventory_is_never_adopted_or_destroyed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            provider = FakeProvider(root)
            provider.instances = {"ubuntu": {"owned": "previous-run"}}
            with self.assertRaises(lab.LabError):
                self.simulate(root, provider)
            self.assertFalse(provider.events)
            self.assertFalse((root / "evidence").exists())

    def test_phase_nonzero_command_cannot_pass_through_valid_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            provider = FakeProvider(Path(temporary))
            path = provider.child("logs/guest-run.log")
            path.parent.mkdir()
            path.write_text(json.dumps({"lab_id": lab.LAB_ID, "passed": True}))
            with patch.object(provider, "run", side_effect=ProviderError):
                result = lab.phase(provider, SimpleNamespace(LabError=ProviderError), "run")
        self.assertFalse(result["passed"])
        self.assertFalse(result["command_passed"])

    def test_phase_requires_boolean_success_and_matching_object_identity(self):
        provider = MagicMock(tool="never-executed")
        module = SimpleNamespace(LabError=ProviderError)
        for value in (1, "true", [True], None, False):
            with self.subTest(value=value):
                provider.run.return_value = json.dumps({"lab_id": lab.LAB_ID, "passed": value})
                self.assertFalse(lab.phase(provider, module, "run")["passed"])
        for result in ([], {"lab_id": "foreign", "passed": True}, "garbled"):
            with self.subTest(result=result), self.assertRaises(lab.LabError):
                provider.run.return_value = json.dumps(result)
                lab.phase(provider, module, "run")

    def test_private_diagnostics_are_removed_from_public_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            provider = FakeProvider(Path(temporary))
            value = {"lab_id": lab.LAB_ID, "passed": False, "private_diagnostics": ["private"]}
            with patch.object(provider, "run", return_value=json.dumps(value)):
                result = lab.phase(provider, SimpleNamespace(LabError=ProviderError), "run")
            self.assertNotIn("private_diagnostics", result)
            files = list((provider.root / "diagnostics").glob("*.json"))
            self.assertEqual(len(files), 1)
            self.assertEqual(json.loads(files[0].read_text()), ["private"])
            self.assertEqual(stat.S_IMODE(files[0].stat().st_mode), 0o600)


class GuestCleanupTests(unittest.TestCase):
    def test_absent_volume_does_not_bypass_foreign_container_guard(self):
        for labels in (
            {"com.docker.compose.project": "foreign", "com.docker.compose.service": "api"},
            {"com.docker.compose.project": scenario.LAB_ID, "com.docker.compose.service": "other"},
        ):
            with self.subTest(labels=labels), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "engine-owner.json").write_text("{}")
                ctx = MagicMock()
                ctx.docker.side_effect = [
                    "synthetic-id",
                    json.dumps([{"Config": {"Labels": labels}}]),
                ]
                with (
                    patch.object(scenario, "ROOT", root),
                    patch.object(scenario.engine, "owned"),
                    self.assertRaises(GuestError),
                ):
                    scenario.cleanup(ctx)
                ctx.compose.assert_not_called()

    def test_wrong_volume_or_network_labels_prevent_cleanup(self):
        for resource in ("volume", "network"):
            with self.subTest(resource=resource), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "engine-owner.json").write_text("{}")
                ctx = MagicMock()
                if resource == "volume":
                    ctx.docker.side_effect = ["", scenario.LAB_ID + "_database", '[{"Labels":{}}]']
                else:
                    ctx.docker.side_effect = [
                        "",
                        "",
                        scenario.LAB_ID + "_backend",
                        '[{"Labels":{}}]',
                    ]
                with (
                    patch.object(scenario, "ROOT", root),
                    patch.object(scenario.engine, "owned"),
                    self.assertRaises(GuestError),
                ):
                    scenario.cleanup(ctx)
                ctx.compose.assert_not_called()
