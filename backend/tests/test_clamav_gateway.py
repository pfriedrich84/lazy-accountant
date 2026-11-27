"""Exercise the real gateway lifecycle with controlled subprocess/clamd boundaries."""

import ast
import importlib.util
import json
import socket
import urllib.error
import urllib.request
from pathlib import Path
import subprocess
import threading
from unittest.mock import Mock, patch

import pytest

spec = importlib.util.spec_from_file_location(
    "clamav_gateway", Path(__file__).resolve().parents[2] / "docker/clamav/gateway.py"
)
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)


def test_gateway_is_compatible_with_alpine_python():
    ast.parse(Path(gateway.__file__).read_text(), feature_version=(3, 12))


def test_idle_does_not_update_or_start_clamd():
    with (
        patch.object(gateway.subprocess, "run") as update,
        patch.object(gateway.subprocess, "Popen") as start,
    ):
        scanner = gateway.Scanner()
        assert scanner.updated_at == 0
        update.assert_not_called()
        start.assert_not_called()


def test_update_then_load_then_scan_every_sequential_request():
    scanner = gateway.Scanner()
    events = []
    scanner.update = lambda: events.append("update")
    scanner.load = lambda: events.append("load")

    def command(name, data=None):
        events.append(name)
        return "stream: OK" if name == "INSTREAM" else "version"

    with patch.object(gateway, "command", side_effect=command):
        for _ in range(2):
            assert scanner.scan(b"example")["answer"] == "stream: OK"
    assert events == ["update", "load", "VERSION", "INSTREAM", "VERSION"] * 2


def test_failed_update_never_scans_and_releases_lock():
    scanner = gateway.Scanner()
    scanner.update = Mock(side_effect=subprocess.CalledProcessError(1, "freshclam"))
    with patch.object(gateway, "command") as command:
        with pytest.raises(subprocess.CalledProcessError):
            scanner.scan(b"example")
        command.assert_not_called()
    assert scanner.updated_at == 0
    assert scanner.lock.acquire(blocking=False)
    scanner.lock.release()


def test_overlapping_requests_share_update_but_not_scans():
    scanner = gateway.Scanner()
    updating = threading.Event()
    release = threading.Event()
    arrived = threading.Event()
    results = []

    def update():
        updating.set()
        assert release.wait(5)

    # Observe the second request reaching the lock, without scheduling sleeps.
    real_lock = scanner.lock

    class ObservedLock:
        def acquire(self, **kwargs):
            if updating.is_set():
                arrived.set()
            return real_lock.acquire(**kwargs)

        def release(self):
            real_lock.release()

    scanner.lock = ObservedLock()
    scanner.update = Mock(side_effect=update)
    scanner.load = Mock()
    with patch.object(gateway, "command", return_value="response") as command:
        first = threading.Thread(target=lambda: results.append(scanner.scan(b"one")))
        second = threading.Thread(target=lambda: results.append(scanner.scan(b"two")))
        first.start()
        assert updating.wait(5)
        second.start()
        assert arrived.wait(5)
        release.set()
        first.join(5)
        second.join(5)
    assert len(results) == 2
    scanner.update.assert_called_once()
    assert [call.args for call in command.call_args_list].count(("INSTREAM", b"one")) == 1
    assert [call.args for call in command.call_args_list].count(("INSTREAM", b"two")) == 1


def test_database_changes_restart_clamd_before_scanning():
    scanner = gateway.Scanner()
    running = Mock()
    running.poll.return_value = None
    scanner.process = running
    scanner.loaded_state = ("old",)
    fresh = Mock()
    fresh.poll.return_value = None
    with patch.object(gateway, "database_state", return_value=("new",)):
        with patch.object(gateway.subprocess, "Popen", return_value=fresh):
            with patch.object(gateway, "command", return_value="PONG"):
                scanner.load()
    running.terminate.assert_called_once()
    assert scanner.process is fresh
    assert scanner.loaded_state == ("new",)


def test_unchanged_database_does_not_restart_clamd():
    scanner = gateway.Scanner()
    scanner.process = Mock()
    scanner.process.poll.return_value = None
    scanner.loaded_state = ("same",)
    with patch.object(gateway, "database_state", return_value=("same",)):
        with patch.object(gateway.subprocess, "Popen") as start:
            scanner.load()
            start.assert_not_called()
    scanner.process.terminate.assert_not_called()


@pytest.fixture
def http_gateway():
    server = gateway.ThreadingHTTPServer(("127.0.0.1", 0), gateway.Handler)
    server.scanner = Mock()
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def test_real_http_health_never_triggers_scan(http_gateway):
    server, url = http_gateway
    with urllib.request.urlopen(url + "/health", timeout=5) as response:
        assert json.load(response) == {"status": "ready"}
    server.scanner.scan.assert_not_called()


def test_real_http_scan_and_update_failure(http_gateway):
    server, url = http_gateway
    server.scanner.scan.return_value = {"before": "engine", "after": "engine", "answer": "stream: OK"}
    request = urllib.request.Request(url + "/scan", data=b"document")
    with urllib.request.urlopen(request, timeout=5) as response:
        assert json.load(response)["answer"] == "stream: OK"
    server.scanner.scan.assert_called_once_with(b"document")
    server.scanner.scan.side_effect = RuntimeError("private content must not escape")
    with pytest.raises(urllib.error.HTTPError) as failure:
        urllib.request.urlopen(request, timeout=5)
    assert failure.value.code == 503
    assert b"private content" not in failure.value.read()


@pytest.mark.parametrize("reply", [b"stream: OK", b"stream: OK\\0extra\\0", b"\\xff\\0"])
def test_clamd_transport_rejects_incomplete_ambiguous_or_non_ascii_reply(reply):
    client, peer = socket.socketpair()

    def respond():
        with peer:
            peer.recv(100)
            peer.sendall(reply)

    thread = threading.Thread(target=respond)
    thread.start()
    try:
        with patch.object(gateway.socket, "create_connection", return_value=client):
            with pytest.raises(ValueError):
                gateway.command("VERSION")
    finally:
        client.close()
        thread.join(5)
