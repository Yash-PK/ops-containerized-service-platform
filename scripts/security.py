#!/usr/bin/env python3
"""Scan working files, staged blobs, and the entire outgoing history."""

import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCANNER = ROOT / ".tools/bin/gitleaks"


def run(args):
    subprocess.run(
        [str(SCANNER), *args, "--redact", "--no-banner"], cwd=ROOT, check=True, timeout=120
    )


def export(index, destination):
    args = (
        ["git", "ls-files", "-z"]
        if index
        else ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
    )
    names = set(subprocess.check_output(args, cwd=ROOT).split(b"\0")) - {b""}
    for raw in names:
        name = raw.decode()
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise SystemExit("Unsafe Git path")
        source = ROOT / path
        if source.is_symlink():
            raise SystemExit(f"Refusing symlink: {name}")
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if index:
            target.write_bytes(subprocess.check_output(["git", "show", f":{name}"], cwd=ROOT))
        elif source.is_file():
            target.write_bytes(source.read_bytes())


def main():
    if not SCANNER.exists():
        raise SystemExit("Required Gitleaks missing: run make bootstrap")
    with tempfile.TemporaryDirectory(prefix="ops-scan-") as folder:
        base = Path(folder)
        for index, name in [(False, "working"), (True, "staged")]:
            destination = base / name
            destination.mkdir()
            export(index, destination)
            run(["dir", str(destination)])
    head = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if head.returncode == 0:
        run(["git", str(ROOT), "--log-opts=--all"])
    else:
        raise SystemExit(
            "Required history scan unavailable: create the reviewed initial commit, then rerun"
        )
    print("Working-tree and staged-file scans: PASS")


if __name__ == "__main__":
    main()
