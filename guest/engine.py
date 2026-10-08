"""Checksum-pinned static Docker, only inside a fresh authenticated lab VM."""

import hashlib
import io
import json
import re
import tarfile
import urllib.parse
import urllib.request
from pathlib import Path

from guest.common import LAB_ID, ROOT, LabError, regular

ENGINE_MEMBERS = {
    "containerd-shim-runc-v2",
    "dockerd",
    "docker-proxy",
    "runc",
    "docker-init",
    "ctr",
    "containerd",
    "docker",
}


def fetch(item):
    parsed = urllib.parse.urlparse(item["url"])
    if parsed.scheme != "https" or parsed.hostname not in {"github.com", "download.docker.com"}:
        raise LabError("Unexpected engine download origin")
    if not re.fullmatch("[0-9a-f]{64}", item["sha256"]):
        raise LabError("Engine asset requires exact checksum")
    with urllib.request.urlopen(item["url"], timeout=120) as response:
        if urllib.parse.urlparse(response.url).scheme != "https":
            raise LabError("Engine redirect lost TLS")
        data = response.read(150000001)
    if len(data) > 150000000 or hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise LabError("Engine asset checksum mismatch")
    return data


def install(ctx):
    lock = json.loads((ROOT / "engine.lock.json").read_text())
    ctx.check("engine_platform", lock["platform"] == "linux-arm64")
    ctx.check("no_foreign_docker_socket", not Path("/var/run/docker.sock").exists())
    tools = ROOT / "tools"
    tools.mkdir(mode=0o755)
    binaries = tools / "docker"
    binaries.mkdir(mode=0o755)
    data = fetch(lock["assets"]["engine"])
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        seen = set()
        for member in archive:
            if member.name == "docker" and member.isdir():
                continue
            if not member.isfile() or member.name not in {"docker/" + x for x in ENGINE_MEMBERS}:
                raise LabError("Unexpected engine archive member")
            name = member.name.split("/")[1]
            if name in seen or member.size > 120000000:
                raise LabError("Duplicate/oversized engine archive member")
            seen.add(name)
            path = binaries / name
            with path.open("xb") as output:
                output.write(archive.extractfile(member).read())
            path.chmod(0o755)
        if seen != ENGINE_MEMBERS:
            raise LabError("Incomplete engine archive")
    plugins = tools / "plugins"
    plugins.mkdir(mode=0o755)
    for name in ("compose", "buildx"):
        path = plugins / ("docker-" + name)
        path.write_bytes(fetch(lock["assets"][name]))
        path.chmod(0o755)
    config = ROOT / ".runtime/docker-config"
    config.mkdir(mode=0o700)
    (config / "config.json").write_text(json.dumps({"cliPluginsExtraDirs": [str(plugins)]}))
    (ROOT / "run").mkdir(mode=0o700)
    daemon = ROOT / "daemon.json"
    daemon.write_text(
        json.dumps(
            {
                "hosts": ["unix://" + str(ROOT / "run/docker.sock")],
                "data-root": str(ROOT / "engine-data"),
                "exec-root": "/run/ops-container-platform",
                "pidfile": str(ROOT / "run/docker.pid"),
                "bridge": "opsjobs0",
                "group": "root",
                "live-restore": True,
                "log-driver": "local",
                "labels": ["io.ops.lab=" + LAB_ID],
            }
        )
    )
    unit = Path("/etc/systemd/system/ops-container-platform-engine.service")
    if unit.exists() or unit.is_symlink():
        raise LabError("Refusing existing engine unit")
    unit.write_text(
        "[Unit]\nDescription=Owned disposable container lab engine\n"
        "After=network-online.target\n[Service]\nType=notify\n"
        f"Environment=PATH={binaries}:/usr/sbin:/usr/bin:/sbin:/bin\n"
        f"ExecStart={binaries}/dockerd --config-file={daemon}\n"
        "Delegate=yes\nKillMode=process\nTimeoutStartSec=120\n"
        "TimeoutStopSec=60\nLimitNOFILE=1048576\nTasksMax=infinity\n"
    )
    ctx.run(["systemctl", "daemon-reload"], label="engine-unit-load")
    ctx.run(["systemctl", "start", unit.name], label="engine-start", timeout=150)
    info = json.loads(ctx.docker(["info", "--format", "{{json .}}"], label="engine-info"))
    ctx.check("engine_version_pinned", info["ServerVersion"] == lock["assets"]["engine"]["version"])
    ctx.check("engine_label", "io.ops.lab=" + LAB_ID in info["Labels"])
    ctx.check("engine_private_data", info["DockerRootDir"] == str(ROOT / "engine-data"))
    ctx.check("engine_apparmor", any("apparmor" in x for x in info["SecurityOptions"]))
    (ROOT / "engine-owner.json").write_text(json.dumps({"id": info["ID"], "lab_id": LAB_ID}))
    for name in ("compose", "buildx"):
        output = ctx.docker([name, "version"], label=name + "-version")
        ctx.check(name + "_pinned", lock["assets"][name]["version"] in output)
    ctx.report["engine"] = {
        "version": info["ServerVersion"],
        "architecture": info["Architecture"],
        "cgroup_version": info["CgroupVersion"],
        "security_options": info["SecurityOptions"],
    }


def owned(ctx):
    record = json.loads(regular(ROOT / "engine-owner.json").read_text())
    info = json.loads(ctx.docker(["info", "--format", "{{json .}}"], label="verify-engine"))
    if (
        record != {"id": info["ID"], "lab_id": LAB_ID}
        or info["DockerRootDir"] != str(ROOT / "engine-data")
        or "io.ops.lab=" + LAB_ID not in info["Labels"]
    ):
        raise LabError("Engine ownership mismatch; no mutation allowed")
    return info
