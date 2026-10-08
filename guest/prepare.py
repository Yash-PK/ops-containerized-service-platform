"""Stage signed snapshot packages in this disposable guest; never touch the host."""

import json
import os
import pwd
import stat
from pathlib import Path

from guest.common import ROOT, regular


def run(ctx):
    release = dict(
        line.split("=", 1)
        for line in Path("/etc/os-release").read_text().splitlines()
        if "=" in line
    )
    ctx.check(
        "ubuntu_24_04", release.get("ID") == "ubuntu" and release.get("VERSION_ID") == '"24.04"'
    )
    ctx.check(
        "native_arm64", ctx.run(["dpkg", "--print-architecture"], label="arch").strip() == "arm64"
    )
    lock = json.loads((ROOT / "packages.lock.json").read_text())
    ctx.check("signed_snapshot_selected", lock["snapshot"] == "20261007T000000Z")
    lists = Path("/var/lib/apt/lists/ops-container-platform")
    lists.mkdir(mode=0o755)
    partial = lists / "partial"
    partial.mkdir(mode=0o700)
    os.chown(partial, pwd.getpwnam("_apt").pw_uid, 0)
    source = ROOT / "snapshot.sources"
    source.write_text(
        "Types: deb\nURIs: https://snapshot.ubuntu.com/ubuntu/"
        + lock["snapshot"]
        + "/\nSuites: noble noble-updates noble-security\n"
        "Components: main restricted universe multiverse\nArchitectures: arm64\n"
        "Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n"
    )
    options = [
        "-o",
        f"Dir::Etc::sourcelist={source}",
        "-o",
        "Dir::Etc::sourceparts=-",
        "-o",
        f"Dir::State::lists={lists}",
        "-o",
        "Acquire::Retries=2",
        "-o",
        "Acquire::https::Timeout=30",
        "-o",
        "Dpkg::Use-Pty=0",
    ]
    ctx.run(["apt-get", *options, "update", "--error-on=any"], label="apt-update", timeout=600)
    policy = Path("/usr/sbin/policy-rc.d")
    previous = None
    if policy.exists() or policy.is_symlink():
        regular(policy)
        previous = (policy.read_bytes(), stat.S_IMODE(policy.stat().st_mode))
    try:
        descriptor = os.open(policy, os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_NOFOLLOW, 0o755)
        with os.fdopen(descriptor, "w") as handle:
            handle.write("#!/bin/sh\n# owned container lab staging\nexit 101\n")
            os.fchmod(handle.fileno(), 0o755)
        pins = [name + "=" + item["version"] for name, item in sorted(lock["packages"].items())]
        ctx.run(
            [
                "env",
                "DEBIAN_FRONTEND=noninteractive",
                "NEEDRESTART_MODE=l",
                "apt-get",
                *options,
                "install",
                "--yes",
                "--no-install-recommends",
                *pins,
            ],
            label="apt-install",
            timeout=1200,
        )
    finally:
        if previous is None:
            policy.unlink()
        else:
            policy.write_bytes(previous[0])
            policy.chmod(previous[1])
    for name, item in lock["packages"].items():
        version = ctx.run(["dpkg-query", "-W", "-f=${Version}", name], label="package-" + name)
        ctx.check("pinned_" + name, version.strip() == item["version"])
    return lock["expected_kernel"]
