"""Task 3: demo dataset download endpoint contract."""

from __future__ import annotations

import hashlib
import json

from fastapi.testclient import TestClient

from geomodeling.api.app import create_app
from geomodeling.platform.errors import PlatformError

EXPECTED_DEMO_SHA256 = "deb9c25f713ae79d7b1c6300cc8066a6ae927879767c67ab03ef4ad76e8a2bb3"


def test_demo_dataset_download_has_stable_content():
    with TestClient(create_app()) as client:
        response = client.get("/api/demo/datasets/platform-demo-3d")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert "platform_demo_3d.csv" in response.headers["content-disposition"]
    assert hashlib.sha256(response.content).hexdigest() == EXPECTED_DEMO_SHA256
    assert b"D:\\" not in response.content
    # 真实行数与列头
    lines = response.text.strip().splitlines()
    assert lines[0] == "x,y,z,rho"
    assert len(lines) == 145


def test_demo_dataset_missing_returns_sanitized_503(monkeypatch, tmp_path):
    from geomodeling.api.routes import demo as demo_route

    def missing():
        raise PlatformError(
            "DEMO_DATASET_UNAVAILABLE",
            "演示数据不可用",
            {"path": tmp_path / "missing.csv"},
            http_status=503,
        )

    monkeypatch.setattr(demo_route, "get_demo_dataset", missing)
    with TestClient(create_app()) as client:
        response = client.get("/api/demo/datasets/platform-demo-3d")
    assert response.status_code == 503
    payload = response.json()
    assert payload["error"]["code"] == "DEMO_DATASET_UNAVAILABLE"
    assert str(tmp_path) not in json.dumps(payload, ensure_ascii=False)
