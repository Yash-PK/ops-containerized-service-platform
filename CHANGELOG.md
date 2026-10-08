# Changelog

## 0.1.0 — 2026-10-08

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
  evidence; release creation requires exact-target CI.
- Pass formal controller (71 tests), standalone clean-clone and real ARM64
  Compose lifecycle gates at `3d58b9f7107fa1c7de3eec06b32c9b6f6ce644d6`, including
  139 commands, 94 preparation/lifecycle assertions, 21 nested SQL assertions and
  owned cleanup. Preserve four development failures and the earlier formal SSH
  transfer failure. Linux controller CI passed at the first public revision
  `19ec88d5d4a6aa7541e7722b994618c3a6929cc5`; final release-target CI is checked
  separately before creating the tag.
