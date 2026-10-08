# ADR 001: keep durable acceptance and job state in PostgreSQL

Status: accepted for the bounded local reference workload.

## Context

A small asynchronous application needs to distinguish accepting work from
finishing it. A dependency outage must not produce a success response for work
that disappears. Running PostgreSQL plus a cache is already part of the project;
adding a broker would increase services, persistence modes and failure cases.

## Decision

Store input, idempotency key, attempts, lease and result in one SQL row. Commit
acceptance before returning `202`. Claim work with `FOR UPDATE SKIP LOCKED` and
complete it with a token/expiry predicate. Use Valkey only for immutable successful
results with a short TTL. Keep the worker operation deterministic and bounded.

The application uses parameterized SQL and a unique key to coordinate concurrent
retries. Migrations establish constraints; they are not left to handler-level
validation alone. Cache errors cannot change durable acceptance or completion.

## Consequences

One transaction boundary makes a lost API response recoverable through a retry
with the same key. Stopping the worker leaves queued rows intact. A stale worker
can recompute but cannot complete after losing its lease. The real integration
profile must test SQL fencing, queue recovery, repeat keys and persistence; mocks
alone do not establish these properties.

The database is also the queue's availability and scaling bottleneck. Polling
adds queries; expired leases delay crash recovery by up to the configured lease
period plus polling. Idempotency keys and text have no retention policy yet.
Three attempts are a lab policy, not evidence that every failure is transient.
There is no transactional outbox, broker fanout, scheduler, priority queue or
exactly-once external side effect. Introducing those requirements requires a
separate design and tests rather than stretching this demonstration's claims.

## Alternatives considered

A Valkey queue would couple cache persistence and delivery correctness and would
need acknowledgment/recovery semantics. A dedicated broker can support richer
delivery contracts but adds a second durable subsystem. Both can be appropriate
at a different scale; neither is implemented or claimed here.
