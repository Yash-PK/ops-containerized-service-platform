#!/usr/bin/env python3
"""Record actual controller gates with revision and code identity."""

import platform
import subprocess
from pathlib import Path

from clean_clone import run_command
from lab import code_digest, git, now, save_report

ROOT = Path(__file__).resolve().parents[1]


def main():
    revision = git(["rev-parse", "HEAD"])
    fingerprint = code_digest()
    if git(["status", "--porcelain"]):
        raise SystemExit("Commit reviewed changes before collecting formal controller evidence")
    report = {
        "schema_version": 1,
        "profile": "controller",
        "revision": revision,
        "code_sha256": fingerprint,
        "clean_at_start": True,
        "started_at": now(),
        "environment": {
            "os": platform.system(),
            "architecture": platform.machine(),
            "python": platform.python_version(),
        },
        "commands": [],
        "not_run": ["real VM profiles; see separately recorded integration report"],
    }
    replacements = {str(ROOT): "$REPO", str(Path.home()): "$HOME"}
    for target in ("doctor", "validate", "demo", "security"):
        item = run_command(["make", target], ROOT, replacements, timeout=600)
        report["commands"].append(item)
        print(f"make {target}: exit {item['exit_code']}", flush=True)
    report["source_unchanged"] = (
        code_digest() == fingerprint and git(["rev-parse", "HEAD"]) == revision
    )
    report["passed"] = report["source_unchanged"] and all(
        item["exit_code"] == 0 for item in report["commands"]
    )
    report["finished_at"] = now()
    destination = ROOT / "evidence" / f"{revision[:12]}-controller.json"
    save_report(report, destination)
    print(destination.relative_to(ROOT))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        raise SystemExit(f"Cannot identify source: Git exited {error.returncode}") from error
