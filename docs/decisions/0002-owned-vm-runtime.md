# ADR 0002: run the engine inside a disposable, inventoried VZ guest

Status: accepted for macOS ARM64 integration.

## Context

The workstation may have Docker contexts and VM instances unrelated to this
portfolio. A usable CLI does not establish permission to start, modify or prune
those resources. Container integration requires a real Linux kernel, daemon,
networking and writable volumes; controller fixtures cannot prove that behavior.

## Decision

Use a project-local pinned Lima/VZ provider to create one Ubuntu ARM64 guest.
Verify its ownership before privileged guest actions. Install the pinned Docker
engine, Compose and Buildx inside that guest, and use only its explicitly owned
engine and Compose project. Do not mount host directories or forward application
ports. Execute the client against guest loopback. Run faults sequentially and
attempt inventory-scoped teardown in the integration finalizer.

The provider code is fetched by released revision and SHA256 with its MIT license.
Its internal fleet marker is retained instead of weakening its guards. This
repository's private runtime root separates its VM inventory from other projects.

## Consequences

Privileged Docker setup, package changes and container firewall rules remain
inside disposable resources. Existing host contexts, host SSH settings and
global packages remain outside the operation. The guest is a real VM; the
containers still share that guest's kernel. This does not prove a cloud provider,
Kubernetes platform, alternate host architecture or rootless runtime.

The profile is heavier than controller tests and needs Apple virtualization
support, downloads and disk cache. A pinned static engine needs explicit security
updates; it does not receive unattended package-manager upgrades. The supported
integration command is intentionally destructive only to this lab's synthetic
data and requires the exact lab identifier. A retained failed inventory must be
reviewed before retrying; broad cleanup is never an acceptable shortcut.
