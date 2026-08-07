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


# ---------------------------------------------------------------------------
# Task 8：DAT 产品入口缺席（导入 POST 与派生读取均不可达；通用读取兼容）
# ---------------------------------------------------------------------------

def test_dat_import_and_derivation_endpoints_are_not_registered(seeded_client):
    # DAT 导入 POST：产品注册已移除（404/405 均可，绝不 2xx）
    response = seeded_client.post(f"/api/cases/{PRESET_CASE_ID}/microseismic-imports")
    assert response.status_code in (404, 405)
    # DAT 派生证据读取端点同批退出产品面
    dataset_id = _cards(seeded_client)[PRESET_CASE_ID]["primary_dataset"]["id"]
    assert seeded_client.get(f"/api/datasets/{dataset_id}/derivation").status_code in (404, 405)
    assert seeded_client.get(
        f"/api/datasets/{dataset_id}/derivation/points"
    ).status_code in (404, 405)


def test_generic_result_and_dataset_reads_still_work(seeded_client):
    cards = _cards(seeded_client)
    result_id = cards[PRESET_CASE_ID]["official_result"]["result_id"]
    dataset_id = cards[PRESET_CASE_ID]["primary_dataset"]["id"]
    result = seeded_client.get(f"/api/results/{result_id}")
    assert result.status_code == 200, result.text
    dataset = seeded_client.get(f"/api/datasets/{dataset_id}")
    assert dataset.status_code == 200, dataset.text


# ---------------------------------------------------------------------------
# v0.7.0 补齐：user_upload 工作台深状态（数据版本 + 主打成果两种来源）
# ---------------------------------------------------------------------------

import threading  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from geomodeling.modeling.runner import execute_run  # noqa: E402
from geomodeling.platform.results import materialize  # noqa: E402
from geomodeling.platform.repositories import FormalSelectionRepository  # noqa: E402
from geomodeling.platform.schemas import FormalSelectionRequest  # noqa: E402


def _build_upload_result(runtime, case_id: str, *, formal: bool) -> str:
    """上传案例：标准化数据 → 实验 → 运行 → 物化 →（可选）正式选择。"""

    from geomodeling.platform import tables

    dataset_id = f"{case_id}-ds"
    experiment_id = f"{case_id}-exp"
    run_id = f"{case_id}-run"
    rng = np.random.default_rng(7)
    n = 36
    x = rng.uniform(-160.0, -40.0, n)
    y = rng.uniform(220.0, 660.0, n)
    z = rng.uniform(-800.0, -100.0, n)
    frame = pd.DataFrame(
        {
            "source_row": np.arange(1, n + 1),
            "x": x,
            "y": y,
            "z": z,
            "value": np.sin(x / 40) + np.cos(y / 90) + 0.001 * z + 10.0,
            "is_numeric_valid": True,
        }
    )
    target = runtime.settings.standardized_dataset(case_id, dataset_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(target, index=False)
    params = {
        "algorithm": "idw",
        "dataset_version_id": dataset_id,
        "search_mode": "manual",
        "parameters": {"power": 2.0, "neighbor_count": 8},
        "validation": {"method": "spatial_kfold", "folds": 3, "seed": 11},
        "grid": {
            "bounds": [[-160.0, -40.0], [220.0, 660.0], [-800.0, -100.0]],
            "resolution": [40.0, 40.0, 100.0],
            "max_cells": 100000,
        },
    }
    profile = {
        "mapping": {
            "dimension": "3d",
            "x": "x",
            "y": "y",
            "z": "z",
            "value": "value",
            "value_name": "电阻率",
            "value_unit": "ohm-m",
            "coordinate_kind": "local_linear",
        },
        "row_count": n,
        "valid_row_count": n,
        "invalid_row_count": 0,
        "source_sha256": "a" * 64,
        "standardized_sha256": "b" * 64,
        "standardized_path": str(target),
        "quality": {"status": "passed", "confirmed": True},
    }
    with runtime.session() as session:
        session.add(
            tables.Case(id=case_id, name="上传案例", case_type="generic", config_json="{}")
        )
        session.add(
            tables.DatasetVersion(
                id=dataset_id,
                case_id=case_id,
                version=1,
                status="validated",
                source_path="x.csv",
                profile_json=tables.dumps_canonical(profile),
            )
        )
        session.add(
            tables.Experiment(
                id=experiment_id,
                case_id=case_id,
                name="实验",
                params_json=tables.dumps_canonical(params),
            )
        )
        session.add(tables.Run(id=run_id, experiment_id=experiment_id, status="queued"))
        session.commit()
    outcome = execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "succeeded"
    with runtime.session() as session:
        candidate = (
            session.query(tables.CandidateResult)
            .filter(tables.CandidateResult.run_id == run_id)
            .one()
        )
        candidate_id = candidate.id
    materialize(runtime, candidate_id)
    if formal:
        with runtime.session() as session:
            FormalSelectionRepository(session).select(
                case_id,
                FormalSelectionRequest(candidate_result_id=candidate_id, note="测试选择"),
            )
    return dataset_id, candidate_id


def test_upload_workspace_with_dataset_and_formal_selection(seeded_client):
    runtime = seeded_client.app.state.platform_runtime
    dataset_id, candidate_id = _build_upload_result(runtime, "up-formal", formal=True)

    cards = _cards(seeded_client)
    card = cards["up-formal"]
    assert card["workspace_kind"] == "user_upload"
    assert card["capabilities"] == {
        "data_summary": True,
        "experiments": True,
        "official_result": True,
        "native_volume": True,
    }
    assert card["primary_dataset"]["id"] == dataset_id
    assert card["primary_dataset"]["status"] == "validated"
    assert card["official_result"]["result_id"] == candidate_id
    assert card["official_result"]["materialized"] is True
    assert card["official_result"]["url"] == f"/results/{candidate_id}"
    assert card["provenance_summary"]["value_name"] == "电阻率"
    assert card["provenance_summary"]["value_unit"] == "ohm-m"

    workspace = seeded_client.get("/api/cases/up-formal/workspace")
    assert workspace.status_code == 200, workspace.text
    body = workspace.json()
    assert body["official_result"]["result_id"] == candidate_id
    assert body["primary_dataset"]["profile"]["mapping"]["value_name"] == "电阻率"
    assert "source_path" not in workspace.text


def test_upload_workspace_official_result_falls_back_to_latest_candidate(seeded_client):
    runtime = seeded_client.app.state.platform_runtime
    _, candidate_id = _build_upload_result(runtime, "up-plain", formal=False)

    workspace = seeded_client.get("/api/cases/up-plain/workspace")
    assert workspace.status_code == 200, workspace.text
    body = workspace.json()
    assert body["capabilities"]["official_result"] is True
    assert body["official_result"]["result_id"] == candidate_id
    assert body["official_result"]["materialized"] is True


def test_upload_workspace_without_dataset_has_no_experiment_capability(seeded_client):
    from geomodeling.platform import tables

    runtime = seeded_client.app.state.platform_runtime
    with runtime.session() as session:
        session.add(
            tables.Case(id="up-empty", name="空案例", case_type="generic", config_json="{}")
        )
        session.commit()
    workspace = seeded_client.get("/api/cases/up-empty/workspace")
    assert workspace.status_code == 200
    body = workspace.json()
    assert body["capabilities"] == {
        "data_summary": False,
        "experiments": False,
        "official_result": False,
        "native_volume": False,
    }
    assert body["primary_dataset"] is None
    assert body["official_result"] is None


def test_workspace_includes_abandoned_datasets(seeded_client):
    """Workspace DTO must include abandoned datasets for display."""
    from geomodeling.platform import tables
    from geomodeling.platform.schemas import DatasetStatus

    runtime = seeded_client.app.state.platform_runtime
    # Create a case with a validated v1 and abandoned v2
    with runtime.session() as session:
        session.add(
            tables.Case(id="up-abandon", name="放弃历史测试", case_type="generic", config_json="{}")
        )
        session.commit()

    # Upload v1
    resp = seeded_client.post(
        "/api/cases/up-abandon/datasets/uploads",
        files={"file": ("test.csv", b"x,y,v\n1,2,3\n", "text/csv")},
    )
    v1_id = resp.json()["id"]

    # Validate v1
    with runtime.session() as session:
        repo = tables  # use raw table for direct manipulation
        row = session.get(tables.DatasetVersion, v1_id)
        row.status = "validated"
        session.commit()

    # Upload v2
    resp = seeded_client.post(
        "/api/cases/up-abandon/datasets/uploads",
        files={"file": ("test2.csv", b"x,y,v\n4,5,6\n", "text/csv")},
    )
    v2_id = resp.json()["id"]

    # Abandon v2
    resp = seeded_client.post(f"/api/datasets/{v2_id}/abandon")
    assert resp.status_code == 200

    # Check workspace includes abandoned_datasets
    resp = seeded_client.get("/api/cases/up-abandon/workspace")
    assert resp.status_code == 200
    body = resp.json()
    assert "abandoned_datasets" in body
    assert len(body["abandoned_datasets"]) == 1
    assert body["abandoned_datasets"][0]["id"] == v2_id
    assert body["abandoned_datasets"][0]["status"] == "abandoned"
    # v1 should be in validated_datasets
    assert len(body["validated_datasets"]) == 1
    assert body["validated_datasets"][0]["id"] == v1_id
