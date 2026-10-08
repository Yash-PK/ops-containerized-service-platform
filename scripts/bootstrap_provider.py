#!/usr/bin/env python3
"""Install and verify a released provider component and optional local Lima.

The small extraction helper is adapted from the MIT-licensed fleet v0.1.0
bootstrap, whose license is retained in .deps/fleet-provider-LICENSE.
"""

import hashlib
import io
import json
import platform
import re
import tarfile
import types
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath

from paths import bounded

ROOT = Path(__file__).resolve().parents[1]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def download(asset, limit=100_000_000):
    location = urllib.parse.urlparse(asset["url"])
    if location.scheme != "https" or location.hostname not in {
        "github.com",
        "raw.githubusercontent.com",
    }:
        raise ValueError("Dependency must use the pinned GitHub HTTPS origin")
    if not re.fullmatch(r"[0-9a-f]{64}", asset.get("sha256", "")):
        raise ValueError("Dependency requires an exact SHA256")
    with urllib.request.urlopen(asset["url"], timeout=90) as response:
        if urllib.parse.urlparse(response.url).scheme != "https":
            raise ValueError("Refusing a dependency redirect without TLS")
        data = response.read(limit + 1)
    if len(data) > limit or digest(data) != asset["sha256"]:
        raise ValueError("Dependency size or SHA256 mismatch")
    return data


def checked_file(root, path, expected):
    path = bounded(root, path)
    if not path.is_file():
        raise ValueError(f"Missing dependency {path.name}; run make bootstrap")
    if path.stat().st_size > 100_000_000:
        raise ValueError("Oversized cached dependency")
    data = path.read_bytes()
    if digest(data) != expected:
        raise ValueError(f"Cached dependency integrity mismatch: {path.name}")
    return data


def component_files(root):
    manifest = json.loads((root / "component.lock.json").read_text())
    if manifest.get("schema_version") != 1 or set(manifest.get("files", {})) != {
        "fleet_provider.py",
        "fleet-provider-LICENSE",
    }:
        raise ValueError("Unsupported component lock")
    if not re.fullmatch(r"[0-9a-f]{40}", manifest.get("revision", "")):
        raise ValueError("Component requires an immutable full Git revision")
    return manifest["files"]


def provider_asset(root):
    manifest = json.loads((root / "provider.lock.json").read_text())
    key = f"{platform.system()}-{platform.machine()}"
    asset = manifest["tool"]["platforms"].get(key)
    if asset is None:
        raise ValueError(f"VM provider UNAVAILABLE on {key}; macOS ARM64 VZ is required")
    return asset


def verify_binary(root):
    asset = provider_asset(root)
    entries = asset.get("files", {})
    if "bin/limactl" not in entries:
        raise ValueError("Provider lock lacks independently verified binary hashes")
    for name, item in entries.items():
        checked_file(root, root / ".tools/lima" / name, item["sha256"])


def load_provider(root, *, require_binary=False):
    """Hash-check source/license and optionally Lima before executing pinned code."""
    root = Path(root).absolute()
    files = component_files(root)
    source = None
    for name, asset in files.items():
        data = checked_file(root, root / ".deps" / name, asset["sha256"])
        if name == "fleet_provider.py":
            source = data
    if require_binary:
        verify_binary(root)
    module = types.ModuleType("ops_released_fleet_provider")
    module.__file__ = str(root / ".deps/fleet_provider.py")
    # Execute the bytes just verified, never an existing or stale bytecode cache.
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


def install_component(root):
    destination = bounded(root, root / ".deps")
    destination.mkdir(exist_ok=True)
    for name, asset in component_files(root).items():
        path = bounded(root, destination / name)
        if path.exists():
            checked_file(root, path, asset["sha256"])
            continue
        data = download(asset, 1_000_000)
        path.write_bytes(data)
        path.chmod(0o644)
    print("Released fleet provider source and MIT license: verified locally")


def install_lima(root):
    try:
        asset = provider_asset(root)
    except ValueError as error:
        print(error)
        return
    destination = bounded(root, root / ".tools/lima")
    if destination.exists():
        verify_binary(root)
        print("Lima: verified cached archive members")
        return
    data = download(asset)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        members = {}
        for entry in archive:
            name = PurePosixPath(entry.name)
            if name.is_absolute() or ".." in name.parts:
                raise ValueError("Unsafe provider archive path")
            if not entry.isfile():
                continue
            normalized = str(name)
            expected = asset["files"].get(normalized)
            if expected is None or entry.size > 100_000_000:
                raise ValueError("Unexpected provider archive member")
            payload = archive.extractfile(entry).read()
            if digest(payload) != expected["sha256"]:
                raise ValueError("Provider archive member hash mismatch")
            members[normalized] = payload
        if set(members) != set(asset["files"]):
            raise ValueError("Provider archive is missing locked members")
        for name, payload in members.items():
            path = bounded(root, destination / name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            path.chmod(int(asset["files"][name]["mode"], 8))
    verify_binary(root)
    print("Lima: verified and installed only in .tools/lima; no VM started")


def main():
    install_component(ROOT)
    install_lima(ROOT)


if __name__ == "__main__":
    main()
