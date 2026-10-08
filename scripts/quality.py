#!/usr/bin/env python3
"""Check required documents, local references and tracked private-artifact exclusions."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "README.md",
    "AGENTS.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "LICENSE",
    "Makefile",
    ".gitignore",
    ".editorconfig",
    "docs/acceptance.md",
    "docs/architecture.md",
    "docs/decisions/001-durable-postgres-queue.md",
    "docs/runbook.md",
    "docs/validation.md",
    "docs/dependencies.md",
    "docs/demo.md",
)


def main():
    for name in REQUIRED:
        path = ROOT / name
        if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
            raise SystemExit(f"Missing regular required document: {name}")
    paths = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT
    ).split(b"\0")
    for raw in set(paths) - {b""}:
        name = raw.decode()
        path = ROOT / name
        if path.is_symlink():
            raise SystemExit(f"Symlink not allowed in outgoing files: {name}")
        if name.startswith((".runtime/", ".tools/", ".deps/", ".venv/")) or path.suffix in {
            ".key",
            ".pem",
            ".pcap",
            ".img",
            ".qcow2",
        }:
            raise SystemExit(f"Private/generated artifact in outgoing files: {name}")
        if path.suffix != ".md":
            continue
        for target in re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", path.read_text()):
            if "://" in target or target.startswith("mailto:"):
                continue
            destination = (path.parent / target).resolve()
            if not destination.is_relative_to(ROOT) or not destination.exists():
                raise SystemExit(f"Broken/outside local link: {name}: {target}")
    print("Required documents, local links and outgoing artifact boundaries: PASS")


if __name__ == "__main__":
    main()
