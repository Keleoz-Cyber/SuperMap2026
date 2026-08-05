"""v0.7.0 合并前审查修复：预置官方成果身份保护（Blocker）。

写路径：read_only 案例的产品 select-formal 必须返回类型化 409，且不新增
FormalSelection、不改变官方结果；普通上传案例不受影响。
读路径：builtin_preset 的 featured_result 固定解析到 seed 创建的官方选择
（最早一条 + 确定性排序），历史污染选择不得改变首页/工作台/seed 回读。
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from geomodeling.platform.microseismic_preset import PRESET_CASE_ID


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
def preset_client(tmp_path_factory):
    return _make_client(tmp_path_factory.mktemp("preset-guard"), seed=True)


def _official_result_id(client) -> str:
    body = client.get(f"/api/cases/{PRESET_CASE_ID}/workspace").json()
    return body["official_result"]["result_id"]


def _selection_count(client, case_id: str) -> int:
    body = client.get(f"/api/cases/{case_id}/formal-selections").json()
    return len(body["selections"])


def _insert_pollution_selection(client, candidate_id: str) -> None:
    """模拟历史污染：直接向运行库插入一条较新的正式选择（夹具行为，非产品 API）。"""

    from geomodeling.platform import tables

    runtime = client.app.state.platform_runtime
    with runtime.session() as session:
        session.add(
            tables.FormalSelection(
                id=str(uuid.uuid4()),
                case_id=PRESET_CASE_ID,
                candidate_result_id=candidate_id,
                selected_by="pollution-fixture",
                note="模拟历史污染选择（较新 created_at）",
            )
        )
        session.commit()


def _build_user_candidate(client, runtime) -> str:
    """在预置案例中制造一个用户实验成功候选（正常产品链路）。"""

    from test_case_workspace_api import _build_upload_result  # noqa: PLC0415

    # 复用深状态夹具：在同一个 runtime 中向预置案例插入用户实验成功候选
    import threading

    import numpy as np
    import pandas as pd
    from geomodeling.modeling.runner import execute_run
    from geomodeling.platform import tables

    dataset_id = (
        client.get(f"/api/cases/{PRESET_CASE_ID}/workspace")
        .json()["primary_dataset"]["id"]
    )
    experiment_id = f"user-exp-{uuid.uuid4().hex[:8]}"
    run_id = f"user-run-{uuid.uuid4().hex[:8]}"
    params = {
        "algorithm": "idw",
        "dataset_version_id": dataset_id,
        "search_mode": "manual",
        "parameters": {"power": 2.0, "neighbor_count": 8},
        "validation": {"method": "spatial_kfold", "folds": 3, "seed": 11},
        "grid": None,
    }
    with runtime.session() as session:
        session.add(
            tables.Experiment(
                id=experiment_id,
                case_id=PRESET_CASE_ID,
                name="用户实验",
                params_json=tables.dumps_canonical(params),
            )
        )
        session.add(tables.Run(id=run_id, experiment_id=experiment_id, status="queued"))
        session.commit()
    outcome = execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "succeeded"
    with runtime.session() as session:
        return (
            session.query(tables.CandidateResult)
            .filter(tables.CandidateResult.run_id == run_id)
            .one()
            .id
        )


def test_read_only_preset_select_formal_returns_typed_409_without_side_effects(preset_client):
    runtime = preset_client.app.state.platform_runtime
    official_before = _official_result_id(preset_client)
    count_before = _selection_count(preset_client, PRESET_CASE_ID)

    user_candidate = _build_user_candidate(preset_client, runtime)
    response = preset_client.post(
        f"/api/results/{user_candidate}/select-formal",
        json={"note": "用户尝试顶替官方成果", "selected_by": "user"},
    )
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["error"]["code"] == "READ_ONLY_CASE_FORMAL_SELECTION"
    assert "D:\\" not in response.text and "/tmp" not in response.text
    # 无新增选择、官方结果不变
    assert _selection_count(preset_client, PRESET_CASE_ID) == count_before
    assert _official_result_id(preset_client) == official_before


def test_preset_featured_result_ignores_historical_pollution_selection(preset_client):
    runtime = preset_client.app.state.platform_runtime
    official = _official_result_id(preset_client)
    user_candidate = _build_user_candidate(preset_client, runtime)
    _insert_pollution_selection(preset_client, user_candidate)

    # 首页卡片、工作台、featured 解析全部仍指向官方候选
    cards = {c["case_id"]: c for c in preset_client.get("/api/cases").json()["cases"]}
    assert cards[PRESET_CASE_ID]["official_result"]["result_id"] == official
    workspace = preset_client.get(f"/api/cases/{PRESET_CASE_ID}/workspace").json()
    assert workspace["official_result"]["result_id"] == official

    from geomodeling.platform.repositories import featured_result_for_case

    with runtime.session() as session:
        featured = featured_result_for_case(session, PRESET_CASE_ID)
    assert featured is not None and featured.result_id == official


def test_seed_idempotent_read_returns_official_despite_pollution(preset_client):
    from geomodeling.platform.microseismic_preset import seed_microseismic_preset

    runtime = preset_client.app.state.platform_runtime
    official = _official_result_id(preset_client)
    user_candidate = _build_user_candidate(preset_client, runtime)
    _insert_pollution_selection(preset_client, user_candidate)

    record = seed_microseismic_preset(runtime)
    assert record.official_result.result_id == official


def _second_candidate(runtime, case_id: str) -> str:
    """在同一案例下构建第二个实验/运行/成功候选（用于最新选择语义验证）。"""

    import threading

    import numpy as np
    import pandas as pd
    from geomodeling.modeling.runner import execute_run
    from geomodeling.platform import tables

    suffix = uuid.uuid4().hex[:8]
    dataset_id, experiment_id, run_id = (
        f"{case_id}-ds2-{suffix}",
        f"{case_id}-exp2-{suffix}",
        f"{case_id}-run2-{suffix}",
    )
    rng = np.random.default_rng(13)
    n = 36
    frame = pd.DataFrame(
        {
            "source_row": np.arange(1, n + 1),
            "x": rng.uniform(-160.0, -40.0, n),
            "y": rng.uniform(220.0, 660.0, n),
            "z": rng.uniform(-800.0, -100.0, n),
            "value": rng.uniform(1.0, 3.0, n),
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
        "grid": None,
    }
    profile = {
        "mapping": {
            "dimension": "3d",
            "x": "x",
            "y": "y",
            "z": "z",
            "value": "value",
            "value_name": "属性",
            "value_unit": "u",
            "coordinate_kind": "local_linear",
        },
        "row_count": n,
        "valid_row_count": n,
        "invalid_row_count": 0,
        "source_sha256": "c" * 64,
        "standardized_sha256": "d" * 64,
        "standardized_path": str(target),
        "quality": {"status": "passed", "confirmed": True},
    }
    with runtime.session() as session:
        session.add(
            tables.DatasetVersion(
                id=dataset_id,
                case_id=case_id,
                version=2,
                status="validated",
                source_path="y.csv",
                profile_json=tables.dumps_canonical(profile),
            )
        )
        session.add(
            tables.Experiment(
                id=experiment_id,
                case_id=case_id,
                name="第二实验",
                params_json=tables.dumps_canonical(params),
            )
        )
        session.add(tables.Run(id=run_id, experiment_id=experiment_id, status="queued"))
        session.commit()
    outcome = execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "succeeded"
    with runtime.session() as session:
        return (
            session.query(tables.CandidateResult)
            .filter(tables.CandidateResult.run_id == run_id)
            .one()
            .id
        )


def test_upload_case_select_formal_still_works_and_latest_wins(tmp_path):
    client = _make_client(tmp_path, seed=False)
    runtime = client.app.state.platform_runtime
    from test_case_workspace_api import _build_upload_result  # noqa: PLC0415

    _, first = _build_upload_result(runtime, "up-guard", formal=False)
    resp = client.post(
        f"/api/results/{first}/select-formal",
        json={"note": "第一次选择", "selected_by": "user"},
    )
    assert resp.status_code == 201, resp.text
    second = _second_candidate(runtime, "up-guard")
    resp = client.post(
        f"/api/results/{second}/select-formal",
        json={"note": "第二次选择", "selected_by": "user"},
    )
    assert resp.status_code == 201, resp.text
    # 普通案例保持「最新正式选择优先」语义
    workspace = client.get("/api/cases/up-guard/workspace").json()
    assert workspace["official_result"]["result_id"] == second
    assert workspace["capabilities"]["official_result"] is True


def test_formal_selections_endpoint_exposes_selection_allowed(preset_client, tmp_path):
    body = preset_client.get(f"/api/cases/{PRESET_CASE_ID}/formal-selections").json()
    assert body["selection_allowed"] is False

    client = _make_client(tmp_path, seed=False)
    runtime = client.app.state.platform_runtime
    from test_case_workspace_api import _build_upload_result  # noqa: PLC0415

    _build_upload_result(runtime, "up-allowed", formal=True)
    body = client.get("/api/cases/up-allowed/formal-selections").json()
    assert body["selection_allowed"] is True


# ---------------------------------------------------------------------------
# 复审 Medium：官方锚点必须校验完整归属链（Candidate→Run→Experiment）
# ---------------------------------------------------------------------------

def _insert_aged_pollution_selection(
    client, candidate_id: str, *, created_at: str = "2020-01-01T00:00:00+00:00"
) -> None:
    """插入一条时间戳早于官方选择的污染选择（夹具行为，非产品 API）。"""

    from geomodeling.platform import tables

    runtime = client.app.state.platform_runtime
    with runtime.session() as session:
        session.add(
            tables.FormalSelection(
                id=str(uuid.uuid4()),
                case_id=PRESET_CASE_ID,
                candidate_result_id=candidate_id,
                selected_by="pollution-fixture",
                note="早于官方选择的污染行",
                created_at=created_at,
            )
        )
        session.commit()


def test_anchor_returns_none_when_earliest_selection_points_to_other_case(preset_client):
    from geomodeling.platform.repositories import featured_result_for_case
    from test_case_workspace_api import _build_upload_result  # noqa: PLC0415

    runtime = preset_client.app.state.platform_runtime
    # 其他案例的成功候选（归属链不属于预置案例）
    _, foreign_candidate = _build_upload_result(runtime, "up-foreign", formal=False)
    _insert_aged_pollution_selection(preset_client, foreign_candidate)

    with runtime.session() as session:
        featured = featured_result_for_case(session, PRESET_CASE_ID)
    assert featured is None
    workspace = preset_client.get(f"/api/cases/{PRESET_CASE_ID}/workspace").json()
    assert workspace["official_result"] is None


def test_anchor_returns_none_when_earliest_selection_run_not_succeeded(preset_client):
    from geomodeling.platform import tables
    from geomodeling.platform.microseismic_preset import SEED_SELECTED_BY
    from geomodeling.platform.repositories import featured_result_for_case

    runtime = preset_client.app.state.platform_runtime
    # 官方候选直接从 seed 登记的选择读取（不受其他测试污染行影响）
    with runtime.session() as session:
        seed_selection = (
            session.query(tables.FormalSelection)
            .filter(
                tables.FormalSelection.case_id == PRESET_CASE_ID,
                tables.FormalSelection.selected_by == SEED_SELECTED_BY,
            )
            .one()
        )
        official = seed_selection.candidate_result_id
    with runtime.session() as session:
        candidate = session.get(tables.CandidateResult, official)
        run = session.get(tables.Run, candidate.run_id)
        run.status = "failed"
        session.commit()
        session.add(
            tables.FormalSelection(
                id=str(uuid.uuid4()),
                case_id=PRESET_CASE_ID,
                candidate_result_id=official,
                selected_by="pollution-fixture",
                note="Run 非成功的早置污染行",
                created_at="2020-01-01T00:00:00+00:00",
            )
        )
        session.commit()

    with runtime.session() as session:
        featured = featured_result_for_case(session, PRESET_CASE_ID)
    assert featured is None

    # 恢复 Run 状态，避免影响同模块其他测试
    with runtime.session() as session:
        candidate = session.get(tables.CandidateResult, official)
        run = session.get(tables.Run, candidate.run_id)
        run.status = "succeeded"
        session.commit()
