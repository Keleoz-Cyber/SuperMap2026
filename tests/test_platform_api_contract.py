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
from geomodeling.platform.repositories import FormalSelectionRepository
from geomodeling.platform.schemas import FormalSelectionRequest
from geomodeling.platform.tables import CandidateResult
from test_api import FakeIServer, LIVE_RESPONSES, make_config
from test_platform_repositories import (
    create_case,
    create_succeeded_candidate,
    set_candidate_status,
)


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


def test_health_reports_current_version(tmp_path, monkeypatch):
    app = make_integrated_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        body = client.get("/api/health").json()
    assert body["version"] == "0.6.1"


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


def test_microseismic_router_registered_without_shadowing_legacy(tmp_path, monkeypatch):
    """v0.5 微震路由注册后，legacy 精确路由仍然优先命中。"""
    app = make_integrated_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        legacy = client.get("/api/cases/resistivity")
        assert legacy.status_code == 200, legacy.text
        assert legacy.json()["case_id"] == "resistivity"

        paths = client.get("/openapi.json").json()["paths"]
        assert "/api/cases/{case_id}/microseismic-imports" in paths
        assert "/api/datasets/{dataset_id}/derivation" in paths


def test_professional_router_registered_without_shadowing_existing(tmp_path, monkeypatch):
    """v0.6 专业分析路由注册后，legacy 精确路由与微震路由仍然优先命中。"""
    app = make_integrated_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        legacy = client.get("/api/cases/resistivity")
        assert legacy.status_code == 200, legacy.text
        assert legacy.json()["case_id"] == "resistivity"

        paths = client.get("/openapi.json").json()["paths"]
        # 既有微震路由不被遮蔽
        assert "/api/cases/{case_id}/microseismic-imports" in paths
        assert "/api/datasets/{dataset_id}/derivation" in paths
        for path in (
            "/api/datasets/{dataset_id}/professional-diagnostics",
            "/api/professional-diagnostics/{diagnosis_id}",
            "/api/professional-diagnostics/{diagnosis_id}/variogram",
            "/api/professional-diagnostics/{diagnosis_id}/confirm",
            "/api/analysis-jobs/{job_id}",
            "/api/analysis-jobs/{job_id}/cancel",
            "/api/analysis-jobs/{job_id}/retry",
            "/api/results/{result_id}/professional",
            "/api/results/{result_id}/folds",
            "/api/results/{result_id}/residuals",
            "/api/results/{result_id}/uncertainty/{kind}",
            "/api/results/{result_id}/anomaly-extractions",
            "/api/anomaly-extractions/{extraction_id}",
            "/api/professional-comparisons",
            "/api/professional-comparisons/{comparison_id}",
            "/api/professional-artifacts/{artifact_id}/download",
        ):
            assert path in paths, path


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


# ---------------------------------------------------------------------------
# v0.6.1 featured_result：上传案例卡的主打成果直达链接
# ---------------------------------------------------------------------------


def _set_candidate_row(runtime, candidate_id: str, **fields) -> None:
    """直写候选行（手工构造时序/物化场景；生产路径只有 runner 会迁移状态）。"""

    with runtime.session() as session:
        row = session.get(CandidateResult, candidate_id)
        for key, value in fields.items():
            setattr(row, key, value)
        session.commit()


def _upload_card(client: TestClient, case_id: str) -> dict:
    body = client.get("/api/cases").json()
    return next(c for c in body["cases"] if c["case_id"] == case_id)


def test_upload_card_featured_result_prefers_formal_selection(tmp_path, monkeypatch):
    """正式选择优先：即使存在更新的成功候选，featured_result 仍指向正式成果。"""

    app = make_integrated_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        case_id = create_case(runtime, name="体积基准 32³")
        selected = create_succeeded_candidate(runtime, case_id)
        newer = create_succeeded_candidate(runtime, case_id)
        _set_candidate_row(
            runtime,
            selected,
            created_at="2026-08-01T00:00:00+00:00",
            grid_path="/grids/selected/grid.npz",
        )
        _set_candidate_row(runtime, newer, created_at="2026-08-02T00:00:00+00:00")
        with runtime.session() as session:
            FormalSelectionRepository(session).select(
                case_id,
                FormalSelectionRequest(
                    candidate_result_id=selected,
                    note="基准预置成果",
                    selected_by="seed",
                ),
            )
        featured = _upload_card(client, case_id)["featured_result"]
    assert featured["result_id"] == selected
    assert featured["url"] == f"/results/{selected}"
    assert featured["materialized"] is True


def test_upload_card_featured_result_falls_back_to_latest_succeeded(tmp_path, monkeypatch):
    """无正式选择时回退到本案例最新 succeeded 候选；他案例与未成功候选不参与。"""

    app = make_integrated_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        case_id = create_case(runtime, name="体积基准 64³")
        older = create_succeeded_candidate(runtime, case_id)
        latest = create_succeeded_candidate(runtime, case_id)
        failed = create_succeeded_candidate(runtime, case_id)
        set_candidate_status(runtime, failed, "failed")
        other_case_id = create_case(runtime, name="无关案例")
        other = create_succeeded_candidate(runtime, other_case_id)
        _set_candidate_row(runtime, older, created_at="2026-08-01T00:00:00+00:00")
        _set_candidate_row(runtime, latest, created_at="2026-08-02T00:00:00+00:00")
        # 更新的失败候选与本案例无关的候选都不得胜出
        _set_candidate_row(runtime, failed, created_at="2026-08-03T00:00:00+00:00")
        _set_candidate_row(runtime, other, created_at="2026-08-04T00:00:00+00:00")
        featured = _upload_card(client, case_id)["featured_result"]
    assert featured["result_id"] == latest
    assert featured["url"] == f"/results/{latest}"
    assert featured["materialized"] is False


def test_upload_card_featured_result_null_without_candidates(tmp_path, monkeypatch):
    """没有任何候选的上传案例：featured_result 字段保留但为 null。"""

    app = make_integrated_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        case_id = client.post("/api/cases", json={"name": "空案例"}).json()["id"]
        card = _upload_card(client, case_id)
    assert card["source_kind"] == "upload"
    assert card["featured_result"] is None


def test_legacy_cards_carry_no_featured_result(tmp_path, monkeypatch):
    """legacy 内置卡片不受 featured_result 扩展影响。"""

    app = make_integrated_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        body = client.get("/api/cases").json()
    legacy = [c for c in body["cases"] if c["source_kind"] == "builtin_legacy"]
    assert legacy, "应至少有一张 legacy 卡片"
    for card in legacy:
        assert card.get("featured_result") is None
