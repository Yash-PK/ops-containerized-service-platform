#!/usr/bin/env python3
"""Inspect tool versions without changing host configuration or allocating a VM."""

import json
import platform
import subprocess
import sys
from pathlib import Path

from bootstrap_provider import load_provider

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.version_info[:2] != (3, 14):
        raise SystemExit("Application/controller requires locked Python 3.14")
    print(
        f"Controller: {platform.system()} {platform.machine()} Python {platform.python_version()}"
    )
    load_provider(ROOT)
    manifest = json.loads((ROOT / "tools.lock.json").read_text())
    for name, item in manifest["tools"].items():
        path = ROOT / ".tools/bin" / name
        result = subprocess.run(
            [str(path), "version" if name == "gitleaks" else "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        output = result.stdout + result.stderr
        if item["version"] not in output:
            raise SystemExit(f"{name}: installed version differs from lock")
        print(f"{name}: {item['version']}")
    subprocess.run([str(ROOT / ".venv/bin/ruff"), "--version"], timeout=10, check=True)
    if (platform.system(), platform.machine()) == ("Darwin", "arm64"):
        load_provider(ROOT, require_binary=True)
        print(
            "VM provider: verified local Lima; real profile requires "
            "hardware virtualization and free resources"
        )
    else:
        print(
            "VM integration UNAVAILABLE here: requires macOS ARM64 VZ; "
            "controller gates remain applicable"
        )


if __name__ == "__main__":
    main()
