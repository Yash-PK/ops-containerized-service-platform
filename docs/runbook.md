# Local operations runbook

The supported workload exists only during the integration run. All requests and
faults target its owned guest. There is no continuously operated public service,
remote production environment or host-level Docker administration procedure here.

## Before a run

Run the README bootstrap, doctor and controller validation commands. Check
available memory/disk and ensure no previous lab inventory is unresolved.
`make integration LAB=ops-container-platform-reference` explicitly permits this
lab's creation, bounded service stops and synthetic-data deletion. The direct
runner's dry-run mode is the place to inspect a planned action before executing
it. Retain the exact source revision and locks when comparing failures.

## Diagnose from the failing assertion

| Observation | Likely boundary | Next inspection and expected recovery |
| --- | --- | --- |
| Bootstrap rejects a hash or download | Dependency acquisition | Check official availability and the lock; preserve the mismatch and review an explicit update. Never bypass verification. |
| VM creation/SSH verification fails | VZ/provider | Check supported architecture and owned inventory. Preserve host-key checks; do not adopt a different instance. |
| Package/kernel assertion fails | Guest preparation | Compare package lock, signed APT result and cold-boot kernel. Do not continue with an unverified kernel. |
| Migration exits nonzero | Schema or database startup | Inspect its private log and checksum error. Restore matching source or add a new migration; never rewrite applied checksums. |
| API returns `400`, `409`, `413` or `415` | Request contract | Check body shape/encoding, size, content type and key reuse. Retry unchanged text with the original key after an uncertain response. |
| Job stays `queued` while the worker is stopped | Expected durable backlog | Start the owned worker in the scenario and poll for a real result. Acceptance does not imply completion. |
| Job remains `running` after a crash | Lease recovery | Allow its 30-second lease to expire. Verify a new claim token; do not manually force success. Three failed attempts end as `failed`. |
| Cache is stopped but GET still works | Expected SQL fallback | Check SQL-backed response equality, restart only the cache, and verify health. This is not proof that writes survive database failure. |
| POST returns `503`; live `200`, ready `503` | Database unavailable | Restore the owned database; readiness and queued-job completion must recover. A cached result can still return `200`. |
| Proxy process healthy but requests fail | API/DNS/upstream | Inspect API readiness and proxy error log. A PID check alone does not establish end-to-end health. |
| Container killed or exit `137` | Memory/PID/resource pressure | Record limits, exit state and actual pressure. Adjust a reviewed bounded profile; do not remove all limits. |
| Cleanup reports an unexpected object | Ownership conflict | Keep the inventory and stop. Inspect the exact object/engine labels before an explicitly scoped cleanup. |

Application request logs include `request_id`, route, status and duration. Worker
logs include job IDs and completion/lease/database events. Correlate these with
the integration assertion names; no raw text is needed to diagnose this workload.
Runtime logs can include administrative output, so share a reviewed extract rather
than the whole `.runtime` directory.

## Failure and recovery sequence

The scenario first accepts a job without a worker and proves it remains queued.
It starts the worker and checks a computed digest. It then restarts persistent
services, stops/restarts the cache, queues another job, stops PostgreSQL, and
asserts bounded failure and readiness semantics. After restoring PostgreSQL it
restarts the application and verifies the accepted job finishes. Migration/seed
repeats, SQL assertions and runtime isolation checks complete the profile.

This demonstrates recovery from service/process interruption while retaining the
same data volume. It does not simulate loss of that volume or establish backup,
point-in-time recovery, database failover, an RTO or an RPO.

## Teardown and interrupted runs

The normal finalizer inventories the engine/project and deletes only the owned
Compose containers, network resources and data volume, then stops its engine.
The controller then deletes its owned VM. A failed assertion is preserved even
when cleanup succeeds; a cleanup error also prevents success.

If the controller itself is interrupted, inspect its retained inventory and the
runner's teardown dry-run before executing cleanup for the exact lab ID:

```sh
make teardown-plan LAB=ops-container-platform-reference
make teardown LAB=ops-container-platform-reference CONFIRM=ops-container-platform-reference
```

The direct equivalent defaults to dry-run without `--execute` and requires an
explicit matching confirmation to mutate resources:

```sh
.venv/bin/python scripts/lab.py teardown --lab-id ops-container-platform-reference
```

Never
delete the inventory first: it is the evidence used to distinguish owned
resources. Do not use `docker system prune`, wildcard container deletion,
unscoped `limactl delete`, or a recursive removal of unrelated runtime paths.

`make clean` prints the teardown plan; it does not delete resources or caches.
Pinned download caches may remain for reuse. Synthetic database data is
intentionally disposable; copying it out and calling the copy a verified backup
would exceed this project's evidence.
