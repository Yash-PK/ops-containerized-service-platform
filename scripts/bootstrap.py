#!/usr/bin/env python3
"""Install checksum-verified developer tools inside this repository only.

Adapted from the MIT-licensed fleet v0.1.0 developer bootstrap; the pinned
component's original license is retained by bootstrap_provider.py.
"""

import hashlib
import io
import json
import platform
import subprocess
import sys
import tarfile
import urllib.request
import venv
from pathlib import Path

from paths import bounded

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.version_info[:2] != (3, 14):
        raise SystemExit("Python 3.14 is required by this locked application/controller stack")
    target = bounded(ROOT, ROOT / ".venv")
    if not (target / "bin/python").exists():
        venv.EnvBuilder(with_pip=True).create(target)
    subprocess.run(
        [
            str(target / "bin/python"),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--require-hashes",
            "--only-binary=:all:",
            "-r",
            str(ROOT / "requirements-dev.lock"),
        ],
        check=True,
        timeout=240,
    )
    arch = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "x86_64"}.get(platform.machine())
    key = f"{platform.system().lower()}-{arch}"
    manifest = json.loads((ROOT / "tools.lock.json").read_text())
    output = bounded(ROOT, ROOT / ".tools/bin")
    output.mkdir(parents=True, exist_ok=True)
    for name, tool in manifest["tools"].items():
        if key not in tool["platforms"]:
            raise SystemExit(f"Unsupported developer-tool platform {key}: {name}")
        asset = tool["platforms"][key]
        binary = bounded(ROOT, output / name)
        marker = bounded(ROOT, output / (name + ".source-sha256"))
        # Recheck extracted binary to detect accidental local corruption.
        if binary.is_file() and marker.is_file():
            recorded = marker.read_text().split()
            if recorded == [asset["sha256"], hashlib.sha256(binary.read_bytes()).hexdigest()]:
                print(f"{name} {tool['version']}: verified cached installation")
                continue
        if not asset["url"].startswith("https://github.com/"):
            raise SystemExit("Only pinned official GitHub release downloads are permitted")
        print(f"Downloading {name} {tool['version']} ({key})", flush=True)
        with urllib.request.urlopen(asset["url"], timeout=90) as response:
            data = response.read(100_000_001)
        if len(data) > 100_000_000 or hashlib.sha256(data).hexdigest() != asset["sha256"]:
            raise SystemExit(f"Checksum/size mismatch for {name}; refusing installation")
        member = asset.get("member")
        if member:
            with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                entry = archive.getmember(member)
                if not entry.isfile() or entry.size > 100_000_000:
                    raise SystemExit(f"Unexpected archive member for {name}")
                data = archive.extractfile(entry).read()
                if asset.get("license_member"):
                    notice = archive.getmember(asset["license_member"])
                    if not notice.isfile() or notice.size > 1_000_000:
                        raise SystemExit(f"Unexpected license member for {name}")
                    license_dir = bounded(ROOT, ROOT / ".tools/licenses")
                    license_dir.mkdir(parents=True, exist_ok=True)
                    bounded(ROOT, license_dir / (name + ".txt")).write_bytes(
                        archive.extractfile(notice).read()
                    )
        binary.write_bytes(data)
        binary.chmod(0o755)
        marker.write_text(asset["sha256"] + " " + hashlib.sha256(data).hexdigest() + "\n")
    print("Developer tools installed locally. No global packages changed.")


if __name__ == "__main__":
    main()
