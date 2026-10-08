# Security model

This service processes synthetic data in one disposable, locally owned lab. It
has no user authentication or tenant boundary and must not be exposed publicly.
HTTP is bound to guest loopback. Application/data traffic uses internal Compose
networks; only the proxy also joins a normal `edge` bridge for port publishing.
Network isolation is not transport encryption.

## Threat assumptions and controls

The controller account, hypervisor, guest administrator, image publishers and
checked-in source are trusted. A rootful Docker daemon operates only inside the
owned VM. Access to its socket is equivalent to guest administration. No socket
is mounted into an application container or exposed over TCP, and no existing
host Docker context is adopted.

The `edge` bridge permits outbound traffic from nginx; this profile is not a
complete egress-denial policy. Only the proxy joins it, and the single published
port has the explicit guest-local mapping `127.0.0.1:8080:8080`. `frontend` and
`backend` remain internal; database and cache ports are unpublished. The VM
forwards no application port to macOS. A bridge's membership and a published
port's bind address are distinct controls, as described in
[Docker's networking documentation](https://docs.docker.com/engine/network/port-publishing/).
Compromised guest root or proxy code remains outside the isolation guarantees of
this trusted local reference lab.

The API treats text, keys, IDs, JSON and HTTP framing as untrusted input. It
limits text to 4096 UTF-8 bytes, caps HTTP bodies and concurrent request threads,
uses finite I/O timeouts, rejects invalid identifiers and parameterizes SQL.
The workload does not execute submitted programs, shell commands, files or URLs.
Input validation does not make this HTTP implementation a general-purpose
internet service. The Python server's absolute deadline applies to its own
accepted sockets. nginx buffers request bodies and its client-body timeout is an
inactivity timeout, so this is not an end-to-end five-second slow-client
guarantee. Internet-facing denial-of-service protection and authentication would
require a separately designed and tested deployment.

The application role cannot create roles/databases or act as a superuser. The
migration has separate administrative access. Capabilities, root-filesystem
writes, PIDs, memory and CPU are constrained for application services; PostgreSQL
retains the initialization behavior its official image requires. The runtime
checks process identities and effective settings instead of inferring isolation
from configuration alone. AppArmor remains enabled; no unconfined workaround is
part of the supported profile.

## Credentials, input and logs

The run generates separate owner, application and cache passwords from 24 random
bytes each. There are no reusable sample passwords. `scripts/credentials.py`
refuses an existing secret directory so that a retry cannot silently rotate
credentials while retaining a database volume.

Compose file-backed secrets preserve source permissions. Credential files are
mode `0444` so different unprivileged container UIDs can read their specific
mounts, while their guest-local parent directories are owned and mode `0700`.
This is not permission to publish those files: a guest administrator can read
them, and Compose local secrets are not an encrypted secret store. Passwords
reach application code through files. The Valkey health client briefly receives
its authentication value through its process environment inside the container;
privileged guest/container introspection remains trusted.

Text and results persist in PostgreSQL until the confirmed lab teardown removes
the owned volume. Successful results may reside in Valkey for 60 seconds. Use
only synthetic input. Application logs omit submitted bodies, idempotency keys
and credentials; private controller/guest command logs still require review
before sharing. Never upload `.runtime`, `.env`, private keys, database volumes,
VM disks or backup archives.

## Dependency and publication policy

Locks pin image digests, Python wheel hashes, developer tools, guest packages,
engine assets and the released VM provider. Review official support/release and
advisory information before updating them. A digest fixes content; it does not
prove the content has no vulnerabilities. Selected advisory review is documented
in [dependencies](docs/dependencies.md); a complete base-image/transitive-library
vulnerability audit is not claimed.

Required local gates include working-file, staged-file and full outgoing-history
secret scans. Review the exact outgoing diff and evidence manually as well.
GitHub validation uses read-only permissions and pinned actions; untrusted pull
requests must never gain secrets, privileged runners or a publishing context.
No container registry publishing or cloud deployment is authorized by this lab.

## Known limitations and reporting

There is no TLS, authentication, multi-tenancy, secret rotation protocol,
database backup, host-compromise defense or cryptographic authentication of
cached results. No production or compliance certification is implied. General
hardening, supply-chain signing and scanner integrations require distinct
implementation and evidence before being described as controls.

Report a potential vulnerability through GitHub private vulnerability reporting
when it is enabled on the published repository. If no private channel is
available, open an issue requesting one without exploit details, credentials or
private logs. Include the affected revision, synthetic reproduction and expected
boundary. Never paste a token or password into an issue. There is no guaranteed
response SLA or supported production deployment.
