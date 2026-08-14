"""Portable tests for the v0.3 FastAPI layer (no live iServer, no real data)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from geomodeling.api.app import create_app
from geomodeling.api.deps import ApiSettings, get_app_config, get_iserver_client, get_settings
from geomodeling.config import AppConfig

FIXTURE_DIR = Path(__file__).parent / "fixtures"


class FakeIServer:
    """Scripted iServer stand-in with the IServerClient surface used by routes."""

    def __init__(self, responses=None, base_url="http://iserver.test/iserver"):
        self.responses = responses or {}
        self.base_url = base_url
        self.closed = False

    class _Resp:
        def __init__(self, ok, data=None, error=None, status=200):
            self.ok = ok
            self.data = data
            self.error = error
            self.status_code = status

    def get_json(self, path: str, *, use_token: bool = False):
        key = path.lstrip("/")
        value = self.responses.get(key)
        if value is None:
            return self._Resp(False, error="not scripted", status=None)
        return self._Resp(True, data=value)

    def close(self):
        self.closed = True


LIVE_RESPONSES = {
    "services.rjson": [
        {"name": "data-WorkSpace/rest", "url": "http://iserver.test/iserver/services/data-WorkSpace/rest"},
        {"name": "map-WorkSpace/rest", "url": "http://iserver.test/iserver/services/map-WorkSpace/rest"},
        {"name": "3D-WorkSpace/rest", "url": "http://iserver.test/iserver/services/3D-WorkSpace/rest"},
    ],
    "services/data-WorkSpace/rest/data/datasources.rjson": {"datasourceNames": ["expore1"]},
    "services/data-WorkSpace/rest/data/datasources/expore1/datasets.rjson": {
        "datasetNames": ["RHO_KRIG_FINAL_20M_40"]
    },
    "services/data-WorkSpace/rest/data/datasources/expore1/datasets/RHO_KRIG_FINAL_20M_40.rjson": {
        "datasetInfo": {
            "type": "VOLUME",
            "width": 7,
            "height": 23,
            "minValue": 1.4182828664779663,
            "maxValue": 133.1461944580078,
            "bounds": {"left": -160, "right": -40, "top": 660, "bottom": 220},
            "prjCoordSys": {"type": "PCS_NON_EARTH"},
        }
    },
    "services/3D-WorkSpace/rest/realspace/scenes.rjson": [{"name": "RHO_三维全值域"}],
    "services/3D-WorkSpace/rest/realspace/scenes/RHO_%E4%B8%89%E7%BB%B4%E5%85%A8%E5%80%BC%E5%9F%9F/layers.rjson": [
        {"name": "RHO_KRIG_FINAL_20M_40@expore1", "layer3DType": "ImageFileLayer", "visible": True}
    ],
}

VOLUME_RESPONSES = {
    "services/3D-local3DCache-RHO_KRIG_FINAL_20M_40_VOL_S3M2/rest/realspace/scenes.rjson": [
        {"name": "默认场景"}
    ],
    "services/3D-local3DCache-RHO_KRIG_FINAL_20M_40_VOL_S3M2/rest/realspace/scenes/%E9%BB%98%E8%AE%A4%E5%9C%BA%E6%99%AF/layers.rjson": [
        {"name": "RHO_KRIG_FINAL_20M_40_vol", "layer3DType": "OSGBLayer", "visible": True}
    ],
}


def make_config(standardized: Path | None = None) -> AppConfig:
    raw = yaml.safe_load(Path("config/default.yaml").read_text(encoding="utf-8"))
    if standardized is not None:
        raw["paths"]["standardized"] = str(standardized)
    return AppConfig.model_validate(raw)


def make_client(
    tmp_path: Path,
    *,
    iserver: FakeIServer | None = None,
    config: AppConfig | None = None,
    metrics_doc: dict | None = None,
) -> TestClient:
    metrics_json = None
    if metrics_doc is not None:
        metrics_json = tmp_path / "metric_summaries.json"
        metrics_json.write_text(json.dumps(metrics_doc, ensure_ascii=False), encoding="utf-8")

    settings = ApiSettings(
        config_path=Path("config/default.yaml"),
        metrics_json=metrics_json,
        evidence_dir=tmp_path / "evidence",
        frontend_dist=None,
        voxel_cache_dir=None,
    )
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_app_config] = lambda: (config or make_config())
    fake = iserver if iserver is not None else FakeIServer(LIVE_RESPONSES)
    app.dependency_overrides[get_iserver_client] = lambda: fake
    return TestClient(app)


def test_health(tmp_path):
    client = make_client(tmp_path)
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["version"] == "0.9.3"


def test_cases_cards(tmp_path):
    client = make_client(tmp_path)
    body = client.get("/api/cases").json()
    by_id = {c["case_id"]: c for c in body["cases"]}
    # v0.8.0 Task 6：legacy 电阻率卡退役；未 seed 运行库出预置描述卡
    assert by_id["resistivity"]["status"] == "initialization_required"
    assert by_id["resistivity"]["workspace_kind"] == "builtin_preset"
    # v0.8.0 第三批 Task 4：legacy 瓦斯卡（最后一张 legacy 卡）同模式退役；
    # 未 seed 运行库出预置描述卡，首页不再出现 parked/"暂缓" 文案
    assert by_id["gas"]["status"] == "initialization_required"
    assert by_id["gas"]["workspace_kind"] == "builtin_preset"
    # v0.7.0：旧 DAT 微震卡由 builtin_preset 预置描述符取代（未 seed 时可见但能力全 false）
    assert "microseismic" not in by_id
    preset = by_id["builtin-microseismic-vx-1911"]
    assert preset["workspace_kind"] == "builtin_preset"
    assert preset["status"] == "initialization_required"


def test_case_list_json_has_no_legacy_dat_parked_tokens(tmp_path):
    """v0.8.0 第三批 Task 7：首页案例列表 JSON 无 parked/暂缓/DAT/legacy 字样。

    gas 是最后一张退役的 legacy 卡：任何运行库状态下列表只剩 builtin_preset
    与 user_upload 卡，序列化 JSON 绝不出现旧流程语样。
    """

    client = make_client(tmp_path)
    response = client.get("/api/cases")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cases"], "首页至少应有三张预置描述卡"
    assert all(card["source_kind"] != "builtin_legacy" for card in body["cases"])
    serialized = json.dumps(body, ensure_ascii=False)
    for token in ("parked", "暂缓", "DAT", "legacy", "Legacy"):
        assert token not in serialized, token


def test_resistivity_detail_leaderboard_uses_metric_summaries(tmp_path):
    metrics_doc = {
        "summaries": {
            "Kriging 20m/40点": {"mae": 3.222594, "rmse": 5.841043, "r2": 0.93, "n_valid": 1481, "n_nodata": 241}
        },
        "baseline_comparison": {"baseline_passed": True},
    }
    client = make_client(tmp_path, metrics_doc=metrics_doc)
    body = client.get("/api/cases/resistivity").json()
    assert body["metric_source"] != "config_only"
    by_name = {m["display_name"]: m for m in body["models"]}
    assert by_name["Kriging 20m/40点"]["metrics"]["n_valid"] == 1481
    assert by_name["IDW 20m/25点"]["metrics"] is None
    assert body["datasets"][0]["rows"] == 17549
    assert any(r["result_category"] == "formal" for r in body["supermap"]["results"])
    assert any(r["status"] == "failed" for r in body["supermap"]["results"])


def test_resistivity_detail_degrades_to_config_only(tmp_path):
    client = make_client(tmp_path)
    body = client.get("/api/cases/resistivity").json()
    assert body["metric_source"] == "config_only"
    assert all(m["metrics"] is None for m in body["models"])


def test_publish_status_live_evidence_chain(tmp_path):
    client = make_client(tmp_path)
    body = client.get("/api/cases/resistivity/publish-status").json()
    assert body["iserver_available"] is True
    states = {s["state"]: s for s in body["evidence_chain"]["states"]}
    assert states["model_succeeded"]["ok"] is True
    assert states["iserver_published"]["ok"] is True
    assert states["service_metadata_verified"]["ok"] is True
    assert states["browser_loaded"]["ok"] is False
    assert states["manual_visual_checked"]["ok"] is True


def test_publish_status_volume_service_pending_by_default(tmp_path):
    client = make_client(tmp_path)
    body = client.get("/api/cases/resistivity/publish-status").json()
    volume = body["planned_services"]["volume"]
    assert volume["available"] is False
    assert volume["scene_name"] == "默认场景"
    assert "待 iDesktopX" in volume["note"]


def test_publish_status_volume_service_available_when_published(tmp_path):
    responses = dict(LIVE_RESPONSES)
    responses.update(VOLUME_RESPONSES)
    responses["services.rjson"] = LIVE_RESPONSES["services.rjson"] + [
        {
            "name": "3D-local3DCache-RHO_KRIG_FINAL_20M_40_VOL_S3M2/rest",
            "url": "http://iserver.test/iserver/services/3D-local3DCache-RHO_KRIG_FINAL_20M_40_VOL_S3M2/rest",
        }
    ]
    client = make_client(tmp_path, iserver=FakeIServer(responses))
    body = client.get("/api/cases/resistivity/publish-status").json()
    volume = body["planned_services"]["volume"]
    assert volume["available"] is True
    assert volume["layers"][0]["layer3DType"] == "OSGBLayer"


def test_publish_status_iserver_down_keeps_model_state(tmp_path):
    down = FakeIServer({})
    client = make_client(tmp_path, iserver=down)
    body = client.get("/api/cases/resistivity/publish-status").json()
    assert body["iserver_available"] is False
    states = {s["state"]: s for s in body["evidence_chain"]["states"]}
    assert states["model_succeeded"]["ok"] is True
    assert states["iserver_published"]["ok"] is False
    assert states["service_metadata_verified"]["ok"] is False


def test_browser_load_report_flips_evidence_state(tmp_path):
    client = make_client(tmp_path)
    before = client.get("/api/cases/resistivity/publish-status").json()
    states = {s["state"]: s for s in before["evidence_chain"]["states"]}
    assert states["browser_loaded"]["ok"] is False

    resp = client.post(
        "/api/evidence/browser-load",
        json={
            "case_id": "resistivity",
            "result_id": "RHO_KRIG_FINAL_20M_40",
            "service_url": "http://iserver.test/iserver/services/3D-WorkSpace/rest/realspace",
            "scene_name": "RHO_三维全值域",
            "layer_count": 1,
            "success": True,
            "render_kind": "iserver_scene",
            "validated_count": 1,
        },
    )
    assert resp.status_code == 201

    after = client.get("/api/cases/resistivity/publish-status").json()
    states = {s["state"]: s for s in after["evidence_chain"]["states"]}
    assert states["browser_loaded"]["ok"] is True
    assert states["browser_loaded"]["source"] == "browser_report"
    assert "iserver_scene" in states["browser_loaded"]["detail"]


def test_browser_load_fallback_report_never_flips_evidence(tmp_path):
    client = make_client(tmp_path)
    resp = client.post(
        "/api/evidence/browser-load",
        json={
            "case_id": "resistivity",
            "result_id": "RHO_KRIG_FINAL_20M_40",
            "service_url": "http://iserver.test/iserver/services/3D-WorkSpace/rest/realspace",
            "success": False,
            "render_kind": "fallback_points",
            "validated_count": 0,
            "note": "iServer 场景打开失败，仅点云渲染",
        },
    )
    assert resp.status_code == 201

    body = client.get("/api/cases/resistivity/publish-status").json()
    states = {s["state"]: s for s in body["evidence_chain"]["states"]}
    assert states["browser_loaded"]["ok"] is False


def test_browser_load_rejects_wrong_service_identity(tmp_path):
    client = make_client(tmp_path)
    resp = client.post(
        "/api/evidence/browser-load",
        json={
            "case_id": "resistivity",
            "result_id": "RHO_KRIG_FINAL_20M_40",
            "service_url": "http://evil.example/iserver/services/3D-Fake/rest/realspace",
            "scene_name": "RHO_三维全值域",
            "layer_count": 2,
            "success": True,
            "render_kind": "iserver_scene",
            "validated_count": 2,
        },
    )
    assert resp.status_code == 201

    body = client.get("/api/cases/resistivity/publish-status").json()
    states = {s["state"]: s for s in body["evidence_chain"]["states"]}
    assert states["browser_loaded"]["ok"] is False


def test_browser_load_rejects_cross_forged_kind(tmp_path):
    client = make_client(tmp_path)
    resp = client.post(
        "/api/evidence/browser-load",
        json={
            "case_id": "resistivity",
            "result_id": "RHO_KRIG_FINAL_20M_40",
            "service_url": "http://iserver.test/iserver/services/3D-WorkSpace/rest/realspace",
            "scene_name": "默认场景",
            "layer_count": 1,
            "success": True,
            "render_kind": "s3m_voxel_cache",
            "validated_count": 7056,
        },
    )
    assert resp.status_code == 201

    body = client.get("/api/cases/resistivity/publish-status").json()
    states = {s["state"]: s for s in body["evidence_chain"]["states"]}
    assert states["browser_loaded"]["ok"] is False


def test_points_endpoint_uses_fixture_csv(tmp_path):
    config = make_config(standardized=FIXTURE_DIR / "rho_tiny_validation.csv")
    client = make_client(tmp_path, config=config)
    body = client.get("/api/cases/resistivity/points").json()
    assert body["source"] == "platform_csv"
    assert body["count"] == 3
    assert body["served"] == 3
    assert body["values"] == [10.0, 20.0, 30.0]
    assert len(body["sha256"]) == 64

    body2 = client.get("/api/cases/resistivity/points?decimate=2").json()
    assert body2["served"] == 2


def test_points_endpoint_missing_csv_is_503(tmp_path):
    config = make_config(standardized=Path("does/not/exist.csv"))
    client = make_client(tmp_path, config=config)
    resp = client.get("/api/cases/resistivity/points")
    assert resp.status_code == 503
