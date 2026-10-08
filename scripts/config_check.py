"""Check lock/configuration consistency; real Compose validation is separate."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def validate(root=ROOT):
    images = json.loads((root / "images.lock.json").read_text())["images"]
    compose = json.loads((root / "compose.json").read_text())
    if compose["name"] != "ops-container-platform-reference":
        raise ValueError("Unexpected Compose project identity")
    for service, image in [("database", "postgres"), ("cache", "valkey"), ("proxy", "nginx")]:
        if compose["services"][service]["image"] != images[image]["image"]:
            raise ValueError("Compose image differs from lock: " + service)
    for item in images.values():
        if not re.fullmatch("sha256:[0-9a-f]{64}", item["digest"]):
            raise ValueError("Invalid image digest")
    dockerfile = (root / "Dockerfile").read_text()
    if dockerfile.count(images["python"]["image"].removeprefix("library/")) != 2:
        raise ValueError("Both build stages must pin the same Python image")
    for name, service in compose["services"].items():
        if service.get("privileged") or service.get("network_mode") or service.get("pid"):
            raise ValueError("Privileged/host namespaces forbidden")
        if name != "proxy" and service.get("ports"):
            raise ValueError("Administrative port exposure forbidden")
        if not service.get("mem_limit") or not service.get("cpus") or not service.get("pids_limit"):
            raise ValueError("Resource bounds required: " + name)
        if any("/var/run/docker.sock" in volume for volume in service.get("volumes", [])):
            raise ValueError("Daemon socket mount forbidden")
    if compose["services"]["proxy"]["ports"] != ["127.0.0.1:8080:8080"]:
        raise ValueError("Only loopback proxy binding supported")
    if set(compose["networks"]) != {"frontend", "backend", "edge"}:
        raise ValueError("Unexpected network topology")
    if not all(compose["networks"][name].get("internal") for name in ("frontend", "backend")):
        raise ValueError("Application networks must be internal")
    if compose["networks"]["edge"].get("internal") is not False:
        raise ValueError("Proxy edge must support loopback publishing")
    for name, service in compose["services"].items():
        if ("edge" in service["networks"]) != (name == "proxy"):
            raise ValueError("Only the proxy may join the edge network")
    print("Locked images, explicit namespaces, local bindings and resource policy: PASS")


if __name__ == "__main__":
    validate()
