"""Small health probes with explicit deadlines and no shell interpolation."""

import http.client
import sys
import time

from opsjobs.worker import HEARTBEAT


def main(profile):
    if profile == "worker":
        return 0 if 0 <= time.monotonic() - float(HEARTBEAT.read_text()) < 15 else 1
    if profile != "api":
        return 2
    connection = http.client.HTTPConnection("127.0.0.1", 8000, timeout=2)
    try:
        connection.request("GET", "/health/ready")
        return 0 if connection.getresponse().status == 200 else 1
    finally:
        connection.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1]))
    except OSError, ValueError, IndexError, http.client.HTTPException:
        raise SystemExit(1) from None
