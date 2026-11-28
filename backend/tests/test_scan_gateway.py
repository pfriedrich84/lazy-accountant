import io
import json
import urllib.error
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from django.conf import settings

from accounting import scanner

pytestmark = pytest.mark.security


def test_scan_uses_on_demand_gateway_before_releasing_bytes():
    version = "ClamAV 1.5.5/123/" + datetime.now(timezone.utc).strftime("%a %b %d %H:%M:%S %Y")
    response = io.BytesIO(json.dumps({"before": version, "after": version, "answer": "stream: OK"}).encode())
    with patch("urllib.request.OpenerDirector.open", return_value=response) as send:
        assert scanner.scan(b"example").result == "clean"
    request = send.call_args.args[0]
    assert request.full_url == f"http://{settings.CLAMAV_HOST}:3311/scan"
    assert request.data == b"example"
    assert request.method == "POST"


def test_update_failure_never_falls_back_to_direct_scan():
    with patch("urllib.request.OpenerDirector.open", side_effect=OSError("update failed")):
        with patch("socket.create_connection") as direct:
            assert scanner.scan(b"example").result == "error"
            direct.assert_not_called()


def test_cooldown_is_reported_without_releasing_bytes():
    failure = urllib.error.HTTPError(
        "http://clamav:3311/scan",
        503,
        "Unavailable",
        {},
        io.BytesIO(b'{"error":"signature_update_cooldown"}'),
    )
    with patch("urllib.request.OpenerDirector.open", side_effect=failure):
        verdict = scanner.scan(b"example")
    assert verdict.result == "error"
    assert "CDN-Wartefrist" in verdict.reason


@pytest.mark.parametrize(
    "answer, expected",
    [
        ("stream: OK", "clean"),
        ("stream: Test-Signature FOUND", "infected"),
        ("stream: timeout ERROR", "error"),
    ],
)
def test_successful_update_check_with_older_signatures_uses_actual_scan_verdict(answer, expected):
    stamp = datetime.now(timezone.utc) - timedelta(days=4)
    version = "ClamAV 1.5.5/28194/" + stamp.strftime("%a %b %d %H:%M:%S %Y")
    response = io.BytesIO(json.dumps({"before": version, "after": version, "answer": answer}).encode())
    with patch("urllib.request.OpenerDirector.open", return_value=response):
        verdict = scanner.scan(b"example")
    assert verdict.result == expected
    assert verdict.engine == version
