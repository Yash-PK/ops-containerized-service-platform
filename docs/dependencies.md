# Dependency selection and verification

Review date: **2026-10-08**. These are the selected inputs, not a guarantee that
they will remain the newest supported versions. Recheck maintenance status and
advisories when updating a lock. Download failures must remain visible.

## Application and images

| Component | Selection | Verification and reason |
| --- | --- | --- |
| Python | 3.14.7, `slim-trixie` | Exact interpreter version in `.python-version`; official image index digest in `images.lock.json` and both Dockerfile stages. The application and bootstrap require Python 3.14. |
| Psycopg / binary wheel | 3.3.6 | PyPI version metadata and wheel SHA256 values captured in `dependency-audit.json`, installed using `--require-hashes --only-binary=:all:`. The [release notes](https://www.psycopg.org/psycopg3/docs/news.html) identify 3.3.6 as released and 3.3.7 as unreleased on the review date. |
| Valkey Python client | 6.1.1 | Exact PyPI wheel hash and Python requirement recorded in the audit; the [official client catalog](https://valkey.io/clients/) identifies valkey-py as a maintained client. Only basic authenticated GETRANGE/SET/PING behavior is used and must be exercised against the chosen server. |
| PostgreSQL | 18.6, `trixie` | Maintained release branch from the [version policy](https://www.postgresql.org/support/versioning/), [18.6 release notes](https://www.postgresql.org/docs/18/release-18-6.html), and official image metadata. PostgreSQL 19 prerelease is not selected. |
| Valkey server | 9.1.2, `trixie` | [Official releases](https://valkey.io/download/releases/) and published advisory ranges; pinned upstream image index. |
| nginx | 1.30.5, `trixie` | Stable version checked against [official downloads](https://nginx.org/en/download.html) and [security advisories](https://nginx.org/en/security_advisories.html); pinned official image index. |

`images.lock.json` records the full OCI index digest and Linux ARM64/AMD64
platform descriptors obtained from the registry. SHA256 of the fetched manifest
bytes was checked against the registry content digest. The Compose file and
Dockerfile use those immutable index digests. Presence of an AMD64 descriptor
does not establish an AMD64 integration test.

The PostgreSQL volume mounts `/var/lib/postgresql`, following the
[official image's PostgreSQL 18 layout](https://github.com/docker-library/docs/blob/master/postgres/README.md).
Its version-specific data directory is beneath that mount. Reusing an older
major-version volume without a supported upgrade is not part of the quickstart.

The binary Psycopg distribution bundles native libraries. During local dependency
inspection, the installed macOS wheel reported libpq `180006` (18.6); that one
observation does not establish the contents or vulnerability status of every
wheel in the lock. Runtime integration should record the actual loaded version.

## Engine and owned VM

| Component | Selection and lock | Upstream reference |
| --- | --- | --- |
| Docker engine | 29.8.2 Linux ARM64 static bundle; `engine.lock.json` | [Engine release notes](https://docs.docker.com/engine/release-notes/29/) and [binary installation guidance](https://docs.docker.com/engine/install/binaries/) |
| Docker Compose | 5.6.0 Linux ARM64 plugin; `engine.lock.json` | [Official release](https://github.com/docker/compose/releases/tag/v5.6.0) |
| Docker Buildx | 0.38.0 Linux ARM64 plugin; `engine.lock.json` | [Official release](https://github.com/docker/buildx/releases/tag/v0.38.0) |
| Lima | 2.2.1 macOS ARM64; `provider.lock.json` | [Official release](https://github.com/lima-vm/lima/releases/tag/v2.2.1) |
| Ubuntu guest | 24.04 ARM64 cloud image dated 20260926; `provider.lock.json` | [Official image release](https://cloud-images.ubuntu.com/releases/noble/release-20260926/) |
| Guest package profile | Ubuntu snapshot `20261007T000000Z`, exact selected package versions; `packages.lock.json` | [Ubuntu snapshot service](https://snapshot.ubuntu.com/) |
| Fleet provider component | Released v0.1.0 source revision `1531b86b54eee87d01da83f7b55d7d405f43fadb`; `component.lock.json` | [Verified portfolio release](https://github.com/Yash-PK/ops-linux-fleet-automation/releases/tag/v0.1.0) |

The Docker static archive SHA256 was computed from an official HTTPS download;
no independently signed-checksum verification is claimed. Compose/Buildx hashes
were compared with official GitHub release-asset digests. Bootstrap checks actual
bytes again before using them. Static binaries do not receive package-manager
security updates, which is one reason this daemon belongs to a disposable test
guest. The host's installed Docker CLI is not the selected engine.

Guest package index hashes are retained as selection provenance. APT verifies Ubuntu archive
signatures during installation; a downloaded index over TLS alone is not that
signature verification. The expected post-preparation kernel is
`6.8.0-146-generic`, checked after a cold boot. Selected direct package versions
are pinned; a complete transitive package closure and byte-identical disk image
rebuild are not claimed.

The released provider script is a small pinned component with its original MIT
license, not an undocumented sibling import. Its configuration contains another
distro entry required by the unchanged provider validator; this project does
not claim that distro as an exercised platform.

## Selected security review

Docker 29.8.2 fixes OCI-index resource exhaustion and registry TLS fallback
issues, among other runtime/build fixes. This profile selects that maintenance
release instead of adopting an older host CLI/daemon. The exact affected
components and additional fixes are described in the
[engine release notes](https://docs.docker.com/engine/release-notes/29/).

Valkey 9.1.2 is listed as patched for
[GHSA-jcj7-v34w-v9vv](https://github.com/valkey-io/valkey/security/advisories/GHSA-jcj7-v34w-v9vv)
and [GHSA-fq2f-crmw-q97r](https://github.com/valkey-io/valkey/security/advisories/GHSA-fq2f-crmw-q97r).
The captured audit also retains earlier advisory ranges. nginx 1.30.5 is listed
as unaffected by CVE-2026-90439 and includes the stable 1.30.4 fixes for the map,
slice and SSI issues described on its
[advisory page](https://nginx.org/en/security_advisories.html).

PostgreSQL 18.6 includes security corrections affecting server and client
behavior; the [release notes](https://www.postgresql.org/docs/18/release-18-6.html)
are the authority for those changes. No claim is made that private networking
would make an earlier vulnerable version acceptable. Compose 5.6.0 is beyond
the patched 2.40.2 boundary in the captured
[OCI-loading advisory](https://github.com/docker/compose/security/advisories/GHSA-gv8h-7v7w-r22q).

The published Psycopg/valkey-py advisory API and PyPI vulnerability metadata were
empty for the selected releases when captured. That means no advisory was
returned by those sources; it is not proof of zero vulnerabilities. Base-image
OS libraries, bundled runtime libraries and every transitive dependency have
not received a complete independent vulnerability audit. No exception waives a
known failing security gate, and no production suitability claim follows from
this selected review.

## Developer tools and update procedure

`requirements-dev.lock` pins Ruff 0.16.10 with hashes. `tools.lock.json` pins
ShellCheck 0.11.0, shfmt 3.14.1, actionlint 1.7.12 and Gitleaks 8.30.1 by platform
asset hash. These tools cover this repository's Python/shell/workflow/secret
checks; unrelated scanners are not installed to inflate tool coverage.

An update must retrieve official release/support/advisory information, verify
new hashes or image descriptors, update all consumers of the lock, rerun
controller checks and a clean-clone bootstrap, then run the real lifecycle
profile. Record the old/new source revisions and failures. Keep architecture
claims tied to the platforms actually executed. Pinning plus repeatable commands
defines the intended inputs; a demonstrated successful run establishes only the
environment and behaviors recorded in its evidence.
