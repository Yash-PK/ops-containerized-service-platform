# Validation record

Project 4 is in implementation. No release or container integration pass is claimed.
The controller tests execute HTTP socket behavior, payload validation, cache fallback,
worker fencing calls and guard/credential/file-boundary cases. They do not prove SQL
or container behavior. The exact number is recorded by the actual unittest output.

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
satisfying the migration dependency. These changes still require a new real run.

The third run (`20261008T064506703400-development.json`) started the pinned engine,
built the application, pulled the service images and applied migration 1. Compose
reported services ready, but the first guest-loopback HTTP connection was refused.
Its process-only proxy health check had not proved the client path. The proxy now
has an HTTP readiness probe and a dedicated normal bridge for loopback publishing;
API/database/cache remain on the two internal networks. Both Compose teardown and
VM deletion passed on the failed run. Real acceptance remains pending.

The fourth run (`20261008T065059048620-development.json`) passed real asynchronous
completion, replay/conflict checks, cache hits and outage fallback/recovery,
persistence after restart, bounded database failure and recovery, API SIGTERM,
migration/seed idempotency and all 21 real PostgreSQL assertions. It then failed
process inspection: Docker requires a PID column to filter `docker top` results,
and the harness requested only UID/arguments. The fix requests UID/PID/arguments,
validates numeric identities and tests malformed/empty output. Requested port
bindings are now also compared with realized engine mappings. This run remains
failed overall; Compose resources and the owned VM were removed successfully.
