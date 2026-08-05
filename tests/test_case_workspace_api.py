"""v0.7.0 Batch 1 Task 4：统一案例工作台卡片/工作台 API 合同测试。

三类身份：builtin_legacy（电阻率等既有内置卡）、builtin_preset（微震 CSV
预置）、user_upload（用户上传）。未 seed 的预置卡在列表中保持可见但能力
全 false，工作台返回类型化 PRESET_NOT_INITIALIZED；任何响应都不得泄漏
本机绝对路径。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from geomodeling.platform.microseismic_preset import PRESET_CASE_ID, TRACKED_CSV_SHA256


def _make_client(tmp_path: Path, *, seed: bool):
    from fastapi.testclient import TestClient

    from geomodeling.api.app import create_app
    from geomodeling.api.deps import ApiSettings, get_app_config, get_iserver_client, get_settings
    from geomodeling.platform import PlatformRuntime
    from test_api import FakeIServer, make_config

    fixture_csv = Path("tests/fixtures/rho_tiny_validation.csv").resolve()
    config = make_config(standardized=fixture_csv)
    settings = ApiSettings(
        config_path=Path("config/default.yaml"),
        metrics_json=(tmp_path / "m.json"),
        evidence_dir=tmp_path / "evidence",
        frontend_dist=None,
        voxel_cache_dir=tmp_path / "cache",
    )
    (tmp_path / "m.json").write_text('{"summaries": {}}', encoding="utf-8")

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_app_config] = lambda: config
    app.dependency_overrides[get_iserver_client] = lambda: FakeIServer({})

    runtime = PlatformRuntime(tmp_path / "data")
    runtime.initialize()
    if seed:
        from geomodeling.platform.microseismic_preset import seed_microseismic_preset

        seed_microseismic_preset(runtime)
    app.state.platform_runtime = runtime
    return TestClient(app)


@pytest.fixture(scope="module")
def seeded_client(tmp_path_factory):
    runtime_dir = tmp_path_factory.mktemp("workspace-seeded")
    client = _make_client(runtime_dir, seed=True)
    return client


@pytest.fixture()
def fresh_client(tmp_path):
    return _make_client(tmp_path, seed=False)


def _cards(client) -> dict:
    response = client.get("/api/cases")
    assert response.status_code == 200, response.text
    return {card["case_id"]: card for card in response.json()["cases"]}


def test_case_cards_expose_workspace_kind_capabilities_primary_dataset_and_official_result(
    seeded_client,
):
    cards = _cards(seeded_client)
    assert cards["resistivity"]["workspace_kind"] == "builtin_legacy"
    assert cards["resistivity"]["capabilities"]["native_volume"] is True
    assert cards["resistivity"]["capabilities"]["experiments"] is False

    preset = cards[PRESET_CASE_ID]
    assert preset["workspace_kind"] == "builtin_preset"
    assert preset["capabilities"]["experiments"] is True
    assert preset["capabilities"]["data_summary"] is True
    assert preset["capabilities"]["official_result"] is True
    assert preset["official_result"]["materialized"] is True
    assert preset["official_result"]["url"].startswith("/results/")
    assert preset["primary_dataset"]["status"] == "validated"
    assert preset["provenance_summary"]["source_sha256"] == TRACKED_CSV_SHA256
    assert preset["provenance_summary"]["value_unit"] == "km/s"


def test_legacy_microseismic_dat_card_is_replaced_by_preset(fresh_client):
    cards = _cards(fresh_client)
    assert "microseismic" not in cards
    preset = cards[PRESET_CASE_ID]
    assert preset["workspace_kind"] == "builtin_preset"
    assert preset["status"] == "initialization_required"
    assert preset["capabilities"] == {
        "data_summary": False,
        "experiments": False,
        "official_result": False,
        "native_volume": False,
    }
    assert preset["official_result"] is None
    assert preset["primary_dataset"] is None


def test_workspace_get_returns_404_for_unknown_case_and_never_leaks_source_paths(seeded_client):
    assert seeded_client.get("/api/cases/no-such-case/workspace").status_code == 404

    response = seeded_client.get(f"/api/cases/{PRESET_CASE_ID}/workspace")
    assert response.status_code == 200, response.text
    text = response.text
    assert "D:\\" not in text and "/tmp" not in text and "source_path" not in text
    body = response.json()
    assert body["workspace_kind"] == "builtin_preset"
    assert body["official_result"]["materialized"] is True
    assert body["primary_dataset"]["profile"]["mapping"]["value_name"] == "Vx"


def test_unseeded_preset_workspace_returns_typed_initialization_error(fresh_client):
    cards = _cards(fresh_client)
    assert PRESET_CASE_ID in cards
    response = fresh_client.get(f"/api/cases/{PRESET_CASE_ID}/workspace")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PRESET_NOT_INITIALIZED"


def test_upload_case_maps_user_upload_with_capabilities(seeded_client):
    from geomodeling.platform import tables

    runtime = seeded_client.app.state.platform_runtime
    with runtime.session() as session:
        session.add(
            tables.Case(id="up-1", name="上传案例", case_type="generic", config_json="{}")
        )
        session.commit()
    cards = _cards(seeded_client)
    assert cards["up-1"]["workspace_kind"] == "user_upload"
    assert cards["up-1"]["capabilities"]["experiments"] is False  # 无已验证数据版本
    response = seeded_client.get("/api/cases/up-1/workspace")
    assert response.status_code == 200
    assert response.json()["workspace_kind"] == "user_upload"


def test_legacy_resistivity_workspace_resolves_as_builtin_legacy(seeded_client):
    response = seeded_client.get("/api/cases/resistivity/workspace")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["workspace_kind"] == "builtin_legacy"
    assert body["capabilities"]["native_volume"] is True
    assert body["capabilities"]["experiments"] is False
