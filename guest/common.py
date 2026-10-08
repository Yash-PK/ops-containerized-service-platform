"""A private, explicitly owned VM boundary, bounded commands and public assertions."""

import datetime
import json
import os
import stat
import subprocess
from pathlib import Path

ROOT = Path("/var/lib/ops-container-platform")
LAB_ID = "ops-container-platform-reference"


class LabError(RuntimeError):
    pass


def regular(path, owner=0):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != owner or info.st_mode & 0o022:
        raise LabError("Unsafe regular file: " + path.name)
    return path


def boundary():
    if os.geteuid() != 0 or ROOT.resolve() != ROOT:
        raise LabError("Owned guest root required")
    provider = regular(Path("/etc/ops-fleet-lab.json"))
    if json.loads(provider.read_text()) != {
        "lab_id": "ops-fleet-reference",
        "managed_by": "ops-linux-fleet-automation",
    }:
        raise LabError("Guest provider identity mismatch")
    if json.loads(regular(ROOT / "owner.json").read_text()) != {"lab_id": LAB_ID}:
        raise LabError("Guest project identity mismatch")
    if Path("/sys/module/apparmor/parameters/enabled").read_text().strip() != "Y":
        raise LabError("AppArmor must remain enabled")


class Context:
    def __init__(self):
        boundary()
        self.report = {
            "schema_version": 1,
            "lab_id": LAB_ID,
            "started_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "assertions": [],
            "commands": [],
        }
        runtime = ROOT / ".runtime"
        self.logs = runtime / "logs"
        for directory in (runtime, self.logs):
            if directory.is_symlink():
                raise LabError("Private runtime directory must not be a symlink")
            directory.mkdir(mode=0o700, exist_ok=True)
            info = directory.stat()
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise LabError("Private runtime directory ownership or mode mismatch")

    def check(self, name, condition):
        self.report["assertions"].append({"name": name, "passed": bool(condition)})
        if not condition:
            raise LabError("Assertion failed: " + name)

    def run(self, args, *, label, timeout=120, expected=(0,)):
        env = {
            "PATH": str(ROOT / "tools/docker") + ":/usr/sbin:/usr/bin:/sbin:/bin",
            "HOME": str(ROOT / ".runtime"),
            "LC_ALL": "C.UTF-8",
            "DOCKER_CONFIG": str(ROOT / ".runtime/docker-config"),
        }
        index = len(self.report["commands"]) + 1
        try:
            result = subprocess.run(
                [str(x) for x in args],
                cwd=ROOT,
                env=env,
                stdin=subprocess.DEVNULL,
                text=True,
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            self.report["commands"].append({"label": label, "exit_code": None, "timeout": True})
            raise LabError("Command timed out: " + label) from exc
        path = self.logs / f"{index:04d}-{label}.log"
        with path.open("x") as handle:
            handle.write(result.stdout + result.stderr)
        path.chmod(0o600)
        self.report["commands"].append({"label": label, "exit_code": result.returncode})
        if result.returncode not in expected:
            self.report.setdefault("private_diagnostics", []).append(
                {"label": label, "output": (result.stdout + result.stderr)[-16000:]}
            )
            raise LabError("Command failed: " + label + "; private log " + path.name)
        return result.stdout

    def docker(self, args, **kwargs):
        return self.run(
            [
                ROOT / "tools/docker/docker",
                "--host",
                "unix://" + str(ROOT / "run/docker.sock"),
                "--config",
                ROOT / ".runtime/docker-config",
                *args,
            ],
            **kwargs,
        )

    def compose(self, args, **kwargs):
        return self.docker(
            ["compose", "--project-name", LAB_ID, "--file", ROOT / "compose.json", *args], **kwargs
        )
