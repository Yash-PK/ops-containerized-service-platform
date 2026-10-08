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
import shlex
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
CHUNK_BYTES = 8000
MAX_ENCODED_BYTES = 64000
MAX_COMMAND_BYTES = 16000

# These guest programs run only through authenticated SSH in the owned VM.
# Keep each complete shell-quoted command below the conservative mux limit.
GUEST_BOUNDARY = """import base64,hashlib,json,os,pathlib,re,stat,sys,zlib
EXPECTED_UID=0
marker=pathlib.Path('/etc/ops-fleet-lab.json')
staging=pathlib.Path('/var/lib/ops-container-platform-upload')
root=pathlib.Path('/var/lib/ops-container-platform')
def require(condition,message):
    if not condition: raise ValueError(message)
def regular(path,mode=None,maximum=64000):
    info=path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid==EXPECTED_UID
            and info.st_nlink==1 and info.st_size<=maximum,'unsafe upload file')
    require(not info.st_mode & 0o022,'writable upload file')
    if mode is not None: require(stat.S_IMODE(info.st_mode)==mode,'upload file mode')
    return path
require(os.geteuid()==EXPECTED_UID,'guest root required')
expected={'lab_id':'ops-fleet-reference','managed_by':'ops-linux-fleet-automation'}
require(json.loads(regular(marker,maximum=4096).read_text())==expected,'provider identity')
require(root.resolve()==root and not root.exists() and not root.is_symlink(),'existing project')
require(staging.resolve()==staging and not staging.is_symlink(),'staging path')
require(len(sys.argv)>=4,'upload identity arguments')
digest,count_text,size_text=sys.argv[1:4]
require(re.fullmatch('[0-9a-f]{64}',digest) is not None,'upload digest')
require(re.fullmatch('[1-8]',count_text) is not None,'upload part count')
require(re.fullmatch('[1-9][0-9]{0,4}',size_text) is not None,'upload size')
count,size=int(count_text),int(size_text)
require(size<=64000 and count==(size+7999)//8000,'upload count/size mismatch')
identity={'lab_id':'ops-container-platform-reference','sha256':digest,
          'parts':count,'bytes':size,'chunk_bytes':8000}
def part_name(index): return 'part-%04d.b64'%index
def stage(expected_parts):
    info=staging.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid==EXPECTED_UID
            and stat.S_IMODE(info.st_mode)==0o700,'staging ownership/mode')
    require(json.loads(regular(staging/'owner.json',0o600,4096).read_text())==identity,
            'staging identity mismatch')
    expected_names={'owner.json'}|{part_name(i) for i in range(expected_parts)}
    require({p.name for p in staging.iterdir()}==expected_names,'staging sequence/content')
    for i in range(expected_parts): regular(staging/part_name(i),0o600,8000)
def exclusive(path,data):
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(descriptor,'wb') as output:
        os.fchmod(output.fileno(),0o600)
        output.write(data)
"""
UPLOAD_START = (
    GUEST_BOUNDARY
    + """
require(len(sys.argv)==4,'upload start arguments')
require(not staging.exists(),'existing upload staging')
staging.mkdir(mode=0o700)
staging.chmod(0o700)
exclusive(staging/'owner.json',json.dumps(identity,sort_keys=True).encode())
stage(0)
print('upload-ready')
"""
)
UPLOAD_PART = (
    GUEST_BOUNDARY
    + """
require(len(sys.argv)==7,'upload part arguments')
index_text,part_digest,data=sys.argv[4:7]
require(re.fullmatch('[0-7]',index_text) is not None,'upload part index')
index=int(index_text)
require(index<count,'upload part range')
require(re.fullmatch('[0-9a-f]{64}',part_digest) is not None,'part digest format')
require(re.fullmatch('[A-Za-z0-9+/=]+',data) is not None,'part encoding')
expected_size=8000 if index<count-1 else size-8000*index
require(len(data)==expected_size,'part size')
require(hashlib.sha256(data.encode('ascii')).hexdigest()==part_digest,'part digest mismatch')
stage(index)
exclusive(staging/part_name(index),data.encode('ascii'))
stage(index+1)
print('upload-part-stored')
"""
)
INSTALLER = (
    GUEST_BOUNDARY
    + """
require(len(sys.argv)==4,'installer arguments')
stage(count)
parts=[]
for i in range(count):
    data=regular(staging/part_name(i),0o600,8000).read_bytes()
    require(len(data)==(8000 if i<count-1 else size-8000*i),'stored part size')
    parts.append(data)
encoded=b''.join(parts)
require(len(encoded)==size and len(encoded)<=64000,'joined upload size')
require(hashlib.sha256(encoded).hexdigest()==digest,'joined upload digest mismatch')
compressed=base64.b64decode(encoded,validate=True)
require(len(compressed)<=48000,'compressed payload size')
decoder=zlib.decompressobj()
decoded=decoder.decompress(compressed,1000001)
require(len(decoded)<=1000000 and decoder.eof,'decoded payload size/completeness')
require(not decoder.unused_data and not decoder.unconsumed_tail,'trailing compressed content')
def unique_object(pairs):
    value={}
    for name,item in pairs:
        require(name not in value,'duplicate payload path')
        value[name]=item
    return value
payload=json.loads(decoded,object_pairs_hook=unique_object)
require(isinstance(payload,dict) and 1<=len(payload)<=80,'payload inventory')
validated={}
for name,content in payload.items():
    require(isinstance(name,str) and isinstance(content,str),'payload entry type')
    relative=pathlib.PurePosixPath(name)
    require(not relative.is_absolute() and '..' not in relative.parts,'payload path')
    fixed={'Dockerfile','.dockerignore','compose.json','requirements.lock','images.lock.json',
           'engine.lock.json','packages.lock.json','scripts/credentials.py'}
    pattern=r'(opsjobs|guest)/[a-z_]+\\.py|migrations/[0-9]{3}_[a-z_]+\\.sql'
    pattern+=r'|containers/[a-z-]+\\.(sh|conf)'
    require(name in fixed or re.fullmatch(pattern,name) is not None,'payload path allowlist')
    validated[name]=base64.b64decode(content,validate=True)
root.mkdir(mode=0o700)
exclusive(root/'owner.json',json.dumps({'lab_id':'ops-container-platform-reference'}).encode())
for name,content in validated.items():
    target=root/pathlib.PurePosixPath(name)
    target.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
    require(target.resolve()==target and not target.exists(),'payload destination')
    exclusive(target,content)
    target.chmod(0o644)
stage(count)
for i in range(count): (staging/part_name(i)).unlink()
(staging/'owner.json').unlink()
staging.rmdir()
print('guest-payload-installed')
"""
)


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


def validate_payload(encoded):
    """Reject malformed transfer contents before provider loading or VM allocation."""
    if not isinstance(encoded, str) or not 1 <= len(encoded) <= MAX_ENCODED_BYTES:
        raise LabError("Guest payload exceeds bounded transport size")
    try:
        compressed = base64.b64decode(encoded, validate=True)
        if len(compressed) > 48000:
            raise ValueError("Compressed payload too large")
        decoder = zlib.decompressobj()
        decoded = decoder.decompress(compressed, 1000001)
        if (
            len(decoded) > 1000000
            or not decoder.eof
            or decoder.unused_data
            or decoder.unconsumed_tail
        ):
            raise ValueError("Payload compression boundary")

        def unique_object(pairs):
            result = {}
            for name, item in pairs:
                if name in result:
                    raise ValueError("Duplicate payload path")
                result[name] = item
            return result

        value = json.loads(decoded, object_pairs_hook=unique_object)
        if not isinstance(value, dict) or not 1 <= len(value) <= 80:
            raise ValueError("Payload inventory")
        fixed = {
            "Dockerfile",
            ".dockerignore",
            "compose.json",
            "requirements.lock",
            "images.lock.json",
            "engine.lock.json",
            "packages.lock.json",
            "scripts/credentials.py",
        }
        pattern = r"(opsjobs|guest)/[a-z_]+\.py|migrations/[0-9]{3}_[a-z_]+\.sql"
        pattern += r"|containers/[a-z-]+\.(sh|conf)"
        for name, content in value.items():
            if not isinstance(content, str) or not (name in fixed or re.fullmatch(pattern, name)):
                raise ValueError("Payload path/content allowlist")
            base64.b64decode(content, validate=True)
    except (ValueError, TypeError, RecursionError, zlib.error) as error:
        raise LabError("Invalid bounded guest payload") from error


def transfer_plan(encoded):
    """Build and validate every bounded SSH command before creating a VM."""
    validate_payload(encoded)
    chunks = [encoded[i : i + CHUNK_BYTES] for i in range(0, len(encoded), CHUNK_BYTES)]
    digest = hashlib.sha256(encoded.encode("ascii")).hexdigest()
    identity = [digest, str(len(chunks)), str(len(encoded))]
    plan = []

    def add(code, args, label, response):
        argv = ["sudo", "/usr/bin/python3", "-c", code, *args]
        command_bytes = len(shlex.join(argv).encode("utf-8"))
        if command_bytes > MAX_COMMAND_BYTES:
            raise LabError("Upload command exceeds conservative SSH multiplexing limit")
        plan.append({"argv": argv, "label": label, "response": response, "bytes": command_bytes})

    add(UPLOAD_START, identity, "upload-start", "upload-ready")
    for index, chunk in enumerate(chunks):
        part_digest = hashlib.sha256(chunk.encode("ascii")).hexdigest()
        add(
            UPLOAD_PART,
            [*identity, str(index), part_digest, chunk],
            f"upload-part-{index:04d}",
            "upload-part-stored",
        )
    add(INSTALLER, identity, "install-payload", "guest-payload-installed")
    return plan


def install_payload(provider, plan, report):
    for item in plan:
        output = provider.run(
            transport(provider, item["argv"]), distro="ubuntu", timeout=30, log=item["label"]
        )
        if output.strip() != item["response"]:
            raise LabError("Guest upload acknowledgement mismatch: " + item["label"])
        report["completed_commands"].append(item["label"])
    report["passed"] = True


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
    upload = transfer_plan(encoded)
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
        "transfer": {
            "sha256": hashlib.sha256(encoded.encode("ascii")).hexdigest(),
            "encoded_bytes": len(encoded),
            "parts": len(upload) - 2,
            "max_command_bytes": max(item["bytes"] for item in upload),
            "completed_commands": [],
            "passed": False,
        },
        "passed": False,
    }
    with provider.exclusive():
        if provider.state(initialize=True)["instances"]:
            raise LabError("Owned VM inventory not empty; use explicit teardown before rerunning")
        try:
            provider.start("ubuntu")
            install_payload(provider, upload, report["transfer"])
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
