# Bounded core acceptance — defined before implementation

Status: acceptance/dependency review; no container integration claim yet.

## Reference workload

- POST a bounded synthetic text-analysis job; return an immutable job ID promptly.
- A separate worker claims durable queued jobs from PostgreSQL and writes a real
  deterministic result (content digest and text statistics); API polling exposes
  queued/running/succeeded/failed states without fabricating completion.
- Versioned idempotent database migrations, identifiable deterministic seed data,
  bounded retries/lease handling and tests for invalid input and database failures.
- One maintained compatible Valkey cache for completed results; document SQL as
  the source of truth and exercise predictable cache-outage behavior.
- A reverse proxy exposes only the API. Generate fresh local credentials into
  ignored private runtime files. No embedded reusable password or public admin port.

## Containers and controller

- Pin official base/service images by verified digest and Python requirements with
  hashes; record supported versions, advisories and maintenance limitations.
- Multi-stage build, appropriate non-root execution, health/readiness checks,
  graceful shutdown, bounded resources, persistent named volume and explicit
  migration/dependency readiness. Explain layers, networks, namespaces and cgroups.
- Reproducible standalone Compose quickstart with no sibling-directory assumption.
  Use an explicit project/owned engine target and inventory before mutation.
- If local VM validation is required, use only a newly owned disposable VM with
  no host mounts or public port forwards; retain AppArmor and authenticated SSH.
  Do not start the existing default Colima environment or install host packages.

## Executable acceptance

- Clean setup submits a job while worker is stopped; observe queued state, start
  worker, and verify actual result and bounded completion.
- Restart application/database services and verify the original job/result persists.
- Stop cache and verify documented fallback, then recover; stop PostgreSQL and
  verify bounded API failure, then recover and complete a queued job.
- Invalid payloads rejected; migrations repeat without changes; seed repeats
  without duplicate rows; shutdown/restart does not lose accepted durable work.
- Assert service/process identities, private bindings, readiness and resource
  settings from the actual runtime. Unit fixtures do not prove containers.
- Teardown affects only the inventoried project; data removal requires explicit
  confirmation and dry-run default. Preserve failed evidence and cleanup outcomes.

## Publication

Source/configuration, appropriate tests/CI, dependency locks, task interface, MIT
license/attribution, architecture/decision/runbook/demo/security/contribution docs.
Pass clean-clone commands, required lint/tests, working/staged/full-history secret
scans and actual Compose integration before completed designation. Verify new
public repository owner/visibility/default branch/SHA and exact-target CI before
release. Container packages and cloud deployment remain disabled. Rootless Podman
and production improvements stay unverified until separately exercised.
