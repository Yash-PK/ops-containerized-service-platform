# Validation record

The bounded local core passed at source
`3d58b9f7107fa1c7de3eec06b32c9b6f6ce644d6`, implementation fingerprint
`2d02d563e250b498d07b3695894a21d825bc7310c6ed47bd2afc3ee55b1a2f2b`.
Publication, hosted CI and release remain pending. Evidence/documentation commits
after this source do not become the original tested revision.

| Profile | Actual result | Report |
| --- | --- | --- |
| Controller, macOS ARM64 / Python 3.14.7 | Doctor, lint/docs/config, 71 unit/controller/safety tests, safe demo and working/staged/history secret scans passed; clean source remained unchanged | [Controller](../evidence/3d58b9f7107f-controller.json) |
| Standalone temporary clone | Locked bootstrap, doctor, validation, demo and security passed; clone stayed clean and was removed | [Clean clone](../evidence/3d58b9f7107f-clean-clone.json) |
| Real Ubuntu ARM64 VZ / Docker Compose | 22 preparation commands/assertions, 117 Compose commands, 72 Compose assertions and all 21 nested real SQL assertions passed; guest resources and VM removed | [Formal VM](../evidence/3d58b9f7107f-compose-vm.json) |

The formal VM ran from `2026-10-08T07:14:49.280112+00:00` to
`2026-10-08T07:20:20.844680+00:00`, using 2 CPUs, 2 GiB RAM and a 24 GiB sparse
disk. Signed package preparation, cold boot into `6.8.0-146-generic`, authenticated
bounded upload, engine ownership and application lifecycle all passed. Observed
versions were Docker 29.8.2, Compose 5.6.0, Buildx 0.38.0, Python 3.14.7,
Psycopg 3.3.6, libpq 18.6 (`180006`) and valkey-py 6.1.1.

The scenario observed asynchronous completion, key replay/conflict rejection,
restart persistence, cache hits/failure/recovery, bounded database outage and
recovery, API SIGTERM exit 0, migration/seed idempotence, non-root live services,
memory/CPU bounds, AppArmor, internal networks and guest-loopback realized ports.
SQL assertions covered concurrent acceptance, leases/fencing, retry exhaustion,
transaction rollback and owned-schema cleanup. Compose cleanup and VM deletion
passed; the provider inventory was empty afterward. Ignored download/tools caches
may remain. This is functional lab evidence, not a capacity, availability or
disaster-recovery measurement.

Exact configured UIDs and individual PID/tmpfs/log/grace/read-only/capability
settings were not separately asserted live. Worker signal handling is implemented,
but its graceful-exit status was not asserted; the API assertion is distinct.
No cloud, rootless Podman or additional host/container architecture is claimed.

Required publication evidence: a clean committed source, controller report, temporary
clone report and a real Compose lifecycle report whose implementation fingerprint
matches current code. Later documentation/evidence commits preserve the tested code
revision rather than relabeling old output. GitHub CI is tracked independently.

`make integration-dev LAB=ops-container-platform-reference` writes private ignored
`.runtime/evidence/*-development.json`. It cannot satisfy a release gate. Failures and
cleanup outcomes remain available there. `make integration LAB=ops-container-platform-reference`
writes exclusive `evidence/<source12>-compose-vm.json`; commit that report before the
next clean-source gate. `make clean-clone` writes exclusive clone evidence and removes
its temporary checkout. `scripts/record_validation.py` records controller commands,
exit codes, environment, timestamps, code identity and sanitized output.

Real VM profiles require macOS ARM64 VZ. Linux CI executes controller gates only;
no cloud deployment, Podman or x86 container integration claim follows from its pass.

## Development observations

The first real run (`20261008T063613637487-development.json`, ignored) passed
signed package preparation and the controlled cold boot, then rejected the
private runtime parent mode before credential generation or engine installation.
`Path.mkdir(parents=True)` had created the intermediate directory as 0755. The
fix creates and validates each owned directory at 0700 explicitly; a regression
checks parent mode and symlink rejection. The VM was deleted successfully. This
failed run is retained and does not count as container acceptance.

The second development run (`20261008T064105368194-development.json`) passed
package preparation and cold boot, then the owned Docker unit failed to start.
VM teardown passed. Its unit journal was not captured, so the exact startup
cause is not established by that report. Review identified a non-default bridge
name without creation of the required device; the isolated daemon now uses its
normal default bridge. Startup diagnostics now retain the unit journal privately.
The same review moved all nginx temporary paths onto its bounded writable tmpfs
and changed PostgreSQL health to TCP, preventing socket-only initialization from
satisfying the migration dependency. The later complete formal run exercised these changes.

The third run (`20261008T064506703400-development.json`) started the pinned engine,
built the application, pulled the service images and applied migration 1. Compose
reported services ready, but the first guest-loopback HTTP connection was refused.
Its process-only proxy health check had not proved the client path. The proxy now
has an HTTP readiness probe and a dedicated normal bridge for loopback publishing;
API/database/cache remain on the two internal networks. Both Compose teardown and
VM deletion passed on the failed run. Real acceptance was still pending at that
stage; the later complete formal report now supplies it.

The fourth run (`20261008T065059048620-development.json`) passed real asynchronous
completion, replay/conflict checks, cache hits and outage fallback/recovery,
persistence after restart, bounded database failure and recovery, API SIGTERM,
migration/seed idempotency and all 21 real PostgreSQL assertions. It then failed
process inspection: Docker requires a PID column to filter `docker top` results,
and the harness requested only UID/arguments. The fix requests UID/PID/arguments,
validates numeric identities and tests malformed/empty output. Requested port
bindings are now also compared with realized engine mappings. This run remains
failed overall; Compose resources and the owned VM were removed successfully.

## First formal attempt

Source `950e511f42173c00994496265bb48104623e1bea` passed the 57-test controller
report and clean-clone quickstart. Its formal VM report is a **failure**:
`evidence/950e511f4217-compose-vm.json` records SSH upload exit 255 before any guest
phase ran. The private transport log reports `mm_send_fd: sendmsg(2): Message too
long` and `mux_client_request_session: send fds failed`. The encoded source was
54,532 bytes plus the installer, within the old application limit but too large
for this macOS multiplexed transport request. The VM was removed successfully.
A bounded chunked transfer now validates the complete payload before allocating
a VM, sends at most 8,000 encoded bytes per part, and caps each shell-quoted SSH
command at 16,000 bytes. The guest verifies staging ownership, sequence, part and
whole-payload checksums before installation. Fixture tests exercise corruption,
foreign files, symlinks, unsafe modes and interrupted transfer cleanup. This fix
was exercised successfully in the later formal run recorded above. Neither
passing controller checks nor the
previous partial workflow turns the failed report into release proof. Its tested
revision and failure remain preserved.
