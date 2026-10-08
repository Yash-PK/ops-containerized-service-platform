#!/usr/bin/env python3
"""Credential-free new-repository publisher; never overwrite or reuse a collision."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from lab import code_digest, git

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "Yash-PK/ops-containerized-service-platform"
DESCRIPTION = (
    "Durable asynchronous jobs with PostgreSQL, Valkey and Docker Compose; "
    "bounded failures and recovery in an owned local VM."
)


def command(argv, *, capture=False, timeout=120):
    return subprocess.run(
        argv, cwd=ROOT, text=True, capture_output=capture, check=True, timeout=timeout
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute", action="store_true", help="Create only after all local gates pass"
    )
    args = parser.parse_args()
    create = [
        "gh",
        "repo",
        "create",
        REPOSITORY,
        "--public",
        "--source",
        str(ROOT),
        "--remote",
        "origin",
        "--push",
        "--description",
        DESCRIPTION,
    ]
    if not args.execute:
        print("After source/evidence review and a clean commit, run:")
        print("  make gate")
        print("  .venv/bin/python scripts/publish.py --execute")
        print("The script verifies authentication, collision, gates and exact outgoing identity.")
        print("Creation command (only after the same gates):")
        print(f"  gh repo create {REPOSITORY} --public --source . --remote origin --push")
        print("No credentials are requested or printed. CI remains pending until inspected.")
        return 0
    if git(["status", "--porcelain"]):
        raise SystemExit("Commit reviewed source/evidence first")
    if git(["branch", "--show-current"]) != "main":
        raise SystemExit("Publish only the reviewed main branch")
    if git(["remote"]):
        raise SystemExit(
            "New-repository script refuses existing remotes; inspect saved metadata manually"
        )
    revision, fingerprint = git(["rev-parse", "HEAD"]), code_digest()
    command(["make", "gate"], timeout=1800)
    if git(["status", "--porcelain"]):
        raise SystemExit("Source changed during publishing gate")
    command(["make", "security"], timeout=300)
    if code_digest() != fingerprint or git(["rev-parse", "HEAD"]) != revision:
        raise SystemExit("Source changed during publishing gate")
    for subject in (
        ["gh", "repo", "create", "--help"],
        ["gh", "repo", "view", "--help"],
        ["gh", "api", "--help"],
        ["gh", "run", "list", "--help"],
    ):
        command(subject, capture=True)
    login = command(["gh", "api", "user", "--jq", ".login"], capture=True).stdout.strip()
    if login != "Yash-PK":
        raise SystemExit("Authenticated personal account differs from authorized owner Yash-PK")
    collision = subprocess.run(
        ["gh", "api", f"repos/{REPOSITORY}"], cwd=ROOT, text=True, capture_output=True, timeout=60
    )
    if collision.returncode == 0:
        raise SystemExit("Repository collision: refusing reuse, overwrite or silent rename")
    if "HTTP 404" not in collision.stderr:
        raise SystemExit("Cannot establish repository absence; publication blocked")
    print(
        f"Publishing reviewed commit {revision}; exact-head CI remains pending.",
        flush=True,
    )
    command(create, timeout=300)
    metadata = json.loads(
        command(
            [
                "gh",
                "repo",
                "view",
                REPOSITORY,
                "--json",
                "url,owner,name,visibility,defaultBranchRef",
            ],
            capture=True,
        ).stdout
    )
    if (
        metadata["owner"]["login"] != "Yash-PK"
        or metadata["visibility"] != "PUBLIC"
        or metadata["defaultBranchRef"]["name"] != "main"
    ):
        raise SystemExit(
            "Created repository metadata differs from configuration; inspect, do not overwrite"
        )
    remote = command(
        ["git", "ls-remote", "origin", "refs/heads/main"], capture=True
    ).stdout.split()[0]
    if remote != revision:
        raise SystemExit("Remote SHA differs from reviewed source")
    print(
        json.dumps(
            {
                "url": metadata["url"],
                "revision": revision,
                "publication": "verified",
                "ci": "pending inspection",
                "release": "not created",
            },
            indent=2,
        )
    )
    command(
        [
            "gh",
            "run",
            "list",
            "--repo",
            REPOSITORY,
            "--commit",
            revision,
            "--json",
            "headSha,status,conclusion,url",
        ]
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(
            f"Publishing blocked: {type(error).__name__}. "
            "Inspect the last operation; no force/retry adoption occurs.",
            file=sys.stderr,
        )
        raise SystemExit(1) from error
