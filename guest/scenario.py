"""Real containers: durable asynchronous jobs, outages, identities and scoped cleanup."""

import hashlib
import http.client
import json
import platform
import time
import uuid

from guest import engine
from guest.common import LAB_ID, ROOT, LabError
from scripts.credentials import generate

TEXT = "Synthetic portfolio job\nrecoverable durable work"


def request(method, path, payload=None, key=None, *, headers_out=None):
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Idempotency-Key"] = key
    connection = http.client.HTTPConnection("127.0.0.1", 8080, timeout=12)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        content = response.read(20000)
        if headers_out is not None:
            headers_out.update({key.lower(): value for key, value in response.getheaders()})
        return response.status, json.loads(content)
    finally:
        connection.close()


def wait_job(ctx, job_id, label):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status, job = request("GET", "/jobs/" + job_id)
        if status == 200 and job["status"] == "succeeded":
            ctx.check(label, job["result"]["sha256"] == hashlib.sha256(TEXT.encode()).hexdigest())
            return job
        if status != 200 or job.get("status") == "failed":
            raise LabError("Unexpected job polling result")
        time.sleep(0.2)
    raise LabError("Job completion deadline exceeded")


def container(ctx, service):
    ids = ctx.compose(["ps", "--all", "--quiet", service], label="id-" + service).split()
    if len(ids) != 1:
        raise LabError("Expected exactly one service container")
    return json.loads(ctx.docker(["inspect", ids[0]], label="inspect-" + service))[0]


def wait_health(ctx, service):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        info = container(ctx, service)
        if info["State"].get("Health", {}).get("Status") == "healthy":
            return
        time.sleep(1)
    raise LabError("Service health deadline: " + service)


def inventory(ctx, *, require_volume=True):
    engine.owned(ctx)
    ids = ctx.docker(["ps", "-aq"], label="inventory-containers").split()
    records = json.loads(ctx.docker(["inspect", *ids], label="inventory-details")) if ids else []
    expected = {"database", "cache", "migrate", "api", "worker", "proxy", "seed"}
    for item in records:
        labels = item["Config"].get("Labels", {})
        if (
            labels.get("com.docker.compose.project") != LAB_ID
            or labels.get("com.docker.compose.service") not in expected
        ):
            raise LabError("Unexpected container on owned engine; refusing cleanup")
    names = ctx.docker(
        ["volume", "ls", "--format", "{{.Name}}"], label="inventory-volume-names"
    ).split()
    present = LAB_ID + "_database" in names
    if require_volume and not present:
        raise LabError("Required database volume is absent")
    if present:
        volumes = json.loads(
            ctx.docker(["volume", "inspect", LAB_ID + "_database"], label="inventory-volume")
        )
        if volumes[0].get("Labels", {}).get("io.ops.lab") != LAB_ID:
            raise LabError("Database volume ownership mismatch")
    networks = ctx.docker(
        ["network", "ls", "--format", "{{.Name}}"], label="inventory-network-names"
    ).split()
    for name in (LAB_ID + "_frontend", LAB_ID + "_backend"):
        if name in networks:
            value = json.loads(ctx.docker(["network", "inspect", name], label="inventory-network"))[
                0
            ]
            if value.get("Labels", {}).get("com.docker.compose.project") != LAB_ID:
                raise LabError("Network ownership mismatch")
    result = {
        "lab_id": LAB_ID,
        "containers": [x["Id"] for x in records],
        "volume": LAB_ID + "_database",
    }
    (ROOT / "resources.json").write_text(json.dumps(result))
    return records


def execute(ctx):
    kernel = json.loads((ROOT / "packages.lock.json").read_text())["expected_kernel"]
    ctx.check("patched_kernel_booted", platform.release() == kernel)
    ctx.report["kernel"] = platform.release()
    generate(ROOT)
    engine.install(ctx)
    ctx.compose(["config", "--quiet"], label="compose-config")
    ctx.compose(["build", "--pull", "api"], label="app-build", timeout=900)
    ctx.compose(["pull", "database", "cache", "proxy"], label="service-pull", timeout=600)
    ctx.compose(
        ["up", "--detach", "--wait", "--wait-timeout", "120", "api", "proxy"],
        label="start-without-worker",
        timeout=180,
    )
    key = "demo_" + uuid.uuid4().hex
    status, job = request("POST", "/jobs", {"text": TEXT}, key)
    ctx.check("submit_accepted", status == 202 and job["status"] == "queued")
    job_id = job["id"]
    status, queued = request("GET", "/jobs/" + job_id)
    ctx.check("separate_worker_required", status == 200 and queued["status"] == "queued")
    status, replay = request("POST", "/jobs", {"text": TEXT}, key)
    ctx.check("idempotency_replay", status == 200 and replay["id"] == job_id)
    ctx.check(
        "idempotency_conflict", request("POST", "/jobs", {"text": "different"}, key)[0] == 409
    )
    ctx.check(
        "invalid_payload_rejected", request("POST", "/jobs", {"text": ""}, "invalid_key")[0] == 400
    )
    ctx.compose(
        ["up", "--detach", "--wait", "--wait-timeout", "60", "worker"],
        label="start-worker",
        timeout=120,
    )
    done = wait_job(ctx, job_id, "worker_actual_digest")
    headers = {}
    status, cached = request("GET", "/jobs/" + job_id, headers_out=headers)
    ctx.check(
        "completed_result_cache_hit",
        status == 200 and cached == done and headers.get("x-result-cache") == "hit",
    )
    ctx.compose(
        ["restart", "database", "api", "worker"], label="restart-persistent-services", timeout=120
    )
    for service in ("database", "api", "worker"):
        wait_health(ctx, service)
    status, restored = request("GET", "/jobs/" + job_id)
    ctx.check("data_survives_restart", status == 200 and restored == done)
    ctx.compose(["stop", "cache"], label="stop-cache")
    headers = {}
    status, fallback = request("GET", "/jobs/" + job_id, headers_out=headers)
    ctx.check(
        "cache_outage_sql_fallback",
        status == 200 and fallback == done and headers.get("x-result-cache") == "miss",
    )
    ctx.compose(["start", "cache"], label="recover-cache")
    wait_health(ctx, "cache")
    ctx.check("cache_recovered", request("GET", "/jobs/" + job_id)[1] == done)
    headers = {}
    request("GET", "/jobs/" + job_id, headers_out=headers)
    ctx.check("cache_recovery_hit", headers.get("x-result-cache") == "hit")
    ctx.compose(["stop", "worker"], label="stop-worker-for-durability")
    recovery_key = "recovery_" + uuid.uuid4().hex
    status, recovery = request("POST", "/jobs", {"text": TEXT}, recovery_key)
    ctx.check("durable_before_outage", status == 202 and recovery["status"] == "queued")
    ctx.compose(["stop", "database"], label="stop-database")
    started = time.monotonic()
    ctx.check(
        "database_outage_write_503",
        request("POST", "/jobs", {"text": TEXT}, "outage_" + uuid.uuid4().hex)[0] == 503,
    )
    ctx.check("database_outage_bounded", time.monotonic() - started < 8)
    ctx.check("live_during_database_outage", request("GET", "/health/live")[0] == 200)
    ctx.check("unready_during_database_outage", request("GET", "/health/ready")[0] == 503)
    ctx.compose(["start", "database"], label="recover-database")
    wait_health(ctx, "database")
    ctx.compose(["stop", "api"], label="graceful-api-stop")
    stopped = container(ctx, "api")
    ctx.check("api_sigterm_clean_exit", stopped["State"]["ExitCode"] == 0)
    ctx.compose(["start", "api", "worker"], label="recover-applications")
    wait_health(ctx, "api")
    wait_health(ctx, "worker")
    wait_job(ctx, recovery["id"], "accepted_job_survives_outage_and_shutdown")
    migrated = json.loads(
        ctx.compose(["run", "--rm", "--no-deps", "migrate"], label="migration-repeat")
    )
    ctx.check("migration_idempotent", migrated == {"migrations_applied": []})
    first = json.loads(ctx.compose(["run", "--rm", "--no-deps", "seed"], label="seed-first"))[
        "seed_jobs"
    ]
    second = json.loads(ctx.compose(["run", "--rm", "--no-deps", "seed"], label="seed-repeat"))[
        "seed_jobs"
    ]
    ctx.check(
        "seed_idempotent",
        [x["id"] for x in first] == [x["id"] for x in second]
        and all(not x["created"] for x in second),
    )
    sql = json.loads(
        ctx.compose(
            [
                "run",
                "--rm",
                "--no-deps",
                "migrate",
                "python",
                "-m",
                "opsjobs.sqlcheck",
                "--lab-id",
                LAB_ID,
                "--confirm",
                LAB_ID,
                "--execute",
            ],
            label="sql-integration",
            timeout=120,
        )
    )
    ctx.check("sql_integration", sql.get("passed") is True)
    ctx.report["sql_integration"] = sql
    records = inventory(ctx)
    for item in records:
        service = item["Config"]["Labels"]["com.docker.compose.service"]
        if service == "migrate":
            ctx.check("migration_success", item["State"]["ExitCode"] == 0)
            continue
        ctx.check(service + "_memory_limit", 0 < item["HostConfig"]["Memory"] <= 268435456)
        ctx.check(service + "_cpu_limit", 0 < item["HostConfig"]["NanoCpus"] <= 500000000)
        ctx.check(service + "_no_privileged", not item["HostConfig"]["Privileged"])
        ctx.check(service + "_apparmor", item["AppArmorProfile"] == "docker-default")
        ports = item["HostConfig"].get("PortBindings") or {}
        ctx.check(
            service + "_private_ports",
            ports
            == (
                {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8080"}]}
                if service == "proxy"
                else {}
            ),
        )
        top = ctx.docker(["top", item["Id"], "-eo", "uid,args"], label="processes-" + service)
        uids = [line.split()[0] for line in top.splitlines()[1:] if line.strip()]
        ctx.check(service + "_runtime_nonroot", bool(uids) and all(uid != "0" for uid in uids))
    for name in ("backend", "frontend"):
        net = json.loads(
            ctx.docker(["network", "inspect", LAB_ID + "_" + name], label="network-" + name)
        )[0]
        ctx.check(name + "_internal", net["Internal"] is True)
    ctx.report["workload"] = {
        "kind": "synthetic UTF-8 text analysis",
        "accepted_job_id": job_id,
        "result": done["result"],
    }
    ctx.report["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def cleanup(ctx):
    if not (ROOT / "engine-owner.json").exists():
        return
    engine.owned(ctx)
    inventory(ctx, require_volume=False)
    ctx.compose(
        ["down", "--volumes", "--remove-orphans", "--timeout", "20"],
        label="compose-owned-teardown",
        timeout=120,
    )
    ctx.check(
        "containers_removed", not ctx.docker(["ps", "-aq"], label="cleanup-containers").strip()
    )
    ctx.check(
        "database_volume_removed",
        LAB_ID + "_database"
        not in ctx.docker(
            ["volume", "ls", "--format", "{{.Name}}"], label="cleanup-volumes"
        ).split(),
    )
    ctx.run(["systemctl", "stop", "ops-container-platform-engine.service"], label="engine-stop")
