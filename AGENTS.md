# Container platform continuation

This is the sole active engineering project after completed network/storage v0.1.0.
Read docs/acceptance.md before implementation. Keep sibling repositories separate.
Build original lab/reference work, not production/experience claims. Use the existing
Git identity. No host changes, global packages, paid services, cloud resources,
container-package publishing, arbitrary Docker targets or unrelated cleanup.

Architecture: one synthetic asynchronous jobs contract shared by later projects.
Python API/worker, PostgreSQL durable state/migrations, one compatible Valkey cache,
and a reverse proxy. Docker Compose is primary; Podman is a separately tested extension.
Select/pin dependencies from official release/support/advisory information first.
An optional project-owned VZ guest can host the real container engine; never start
or adopt the existing default Colima context. Containers are not VMs or cloud proof.

Use bounded subprocess argv, explicit project/engine ownership, loopback-only host
bindings, runtime credentials in ignored private paths, synthetic data, negative
checks and inventory-scoped cleanup. No blanket prune, force push or secret logs.
Required gates include implementation tests, lint, real Compose lifecycle/outage/
persistence assertions, clean-clone quickstart, exact outgoing review and working/
staged/full-history secret scans. Default demo must not mutate unrelated resources.
Record revision, environment, versions, results and cleanup; skips are never passes.
Only create the new authorized public Yash-PK/ops-containerized-service-platform
repository after local gates. Verify exact-head CI before release. Update the hub
and save accurate continuation state; do not regenerate completed projects.
