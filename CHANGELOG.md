# Changelog

## Unreleased

- Implement a bounded HTTP API and separate text-analysis worker with durable
  PostgreSQL acceptance, idempotent submission, lease fencing and bounded retries.
- Add checked SQL migrations, repeatable synthetic seeds and terminal-result
  caching with Valkey fallback behavior.
- Define digest-pinned, resource-constrained Docker Compose services with a
  multi-stage Python image, separate credentials and a guest-loopback nginx proxy.
- Add controller/unit tests and a guarded disposable VM integration profile for
  service failure, persistence, recovery and ownership-scoped cleanup.
- Document architecture, dependency selection, operational boundaries and
  validation requirements. Integration and publication status follow actual
  evidence; this entry does not declare a released version.
