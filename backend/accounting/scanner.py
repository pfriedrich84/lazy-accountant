"""Local clamd protocol only. An incomplete or ambiguous answer is never clean."""

import re
import socket
import struct
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from django.conf import settings


class ScanError(Exception):
    pass


@dataclass
class Verdict:
    result: str
    engine: str
    signature: str = ""
    reason: str = ""


def command(name, data=None):
    deadline = time.monotonic() + settings.CLAMAV_TIMEOUT
    with socket.create_connection(
        (settings.CLAMAV_HOST, settings.CLAMAV_PORT), timeout=settings.CLAMAV_TIMEOUT
    ) as sock:

        def send(chunk):
            sock.settimeout(max(0.001, deadline - time.monotonic()))
            sock.sendall(chunk)

        send(b"z" + name.encode("ascii") + b"\0")
        if data is not None:
            for offset in range(0, len(data), 65536):
                chunk = data[offset : offset + 65536]
                send(struct.pack("!I", len(chunk)) + chunk)
            send(struct.pack("!I", 0))
        answer = bytearray()
        while len(answer) < 4096:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ScanError("Scanner-Zeitlimit überschritten.")
            sock.settimeout(remaining)
            chunk = sock.recv(4096 - len(answer))
            if not chunk:
                break
            answer.extend(chunk)
            if b"\0" in answer:
                if not answer.endswith(b"\0") or answer.count(b"\0") != 1:
                    raise ScanError("Mehrdeutige Scannerantwort.")
                return answer[:-1].decode("ascii", errors="strict")
        raise ScanError("Unvollständige Scannerantwort.")


def readiness():
    version = command("VERSION")
    match = re.fullmatch(r"ClamAV ([^/\s]+)/([0-9]+)/(.+)", version)
    if not match or int(match[2]) <= 0:
        raise ScanError("Scanner ohne vertrauenswürdigen Signaturstand.")
    try:
        stamp = datetime.strptime(match[3], "%a %b %d %H:%M:%S %Y").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ScanError("Unbekanntes Signaturdatum.") from exc
    age = (datetime.now(timezone.utc) - stamp).total_seconds()
    if age < -3600 or age > settings.CLAMAV_MAX_SIGNATURE_AGE:
        raise ScanError("Scanner-Signaturen fehlen oder sind veraltet.")
    return version


def scan(data):
    engine = ""
    try:
        engine = readiness()
        answer = command("INSTREAM", data)
        if any(ord(char) < 32 or ord(char) > 126 for char in answer):
            raise ScanError("Mehrdeutige Scannerantwort.")
        readiness()  # Do not release across expired signatures / failed reloads.
        if answer == "stream: OK":
            return Verdict("clean", engine)
        if answer.startswith("stream: ") and answer.endswith(" FOUND"):
            signature = answer[len("stream: ") : -len(" FOUND")][:200]
            if not signature:
                raise ScanError("Leerer Signaturname.")
            # AlertExceedsMax and AlertEncrypted turn partial inspection into
            # heuristic FOUND responses. They are technical failures, not clean.
            if signature.startswith(("Heuristics.Limits.", "Heuristics.Encrypted.")):
                return Verdict("error", engine, signature, "Inhalt nicht vollständig prüfbar: " + signature)
            return Verdict("infected", engine, signature, "Malwarefund: " + signature)
        raise ScanError("Scanner hat die Prüfung nicht erfolgreich abgeschlossen.")
    except ScanError as exc:
        return Verdict("error", engine, reason=str(exc))
    except OSError, ValueError:
        # Never persist arbitrary scanner replies (they may contain input data).
        return Verdict("error", engine, reason="Scanner nicht erreichbar, Zeitlimit oder ungültige Antwort.")
