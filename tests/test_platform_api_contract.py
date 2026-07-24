"""Task 10 contract tests: v0.4 integration with the v0.3.1 legacy adapter.

Covers the merged case list, route ordering (legacy exact routes must not
be swallowed by ``/api/cases/{case_id}``), the unified error envelope with
path redaction, the dev version report, and clean lifespan shutdown.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from geomodeling.api.app import create_app
from geomodeling.api.deps import ApiSettings, get_app_config, get_iserver_client, get_settings
from test_api import FakeIServer, LIVE_RESPONSES, make_config


def make_integrated_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    config=None,
    iserver: FakeIServer | None = None,
):
    monkeypatch.setenv("GEOMODELING_DATA_DIR", str(tmp_path / "data"))
    settings = ApiSettings(
        config_path=Path("config/default.yaml"),
        metrics_json=None,
        evidence_dir=tmp_path / "evidence",
        frontend_dist=None,
        voxel_cache_dir=None,
    )
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_app_config] = lambda: (config or make_config())
    fake = iserver if iserver is not None else FakeIServer(LIVE_RESPONSES)
    app.dependency_overrides[get_iserver_client] = lambda: fake
    return app


def test_health_reports_v04_dev_version(tmp_path, monkeypatch):
    app = make_integrated_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        body = client.get("/api/health").json()
    assert body["version"] == "0.4.0-dev"


def test_cases_merges_legacy_card_and_upload_cases(tmp_path, monkeypatch):
    app = make_integrated_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        resp = client.post("/api/cases", json={"name": "集成上传案例"})
        assert resp.status_code == 201, resp.text
        case_id = resp.json()["id"]

        body = client.get("/api/cases").json()
    by_id = {c["case_id"]: c for c in body["cases"]}
    assert by_id["resistivity"]["source_kind"] == "builtin_legacy"
    assert by_id["resistivity"]["status"] == "active"
    # v0.3.1 卡片语义保留
    assert by_id["microseismic"]["status"] == "audit_only"
    assert by_id["gas"]["status"] == "parked"
    uploaded = by_id[case_id]
    assert uploaded["title"] == "集成上传案例"
    assert uploaded["source_kind"] == "upload"
    assert uploaded["links"]["detail"] == f"/api/cases/{case_id}"


def test_generated_case_uuid_resolves_and_unknown_is_envelope_404(tmp_path, monkeypatch):
    app = make_integrated_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        case_id = client.post("/api/cases", json={"name": "按ID查询"}).json()["id"]
        detail = client.get(f"/api/cases/{case_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["name"] == "按ID查询"

        missing = client.get("/api/cases/00000000-0000-0000-0000-000000000000")
        assert missing.status_code == 404
        payload = missing.json()
        assert payload["error"]["code"] == "CASE_NOT_FOUND"
        assert set(payload["error"]) == {"code", "message", "details"}


def test_legacy_exact_routes_not_swallowed_by_dynamic_case_route(tmp_path, monkeypatch):
    app = make_integrated_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        detail = client.get("/api/cases/resistivity")
        assert detail.status_code == 200, detail.text
        assert detail.json()["case_id"] == "resistivity"
        assert "models" in detail.json()

        publish = client.get("/api/cases/resistivity/publish-status")
        assert publish.status_code == 200, publish.text
        assert "evidence_chain" in publish.json()


def test_http_errors_use_envelope_and_never_leak_paths(tmp_path, monkeypatch):
    missing_csv = (tmp_path / "missing-standardized.csv").resolve()
    config = make_config(standardized=missing_csv)
    app = make_integrated_app(tmp_path, monkeypatch, config=config)
    with TestClient(app) as client:
        resp = client.get("/api/cases/resistivity/points")
        assert resp.status_code == 503
        payload = resp.json()
        assert set(payload) == {"error"}
        assert payload["error"]["code"]
        # 本机绝对路径不得出现在任何公开错误字段里
        assert str(tmp_path) not in json.dumps(payload, ensure_ascii=False)
        assert "missing-standardized" not in json.dumps(payload, ensure_ascii=False)


def test_lifespan_shutdown_stops_worker_and_closes_runtime(tmp_path, monkeypatch):
    app = make_integrated_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        worker = app.state.job_worker
        assert runtime.db_path.exists()
        assert client.get("/api/health").json()["status"] == "ok"
    # 关闭后：执行器拒绝新任务，数据库引擎已释放
    with pytest.raises(RuntimeError):
        worker._executor.submit(lambda: None)
    with pytest.raises(RuntimeError):
        _ = runtime.engine
