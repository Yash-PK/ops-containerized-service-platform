#!/usr/bin/env python3
"""Dry-run or execute one owned VM, real Compose assertions and scoped teardown."""

import argparse
import base64
import datetime
import hashlib
import json
import os
import platform
import re
import subprocess
import zlib
from pathlib import Path

from bootstrap_provider import load_provider
from paths import bounded

ROOT = Path(__file__).resolve().parents[1]
LAB_ID = "ops-container-platform-reference"
CODE_PATHS = (
    "opsjobs",
    "migrations",
    "containers",
    "guest",
    "scripts",
    "tests",
    ".github",
    "Dockerfile",
    ".dockerignore",
    "compose.json",
    "Makefile",
    "pyproject.toml",
    "requirements.lock",
    "requirements-dev.lock",
    "tools.lock.json",
    "provider.lock.json",
    "component.lock.json",
    "packages.lock.json",
    "engine.lock.json",
    "images.lock.json",
    ".python-version",
)
INSTALLER = """import base64,json,os,pathlib,re,stat,sys,zlib
marker=pathlib.Path('/etc/ops-fleet-lab.json')
info=marker.lstat()
assert os.geteuid()==0 and stat.S_ISREG(info.st_mode) and info.st_uid==0
assert not info.st_mode & 0o022
expected={'lab_id':'ops-fleet-reference','managed_by':'ops-linux-fleet-automation'}
assert json.loads(marker.read_text())==expected
root=pathlib.Path('/var/lib/ops-container-platform')
assert root.resolve()==root and not root.exists()
compressed=base64.b64decode(sys.argv[1],validate=True)
assert len(compressed)<=48000
decoder=zlib.decompressobj()
decoded=decoder.decompress(compressed,1000001)
assert len(decoded)<=1000000 and decoder.eof
assert not decoder.unused_data and not decoder.unconsumed_tail
payload=json.loads(decoded)
assert isinstance(payload,dict) and 1<=len(payload)<=80
validated={}
for name,content in payload.items():
    assert isinstance(name,str) and isinstance(content,str)
    relative=pathlib.PurePosixPath(name)
    assert not relative.is_absolute() and '..' not in relative.parts
    fixed={'Dockerfile','.dockerignore','compose.json','requirements.lock','images.lock.json',
           'engine.lock.json','packages.lock.json','scripts/credentials.py'}
    pattern=r'(opsjobs|guest)/[a-z_]+\\.py|migrations/[0-9]{3}_[a-z_]+\\.sql'
    pattern+=r'|containers/[a-z-]+\\.(sh|conf)'
    assert name in fixed or re.fullmatch(pattern,name)
    validated[name]=base64.b64decode(content,validate=True)
root.mkdir(mode=0o700)
(root/'owner.json').write_text(json.dumps({'lab_id':'ops-container-platform-reference'}))
(root/'owner.json').chmod(0o600)
for name,content in validated.items():
    target=root/pathlib.PurePosixPath(name)
    target.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
    assert target.resolve()==target and not target.exists()
    with target.open('xb') as output: output.write(content)
    target.chmod(0o644)
print('guest-payload-installed')
"""


class LabError(RuntimeError):
    pass


def now():
    return datetime.datetime.now(datetime.UTC).isoformat()


def git(args, root=ROOT):
    return subprocess.check_output(["git", *args], cwd=root, text=True, timeout=30).strip()


def code_digest(root=ROOT):
    names = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", *CODE_PATHS],
        cwd=root,
        timeout=30,
    ).split(b"\0")
    digest = hashlib.sha256()
    for name in sorted(set(names) - {b""}):
        path = bounded(root, root / os.fsdecode(name))
        if not path.is_file():
            raise LabError("Fingerprint requires regular source files")
        digest.update(name + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def payload(root=ROOT):
    fixed = [
        "Dockerfile",
        ".dockerignore",
        "compose.json",
        "requirements.lock",
        "images.lock.json",
        "engine.lock.json",
        "packages.lock.json",
        "scripts/credentials.py",
    ]
    paths = [root / name for name in fixed]
    for pattern in ("opsjobs/*.py", "guest/*.py", "migrations/*.sql", "containers/*"):
        paths.extend(sorted(root.glob(pattern)))
    value = {}
    for path in paths:
        bounded(root, path)
        if not path.is_file():
            raise LabError("Payload requires regular source files")
        data = path.read_bytes()
        if path.name == "packages.lock.json":
            lock = json.loads(data)
            data = json.dumps(
                {
                    "snapshot": lock["snapshot"],
                    "expected_kernel": lock["expected_kernel"],
                    "packages": {
                        name: {"version": item["version"]}
                        for name, item in lock["packages"].items()
                    },
                }
            ).encode()
        value[path.relative_to(root).as_posix()] = base64.b64encode(data).decode()
    serialized = json.dumps(value).encode()
    encoded = base64.b64encode(zlib.compress(serialized, level=9)).decode()
    if len(serialized) > 1000000 or len(encoded) > 64000:
        raise LabError("Guest payload exceeds bounded transport size")
    return encoded


def target(lab_id, confirm, execute):
    if lab_id != LAB_ID or (execute and confirm != LAB_ID):
        raise LabError("Exact --lab-id and matching --confirm required for execution")


def transport(provider, arguments):
    return [provider.tool, "shell", "--workdir=/home/ops-control", "ops-fleet-ubuntu", *arguments]


def phase(provider, module, name):
    args = [
        "sudo",
        "/usr/bin/python3",
        "/var/lib/ops-container-platform/guest/main.py",
        name,
        "--lab-id",
        LAB_ID,
        "--confirm",
        LAB_ID,
        "--execute",
    ]
    command_passed = True
    try:
        output = provider.run(
            transport(provider, args), distro="ubuntu", timeout=2400, log="guest-" + name
        )
    except module.LabError:
        command_passed = False
        output = provider.child("logs/guest-" + name + ".log").read_text()
    try:
        result = json.loads(output)
    except ValueError as error:
        raise LabError("Invalid guest report; inspect private guest-" + name + ".log") from error
    if not isinstance(result, dict) or result.get("lab_id") != LAB_ID:
        raise LabError("Guest report identity mismatch")
    private = result.pop("private_diagnostics", [])
    if private:
        directory = provider.directory("diagnostics")
        stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%S%f")
        path = directory / (stamp + "-" + name + ".json")
        with path.open("x") as handle:
            json.dump(private, handle)
        path.chmod(0o600)
    result["command_passed"] = command_passed
    result["passed"] = result.get("passed") is True and command_passed
    return result


def save_report(report, destination, root=ROOT):
    destination = bounded(root, destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")


def report_path(root, development, revision):
    if development:
        relative = (
            ".runtime/evidence/"
            + datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%S%f")
            + "-development.json"
        )
    else:
        if not re.fullmatch("[0-9a-f]{40}", revision):
            raise LabError("Formal evidence requires an exact source revision")
        relative = "evidence/" + revision[:12] + "-compose-vm.json"
    path = bounded(root, root / relative)
    if path.exists():
        raise LabError("Refusing to overwrite evidence")
    return path


def execute(root=ROOT, development=False):
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise LabError("VM integration unavailable: macOS ARM64 VZ is required")
    status = git(["status", "--porcelain"], root)
    if status and not development:
        raise LabError("Formal integration requires clean committed source")
    try:
        revision = git(["rev-parse", "--verify", "HEAD"], root)
    except subprocess.CalledProcessError:
        if not development:
            raise LabError("Formal integration requires a source commit") from None
        revision = "uncommitted"
    output = report_path(root, development, revision)
    encoded = payload(root)
    fingerprint = code_digest(root)
    module = load_provider(root, require_binary=True)
    provider = module.Lab(root)
    report = {
        "schema_version": 1,
        "lab_id": LAB_ID,
        "revision": revision,
        "code_fingerprint": fingerprint,
        "development": development,
        "started_at": now(),
        "environment": {
            "os": platform.system(),
            "arch": platform.machine(),
            "python": platform.python_version(),
            "vm_cpu": 2,
            "vm_memory_gib": 2,
            "vm_disk_gib_sparse": 24,
        },
        "phases": {},
        "passed": False,
    }
    with provider.exclusive():
        if provider.state(initialize=True)["instances"]:
            raise LabError("Owned VM inventory not empty; use explicit teardown before rerunning")
        try:
            provider.start("ubuntu")
            provider.run(
                transport(provider, ["sudo", "/usr/bin/python3", "-c", INSTALLER, encoded]),
                distro="ubuntu",
                timeout=30,
                log="install-payload",
            )
            prepared = phase(provider, module, "prepare")
            report["phases"]["prepare"] = prepared
            if prepared.get("passed") is not True:
                raise LabError("Guest package preparation failed")
            provider.stop("ubuntu")
            provider.start("ubuntu")
            result = phase(provider, module, "run")
            report["phases"]["compose"] = result
            if result.get("passed") is not True:
                raise LabError("Compose integration failed: " + result.get("error", "see report"))
            if fingerprint != code_digest(root):
                raise LabError("Source changed during integration; formal proof rejected")
            report["passed"] = True
        except Exception as error:
            report["error"] = str(error)[:400]
            report["error_type"] = type(error).__name__
        finally:
            try:
                if "ubuntu" in provider.state(initialize=True)["instances"]:
                    provider.destroy("ubuntu")
                report["vm_cleanup"] = "passed"
            except Exception as error:
                report["vm_cleanup"] = "failed"
                report["cleanup_error"] = str(error)[:300]
                report["passed"] = False
            report["finished_at"] = now()
            output.parent.mkdir(mode=0o700 if development else 0o755, parents=True, exist_ok=True)
            with output.open("x") as handle:
                json.dump(report, handle, indent=2)
                handle.write("\n")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "report": str(output.relative_to(root)),
                "vm_cleanup": report["vm_cleanup"],
                "error": report.get("error"),
            }
        )
    )
    return 0 if report["passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("integration", "teardown"))
    parser.add_argument("--lab-id", required=True)
    parser.add_argument("--confirm")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    try:
        target(args.lab_id, args.confirm, args.execute)
        if not args.execute:
            print(
                json.dumps(
                    {
                        "dry_run": True,
                        "action": args.action,
                        "lab_id": LAB_ID,
                        "target": "one project-owned ARM64 VZ VM; no host Docker context",
                        "cleanup": "only inventoried VM and its lab data",
                    }
                )
            )
            return 0
        if args.action == "integration":
            return execute(development=args.development)
        if args.development:
            raise LabError("--development applies only to integration")
        module = load_provider(ROOT, require_binary=True)
        provider = module.Lab(ROOT)
        with provider.exclusive():
            state = provider.state()
            if set(state["instances"]) - {"ubuntu"}:
                raise LabError("Unexpected owned instance; refusing teardown")
            if "ubuntu" in state["instances"]:
                provider.destroy("ubuntu")
            print("Owned VM inventory is empty; no unrelated resources changed")
        return 0
    except (LabError, ValueError, OSError) as error:
        parser.exit(2, str(error) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
