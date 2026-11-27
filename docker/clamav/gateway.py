"""Private scan gateway: no timer, no startup downloads, no document persistence.

All scans share one lock covering update, database loading and INSTREAM. A scan
arriving during an update shares that successful update rather than starting a
second one. Sequential scans each check for updates (FreshClam honors CDN cooldowns).
"""

import json
import logging
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_BYTES = 25 * 1024 * 1024
SCAN_TIMEOUT = int(os.getenv("CLAMAV_TIMEOUT", "60"))
if not 1 <= SCAN_TIMEOUT <= 60:
    raise ValueError("CLAMAV_TIMEOUT must be between 1 and 60 seconds")
DATABASE = Path("/var/lib/clamav")


def command(name, data=None):
    deadline = time.monotonic() + SCAN_TIMEOUT
    with socket.create_connection(("127.0.0.1", 3310), timeout=5) as sock:
        sock.sendall(b"z" + name.encode("ascii") + b"\0")
        if data is not None:
            for offset in range(0, len(data), 65536):
                chunk = data[offset : offset + 65536]
                sock.settimeout(max(0.001, deadline - time.monotonic()))
                sock.sendall(struct.pack("!I", len(chunk)) + chunk)
            sock.sendall(struct.pack("!I", 0))
        answer = bytearray()
        while len(answer) < 4096:
            sock.settimeout(max(0.001, deadline - time.monotonic()))
            chunk = sock.recv(4096 - len(answer))
            if not chunk:
                break
            answer.extend(chunk)
            if b"\0" in answer:
                if answer.count(b"\0") != 1 or not answer.endswith(b"\0"):
                    raise ValueError("Ambiguous clamd reply")
                return answer[:-1].decode("ascii")
        raise ValueError("Incomplete clamd reply")


def database_state():
    return tuple(
        sorted(
            (p.name, p.stat().st_size, p.stat().st_mtime_ns)
            for p in DATABASE.iterdir()
            if p.suffix in {".cvd", ".cld"}
        )
    )


class Scanner:
    def __init__(self):
        self.lock = threading.Lock()
        self.updated_at = 0
        self.loaded_state = None
        self.process = None

    def stop(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            self.process = None

    def update(self):
        # One-shot mode only. Never launch freshclam --daemon.
        subprocess.run(
            ["freshclam", "--config-file=/etc/clamav/freshclam.conf", "--stdout"], check=True, timeout=120
        )

    def load(self):
        state = database_state()
        if self.process is None or self.process.poll() is not None or state != self.loaded_state:
            # No active INSTREAM can be interrupted: the caller owns the scan lock.
            self.stop()
            self.process = subprocess.Popen(
                ["clamd", "--foreground=true", "--config-file=/etc/clamav/clamd.conf"]
            )
            deadline = time.monotonic() + 45
            while True:
                if self.process.poll() is not None:
                    raise RuntimeError("clamd exited during database loading")
                try:
                    if command("PING") == "PONG":
                        break
                except (OSError, ValueError):
                    pass
                if time.monotonic() >= deadline:
                    self.stop()
                    raise TimeoutError("clamd database loading timed out")
                time.sleep(0.2)
            self.loaded_state = state

    def scan(self, data):
        arrived = time.monotonic()
        if not self.lock.acquire(timeout=240):
            raise TimeoutError("Scanner busy")
        try:
            if self.updated_at < arrived:
                self.update()  # Any failure prevents INSTREAM, even with cached signatures.
                self.load()
                self.updated_at = time.monotonic()
            else:
                self.load()
            before = command("VERSION")
            answer = command("INSTREAM", data)
            after = command("VERSION")
            return {"before": before, "answer": answer, "after": after}
        finally:
            self.lock.release()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # No request bodies, names or scanner responses in access logs.

    def respond(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        # Idle databases may legitimately be old; health probes never trigger updates.
        self.respond(200 if self.path == "/health" else 404, {"status": "ready"})

    def do_POST(self):
        self.connection.settimeout(30)
        try:
            size = int(self.headers.get("Content-Length", "-1"))
            if self.path != "/scan" or not 0 <= size <= MAX_BYTES:
                self.respond(400, {"error": "Invalid scan request"})
                return
            data = self.rfile.read(size)
            if len(data) != size:
                raise ValueError("Incomplete scan request")
            self.respond(200, self.server.scanner.scan(data))
        except Exception as exc:
            # Exception messages (e.g. decoder errors) can contain scanner input.
            # FreshClam already prints its own credential-free update diagnostics.
            logging.error("On-demand update/scan failed (%s)", type(exc).__name__)
            self.respond(503, {"error": "Signature update or scan failed"})


if __name__ == "__main__":
    # Root prepares the persistent volume; both HTTP gateway and its children then
    # run as clamav. The upstream /init is intentionally not invoked.
    import pwd

    user = pwd.getpwnam("clamav")
    DATABASE.mkdir(parents=True, exist_ok=True)
    os.chown(DATABASE, user.pw_uid, user.pw_gid)
    runtime = Path("/run/clamav")
    runtime.mkdir(parents=True, exist_ok=True)
    os.chown(runtime, user.pw_uid, user.pw_gid)
    os.setgroups([])
    os.setgid(user.pw_gid)
    os.setuid(user.pw_uid)
    server = ThreadingHTTPServer(("0.0.0.0", 3311), Handler)
    server.scanner = Scanner()

    def shutdown(signum, frame):
        server.scanner.stop()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, shutdown)
    try:
        server.serve_forever()
    finally:
        server.scanner.stop()
