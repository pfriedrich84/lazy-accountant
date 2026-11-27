import io
import json
from unittest.mock import patch

import pytest
from django.conf import settings

from accounting import scanner

pytestmark = pytest.mark.security


def test_scan_uses_on_demand_gateway_before_releasing_bytes():
    from datetime import datetime, timezone

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
