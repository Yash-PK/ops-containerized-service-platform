#!/usr/bin/env python3
"""Validate a clean temporary clone; bootstrap downloads locked developer tools."""

import argparse
import datetime
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from lab import save_report

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ("bootstrap", "doctor", "validate", "demo", "security")


def sanitize(value, replacements):
    """Remove local checkout, temporary directory and home paths from evidence."""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    result = value or ""
    for source, replacement in sorted(replacements.items(), key=lambda item: -len(item[0])):
        result = result.replace(source, replacement)
    return result


def run_command(command, cwd, replacements, timeout=600):
    start = time.monotonic()
    timed_out = False
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        code, output = result.returncode, result.stdout
    except subprocess.TimeoutExpired as error:
        timed_out = True
        code, output = 124, error.stdout or ""
    except OSError as error:
        code, output = 127, str(error)
    return {
        "argv": [sanitize(argument, replacements) for argument in command],
        "exit_code": code,
        "timed_out": timed_out,
        "timeout_seconds": timeout,
        "duration_seconds": round(time.monotonic() - start, 3),
        "output": sanitize(output, replacements),
    }


def validate(root=ROOT):
    """Run real clone/gates and persist success or failure without touching host state."""
    root = root.resolve()
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        timeout=30,
    ).strip()
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain"],
        cwd=root,
        text=True,
        timeout=30,
    )
    if dirty:
        raise SystemExit("Commit changes first: clean-clone evidence requires clean source")
    destination = root / "evidence" / f"{revision[:12]}-clean-clone.json"
    if destination.exists() or destination.is_symlink():
        raise SystemExit("Evidence already exists; preserve it and use a new tested commit")
    report = {
        "schema_version": 1,
        "revision": revision,
        "profile": "clean-clone",
        "clean_at_start": True,
        "network_required": "bootstrap downloads checksum/hash-locked tools",
        "environment": {
            "os": platform.system(),
            "release": platform.release(),
            "architecture": platform.machine(),
            "python": platform.python_version(),
        },
        "started_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "commands": [],
        "assertions": [],
        "not_run": list(TARGETS),
    }
    print("Clean-clone gate: network is required for locked bootstrap downloads.", flush=True)
    with tempfile.TemporaryDirectory(prefix="ops-clean-clone-") as temporary:
        checkout = Path(temporary) / root.name
        replacements = {
            str(root): "$SOURCE_REPO",
            str(checkout): "$CLEAN_CLONE",
            temporary: "$TEMP",
            str(Path.home()): "$HOME",
        }
        clone = run_command(
            ["git", "clone", "--no-local", "--", str(root), str(checkout)],
            root,
            replacements,
            timeout=120,
        )
        report["commands"].append(clone)
        if clone["exit_code"] == 0:
            head = run_command(["git", "rev-parse", "HEAD"], checkout, replacements, timeout=30)
            report["commands"].append(head)
            same_revision = head["exit_code"] == 0 and head["output"].strip() == revision
            report["assertions"].append(
                {
                    "name": "clone_revision_matches_source",
                    "passed": same_revision,
                }
            )
            if same_revision:
                for target in TARGETS:
                    result = run_command(
                        (
                            [
                                "make",
                                f"PYTHON={getattr(sys, '_base_executable', sys.executable)}",
                                target,
                            ]
                            if target == "bootstrap"
                            else ["make", target]
                        ),
                        checkout,
                        replacements,
                        timeout=900 if target == "bootstrap" else 600,
                    )
                    report["commands"].append(result)
                    report["not_run"].remove(target)
                    print(f"Clean clone: make {target}: exit {result['exit_code']}", flush=True)
                    if target == "bootstrap" and result["exit_code"] != 0:
                        break
                clean = run_command(
                    ["git", "status", "--porcelain"],
                    checkout,
                    replacements,
                    timeout=30,
                )
                report["commands"].append(clean)
                report["assertions"].append(
                    {
                        "name": "clone_remains_clean_after_checks",
                        "passed": clean["exit_code"] == 0 and not clean["output"].strip(),
                    }
                )
    report["temporary_clone_removed"] = not Path(temporary).exists()
    report["finished_at"] = datetime.datetime.now(datetime.UTC).isoformat()
    report["passed"] = (
        not report["not_run"]
        and all(item["exit_code"] == 0 for item in report["commands"])
        and all(item["passed"] for item in report["assertions"])
        and report["temporary_clone_removed"]
    )
    save_report(report, destination)
    print(destination.relative_to(root), flush=True)
    return report["passed"]


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    raise SystemExit(0 if validate() else 1)


if __name__ == "__main__":
    main()
