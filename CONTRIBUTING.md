# Contributing

Read `AGENTS.md` and `docs/acceptance.md`. Keep the change within one bounded
capability and preserve standalone operation: downloaded portfolio components
must be pinned and verified, not imported from sibling directories.

Use Python 3.14.7 and the repository-local bootstrap:

```sh
make PYTHON=python3.14 bootstrap
make doctor
make validate
make demo
make security
```

Changes affecting Dockerfiles, Compose, migrations, dependencies, credentials,
the VM runner or lifecycle behavior also require the supported real profile:

```sh
make integration LAB=ops-container-platform-reference
```

This command creates and destroys disposable resources and their synthetic data.
Do not point it at a shared engine. Do not change the lab identifier, ownership
guards, SSH verification, sandboxing or security controls to get a passing run.
An unsupported environment is a visible limitation, not a passing integration.

Test observable contracts: concurrent key reuse, HTTP rejection, SQL leases,
outage behavior, safe path handling and cleanup. A test that repeats an
implementation constant without testing behavior provides little confidence.
Keep fixture tests distinct from PostgreSQL/Valkey/container integration.

Add a numbered migration for schema changes. Never edit an already applied SQL
file or remove its checksum record to bypass drift detection. Explain an upgrade
and data-recovery path before claiming compatibility with existing data. Keep
seeds synthetic and repeatable through the application contract.

Update locks only from verified official metadata; preserve third-party license
notices. Document why the selected version remains supported and what advisory
review covers. Do not silently drop hashes, loosen pins or disable certificate
verification to resolve download failures.

For review, state the trigger, resulting behavior, tests run, tested revision
and limitations. Include actual exit codes and failure/cleanup results. Redact
private paths or host identifiers when appropriate without changing assertions.
Do not add generated disks, runtime secrets, package caches, or unreviewed logs.
Run a fresh clone to detect hidden local dependencies. Follow the release gate
and inspect exact-revision CI before making a release claim.

Use your existing Git identity and commits describing work actually performed.
No artificial history, production-experience claims or decorative success badges.
