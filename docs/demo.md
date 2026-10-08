# Demonstration walkthrough

Run the exact README commands from a clean checkout. The lightweight controller
demo is separate from the required real integration. For the latter:

```sh
make integration LAB=ops-container-platform-reference
```

Formal evidence requires a clean source commit and is saved once at
`evidence/<source-revision-first-12>-compose-vm.json`. During development, use
`make integration-dev LAB=ops-container-platform-reference`; its timestamped
report stays under ignored `.runtime/evidence` and is not release proof.

The lab ID is the explicit execution boundary. The profile allocates its own
VM/engine, runs the sequence below, and tears them down. There is no standing
macOS `localhost:8080` endpoint after the command returns.

## What the audience should observe

1. A pinned image build, ready PostgreSQL, successful migration, cache, API and
   proxy start. The worker is deliberately absent for the first submission.
2. `POST /jobs` accepts a synthetic text and returns `202` with a real queued ID.
   Polling leaves it queued. A repeat key returns the same ID; different content
   with that key returns `409`; invalid input is rejected.
3. Starting the worker produces a digest matching the submitted UTF-8 bytes.
   The result was computed asynchronously, not filled in by the API.
4. Restarting database/application containers preserves the original result.
   Stopping Valkey still allows SQL-backed reads. Starting it restores health.
5. A second accepted job waits while the worker is stopped. A PostgreSQL outage
   causes bounded `503` on new writes, `200` liveness and `503` readiness.
6. Restoring the database and application completes the previously accepted job.
   Graceful API shutdown, repeated migration/seed operations, SQL correctness,
   runtime identities, resource settings and private bindings are asserted.
7. The report states each observed assertion and the cleanup outcome. Review
   that report; the presence of a JSON file is not itself a pass.

These are expected assertions, not a pasted success transcript. A report tied to
the tested revision is the evidence for which of them actually ran and passed.

## Explain the implementation in an interview

Start with `opsjobs/database.py`: the accepted row and the durable queue are the
same record. Show the unique idempotency key and where a transaction commits
before HTTP `202`. Discuss the ambiguous-client-response case and why retrying
with the same key recovers the original job.

Follow `claim` and `complete`: `SKIP LOCKED` coordinates claimants, while the
lease token and expiry fence stale completion. A crash can repeat computation.
Because analysis is pure and small, repeated computation has no external side
effect. Explain why a payment or email job would require more than this design.

Open `cache.py` and stop the cache in the scenario: a cache miss/error reads SQL.
Only terminal success is cached, avoiding stale queue state. Then distinguish
database failure from cache failure using live/ready and the write response.

Compare `Dockerfile` with `compose.json`: the build stages isolate dependency
installation, numeric UIDs and read-only filesystems constrain processes, networks
separate ingress from data services, and cgroup settings bound resources. These
containers share one Linux kernel; VZ provides the surrounding VM boundary.

End at the evidence and limitations: restart persistence is not disaster
recovery, a short functional run is not an availability record, and one verified
ARM64 VM profile does not prove every Docker or cloud environment.
