"""Small bounded HTTP/JSON API, intended for the private reference lab only."""

import json
import signal
import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import psycopg

from opsjobs.cache import ResultCache
from opsjobs.config import Config
from opsjobs.database import Repository
from opsjobs.domain import Conflict, InvalidInput, idempotency_key, job_id, payload


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidInput("Duplicate JSON field")
        result[key] = value
    return result


class Server(ThreadingHTTPServer):
    daemon_threads = False
    request_queue_size = 16
    allow_reuse_address = True

    def __init__(self, address, repository, cache, *, request_timeout=5.0):
        if not 0 < request_timeout <= 10:
            raise ValueError("Request deadline must be positive and at most 10 seconds")
        self.repository = repository
        self.cache = cache
        self.capacity = threading.BoundedSemaphore(16)
        self.request_timeout = request_timeout
        self.connections = {}
        self.connections_lock = threading.Lock()
        super().__init__(address, Handler)

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(4)
        return request, address

    def process_request(self, request, address):
        if not self.capacity.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n")
            finally:
                self.shutdown_request(request)
            return
        try:
            with self.connections_lock:
                self.connections[request] = time.monotonic() + self.request_timeout
            super().process_request(request, address)
        except BaseException:
            self.capacity.release()
            raise

    @staticmethod
    def interrupt(request):
        try:
            request.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass  # A completing request may have already closed its socket.

    def service_actions(self):
        # A socket timeout resets between reads. An absolute acceptance deadline
        # also bounds clients which drip headers/body just before that timeout.
        now = time.monotonic()
        with self.connections_lock:
            expired = [request for request, deadline in self.connections.items() if deadline <= now]
        for request in expired:
            self.interrupt(request)

    def shutdown_request(self, request):
        try:
            super().shutdown_request(request)
        finally:
            with self.connections_lock:
                self.connections.pop(request, None)

    def server_close(self):
        # Drain database operations under their configured connect/statement
        # timeouts, but do not wait for a client to finish an incomplete request.
        with self.connections_lock:
            active = list(self.connections)
        for request in active:
            self.interrupt(request)
        super().server_close()

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.capacity.release()

    def handle_error(self, request, client_address):
        # Neither traceback locals nor request bodies enter operational logs.
        print(json.dumps({"event": "request_interrupted"}), flush=True)


class Handler(BaseHTTPRequestHandler):
    server_version = "OpsJobs/0.1"
    sys_version = ""
    protocol_version = "HTTP/1.0"

    def log_message(self, *_args):
        pass

    def reply(self, code, value, *, cache="none"):
        data = json.dumps(value, ensure_ascii=True, allow_nan=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Request-ID", self.request_id)
        self.send_header("X-Result-Cache", cache)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)
        self.close_connection = True

    def dispatch(self):
        self.request_id = str(uuid.uuid4())
        started = time.monotonic()
        status, route = 500, "unknown"
        try:
            target = urlsplit(self.path)
            if target.query or target.fragment or target.scheme or target.netloc:
                raise InvalidInput("Queries and absolute URLs are not supported")
            if self.headers.get("Transfer-Encoding") is not None:
                raise InvalidInput("Transfer-Encoding is not supported")
            if self.command == "GET" and target.path == "/health/live":
                status, route = 200, "health.live"
                self.reply(status, {"status": "alive"})
            elif self.command == "GET" and target.path == "/health/ready":
                route = "health.ready"
                status = 200 if self.server.repository.ready() else 503
                self.reply(status, {"status": "ready" if status == 200 else "unavailable"})
            elif self.command == "POST" and target.path == "/jobs":
                route = "jobs.create"
                lengths = self.headers.get_all("Content-Length", [])
                if len(lengths) != 1 or not lengths[0].isdigit():
                    raise InvalidInput("Exactly one numeric Content-Length is required")
                length = int(lengths[0])
                if not 1 <= length <= 16384:
                    status = 413
                    self.reply(status, {"error": "body_too_large"})
                    return
                if self.headers.get_content_type() != "application/json":
                    status = 415
                    self.reply(status, {"error": "application_json_required"})
                    return
                keys = self.headers.get_all("Idempotency-Key", [])
                if len(keys) != 1:
                    raise InvalidInput("Exactly one Idempotency-Key is required")
                key = idempotency_key(keys[0])
                body = self.rfile.read(length)
                if len(body) != length:
                    raise InvalidInput("Incomplete body")
                text = payload(json.loads(body.decode("utf-8"), object_pairs_hook=unique_object))
                job, created = self.server.repository.enqueue(text, key)
                status = 202 if created else 200
                self.reply(status, job)
            elif self.command == "GET" and target.path.startswith("/jobs/"):
                route = "jobs.get"
                identifier = job_id(target.path.removeprefix("/jobs/"))
                value = self.server.cache.get(identifier)
                source = "hit" if value is not None else "miss"
                if value is None:
                    value = self.server.repository.get(identifier)
                    if value is not None:
                        self.server.cache.put(value)
                status = 404 if value is None else 200
                self.reply(status, {"error": "not_found"} if value is None else value, cache=source)
            else:
                status = 404
                self.reply(status, {"error": "not_found"})
        except Conflict:
            status = 409
            self.reply(status, {"error": "idempotency_conflict"})
        except InvalidInput, UnicodeError, json.JSONDecodeError, ValueError, RecursionError:
            status = 400
            self.reply(status, {"error": "invalid_request"})
        except psycopg.Error:
            status = 503
            self.reply(status, {"error": "database_unavailable"})
        except TimeoutError:
            status = 408
            self.reply(status, {"error": "request_timeout"})
        finally:
            print(
                json.dumps(
                    {
                        "event": "request",
                        "route": route,
                        "status": status,
                        "request_id": self.request_id,
                        "duration_ms": round((time.monotonic() - started) * 1000, 3),
                    }
                ),
                flush=True,
            )

    do_GET = dispatch
    do_POST = dispatch


def main():
    config = Config.from_env()
    server = Server(("0.0.0.0", 8000), Repository(config), ResultCache(config))
    for number in (signal.SIGTERM, signal.SIGINT):
        signal.signal(
            number,
            lambda _signum, _frame: threading.Thread(target=server.shutdown, daemon=True).start(),
        )
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
    print(json.dumps({"event": "api_stopped"}), flush=True)


if __name__ == "__main__":
    main()
