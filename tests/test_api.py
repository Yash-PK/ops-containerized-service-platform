"""Real loopback HTTP parsing with a controlled repository; not PostgreSQL proof."""

import contextlib
import http.client
import io
import json
import socket
import threading
import time
import unittest
import uuid

import psycopg

from opsjobs.api import Server
from opsjobs.domain import Conflict


class FakeRepository:
    def __init__(self):
        self.jobs = {}
        self.available = True

    def ready(self):
        if not self.available:
            raise psycopg.OperationalError("synthetic database unavailable")
        return True

    def enqueue(self, text, key):
        self.ready()
        if key in self.jobs:
            old_text, value = self.jobs[key]
            if old_text != text:
                raise Conflict("synthetic conflict")
            return value, False
        value = {"id": str(uuid.uuid4()), "status": "queued", "result": None}
        self.jobs[key] = (text, value)
        return value, True

    def get(self, identifier):
        self.ready()
        return next((v for _, v in self.jobs.values() if v["id"] == identifier), None)


class FakeCache:
    def get(self, _identifier):
        return None

    def put(self, _value):
        pass


class APITests(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        redirect = contextlib.redirect_stdout(self.output)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)
        self.repository = FakeRepository()
        self.server = Server(("127.0.0.1", 0), self.repository, FakeCache())
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.01}
        )
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.assertFalse(self.thread.is_alive())

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection(*self.server.server_address, timeout=2)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            reply = conn.getresponse()
            return reply.status, json.loads(reply.read()), dict(reply.getheaders())
        finally:
            conn.close()

    def submit(self, text="synthetic text", key="test-key-001"):
        return self.request(
            "POST",
            "/jobs",
            json.dumps({"text": text}),
            {"Content-Type": "application/json", "Idempotency-Key": key},
        )

    def test_async_acceptance_replay_conflict_and_lookup(self):
        status, job, headers = self.submit()
        self.assertEqual(status, 202)
        self.assertEqual(job["status"], "queued")
        self.assertIsNone(job["result"])
        self.assertIn("X-Request-ID", headers)
        status, replay, _ = self.submit()
        self.assertEqual(status, 200)
        self.assertEqual(replay["id"], job["id"])
        self.assertEqual(self.submit("different content")[0], 409)
        self.assertEqual(self.request("GET", "/jobs/" + job["id"])[1], job)
        self.assertEqual(len(self.repository.jobs), 1)

    def test_invalid_body_headers_and_unknown_job_do_not_enqueue(self):
        headers = {"Content-Type": "application/json", "Idempotency-Key": "test-key-001"}
        for data in ("{", '{"text":"a","text":"b"}', '{"text": ""}', '{"text": 2}'):
            self.assertEqual(self.request("POST", "/jobs", data, headers)[0], 400)
        self.assertEqual(
            self.request("POST", "/jobs", "{}", {"Content-Type": "text/plain"})[0], 415
        )
        self.assertEqual(self.request("POST", "/jobs", "x" * 16385, headers)[0], 413)
        self.assertEqual(self.request("GET", "/jobs/invalid")[0], 400)
        self.assertEqual(self.request("GET", "/jobs/" + str(uuid.uuid4()))[0], 404)
        self.assertFalse(self.repository.jobs)

    def test_dependency_outage_is_bounded_503_but_liveness_survives(self):
        self.repository.available = False
        self.assertEqual(self.submit()[0], 503)
        self.assertEqual(self.request("GET", "/health/ready")[0], 503)
        self.assertEqual(self.request("GET", "/health/live")[0], 200)
        self.repository.available = True
        self.assertEqual(self.submit()[0], 202)

    def test_operational_logs_exclude_payload_and_idempotency_key(self):
        self.submit("synthetic-sensitive-payload", "sensitive-key-0001")
        self.doCleanups()
        self.assertNotIn("synthetic-sensitive-payload", self.output.getvalue())
        self.assertNotIn("sensitive-key-0001", self.output.getvalue())
        for line in self.output.getvalue().splitlines():
            self.assertEqual(json.loads(line)["event"], "request")

    def test_deep_bounded_json_is_rejected_without_enqueuing(self):
        body = '{"text":' + "[" * 1500 + "0" + "]" * 1500 + "}"
        self.assertLess(len(body), 16384)
        status, value, _ = self.request(
            "POST",
            "/jobs",
            body,
            {"Content-Type": "application/json", "Idempotency-Key": "test-deep-json"},
        )
        self.assertEqual((status, value), (400, {"error": "invalid_request"}))
        self.assertFalse(self.repository.jobs)

    def test_raw_ambiguous_framing_is_rejected(self):
        cases = (
            b"Content-Length: 2\r\nContent-Length: 2\r\n",
            b"Transfer-Encoding: chunked\r\nContent-Length: 2\r\n",
            b"Content-Length: 2\r\nIdempotency-Key: duplicate-key\r\n",
        )
        for framing in cases:
            with (
                self.subTest(framing=framing),
                socket.create_connection(self.server.server_address, timeout=1) as client,
            ):
                client.sendall(
                    b"POST /jobs HTTP/1.1\r\nHost: localhost\r\n"
                    b"Content-Type: application/json\r\nIdempotency-Key: test-key-001\r\n"
                    + framing
                    + b"\r\n{}"
                )
                self.assertTrue(client.recv(1024).startswith(b"HTTP/1.0 400 "))
        self.assertFalse(self.repository.jobs)

    def drip(self, client):
        stop = threading.Event()

        def send():
            while not stop.wait(0.02):
                try:
                    client.sendall(b" ")
                except OSError:
                    return

        thread = threading.Thread(target=send)
        thread.start()
        return stop, thread

    def test_absolute_deadline_closes_dripped_headers_and_body(self):
        self.server.request_timeout = 0.15
        for prefix in (
            b"POST /jobs HTTP/1.1\r\nHost: localhost\r\nX-Lab: ",
            b"POST /jobs HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\n"
            b"Idempotency-Key: test-key-001\r\nContent-Length: 1000\r\n\r\n{",
        ):
            with (
                self.subTest(prefix=prefix),
                socket.create_connection(self.server.server_address, timeout=2) as client,
            ):
                started = time.monotonic()
                client.sendall(prefix)
                stop, thread = self.drip(client)
                try:
                    self.assertEqual(client.recv(1024), b"")
                    self.assertLess(time.monotonic() - started, 1)
                finally:
                    stop.set()
                    thread.join(timeout=1)
                    self.assertFalse(thread.is_alive())
        self.assertFalse(self.repository.jobs)

    def test_shutdown_interrupts_incomplete_request_without_waiting_for_deadline(self):
        with socket.create_connection(self.server.server_address, timeout=1) as client:
            client.sendall(b"POST /jobs HTTP/1.1\r\nHost: localhost\r\nX-Lab: ")
            limit = time.monotonic() + 1
            while not self.server.connections and time.monotonic() < limit:
                time.sleep(0.005)
            self.assertTrue(self.server.connections)
            started = time.monotonic()
            self.stop()
            self.assertLess(time.monotonic() - started, 1)
            self.assertEqual(client.recv(1024), b"")
