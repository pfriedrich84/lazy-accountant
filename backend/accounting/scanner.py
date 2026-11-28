"""Private on-demand update/scan gateway. Ambiguous answers are never clean."""

import json
import re
import urllib.error
import urllib.request
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


def readiness(version):
    match = re.fullmatch(r"ClamAV ([^/\s]+)/([0-9]+)/(.+)", version)
    if not match or int(match[2]) <= 0:
        raise ScanError("Scanner ohne vertrauenswürdigen Signaturstand.")
    try:
        stamp = datetime.strptime(match[3], "%a %b %d %H:%M:%S %Y").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ScanError("Unbekanntes Signaturdatum.") from exc
    age = (datetime.now(timezone.utc) - stamp).total_seconds()
    if age < -3600:
        raise ScanError(
            f"ClamAV-Signaturdatum liegt in der Zukunft ({stamp:%Y-%m-%d %H:%M} UTC). Systemuhr prüfen."
        )
    if age > settings.CLAMAV_MAX_SIGNATURE_AGE:
        raise ScanError(f"Geladene ClamAV-Signaturen sind veraltet (Stand: {stamp:%Y-%m-%d %H:%M} UTC).")
    return version


def exchange(data):
    # The private gateway serializes update + database load + scan. No direct
    # clamd fallback is permitted when the update service fails.
    request = urllib.request.Request(
        f"http://{settings.CLAMAV_HOST}:{settings.CLAMAV_GATEWAY_PORT}/scan",
        data=data,
        headers={"Content-Type": "application/octet-stream"},
        method="POST",
    )
    # Never send private document bytes through an environment-configured proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=240) as response:
            result = json.loads(response.read(16385))
    except urllib.error.HTTPError as exc:
        with exc:
            if exc.code == 503:
                try:
                    error = json.loads(exc.read(1024))
                except ValueError:
                    error = None
                if error == {"error": "signature_update_cooldown"}:
                    raise ScanError("ClamAV-Signaturupdate durch CDN-Wartefrist blockiert.") from None
        raise
    if not isinstance(result, dict) or any(
        not isinstance(result.get(key), str) for key in ("before", "answer", "after")
    ):
        raise ScanError("Ungültige Antwort des Update-/Scandienstes.")
    return result["before"], result["answer"], result["after"]


def scan(data):
    engine = ""
    try:
        before, answer, after = exchange(data)
        engine = readiness(before)
        if any(ord(char) < 32 or ord(char) > 126 for char in answer):
            raise ScanError("Mehrdeutige Scannerantwort.")
        readiness(after)  # Do not release across expired signatures / failed reloads.
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
        return Verdict(
            "error",
            engine,
            reason="Signaturupdate/Scanner fehlgeschlagen, nicht erreichbar oder Zeitlimit überschritten.",
        )
