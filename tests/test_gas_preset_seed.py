"""v0.8.0 第三批 Task 4：瓦斯含量预置只读 seed 链测试。

夹具策略：源 CSV 用 ``test_gas_preset_contract.write_gas_fixture``（确定性
合成 58 行硬合同，15 个 XY 采样位置）；官方基线是测试内构造的夹具基线
对象（满足 ``verify_official_baseline`` 全部合同：schema、source_sha256
绑定、空间 5 折验证合同且折数与 XY 柱数兼容、winner 算法 ∈
{idw, ordinary_kriging} 且参数在允许矩阵内、有限指标、粗网格覆盖源坐标
范围）。夹具网格刻意取粗分辨率（约 27 节点），把物化耗时控制在秒级；
真实数值基线由 Task 5 冻结进 ``config/presets/gas-official-baseline.json``，
本文件绝不创建该受控文件。

legacy 瓦斯卡（case_service 的 ``gas`` 卡，"暂缓"文案）随本任务类型化
退役：任何运行库状态下首页/案例列表都不再出现 ``builtin_legacy`` 卡；
未 seed 运行库出瓦斯预置描述卡（可见但能力全 false），seed 后由统一
seed 卡承载。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from geomodeling.platform import PlatformRuntime, tables
from geomodeling.platform.errors import (
    PRESET_BASELINE_INVALID,
    PRESET_SOURCE_INVALID,
    PlatformError,
)
from geomodeling.platform.gas_preset import (
    BASELINE_SCHEMA,
    DEFAULT_BASELINE_PATH,
    PRESET_BADGE,
    PRESET_CASE_ID,
    PRESET_VERSION,
    SEED_SELECTED_BY,
    SELECTION_RULE,
    VALIDATION_CONTRACT,
    OfficialBaseline,
    load_gas_preset,
    load_official_baseline,
    seed_gas_preset,
    verify_official_baseline,
)
from geomodeling.platform.repositories import featured_result_for_case
from test_gas_preset_contract import write_gas_fixture

#: 夹具基线 winner：idw 允许矩阵成员（真实 winner 由 Task 5 候选评估决出）
FIXTURE_WINNER_ALGORITHM = "idw"
FIXTURE_WINNER_PARAMETERS = {"power": 2.0, "neighbor_count": 24}

#: 夹具粗网格分辨率：夹具源 X/Y/Z 三轴节点约 3×3×3=27，控制物化耗时
FIXTURE_GRID_RESOLUTION = [35.0, 8.0, 26.0]

#: seed 写入 Case config_json 的工作台 provenance 文案（设计 §5 口径）
EXPECTED_DATA_FORM = "标准化散点 · 58 个合格样品"
EXPECTED_FIELDS = ["X", "Y", "Z", "CH4_content"]


@pytest.fixture()
def runtime(tmp_path: Path):
    rt = PlatformRuntime(tmp_path / "runtime")
    rt.initialize()
    yield rt
    rt.close()


@pytest.fixture()
def source_path(tmp_path: Path) -> Path:
    return write_gas_fixture(tmp_path / "gas-source.csv")


def _fixture_baseline_dict(source) -> dict:
    """满足 verify 合同的夹具基线文档（网格覆盖源坐标范围、粗分辨率）。"""

    frame = source.frame
    return {
        "schema": BASELINE_SCHEMA,
        "preset_version": PRESET_VERSION,
        "source_sha256": source.sha256,
        "standardized_rows": 58,
        "candidate_report_sha256": "e" * 64,
        "validation": dict(VALIDATION_CONTRACT),
        "selection_rule": list(SELECTION_RULE),
        "winner": {
            "algorithm": FIXTURE_WINNER_ALGORITHM,
            "parameters": dict(FIXTURE_WINNER_PARAMETERS),
            "metrics": {
                "rmse": 1.0,
                "mae": 0.5,
                "r2": 0.9,
                "bias": 0.01,
                "coverage": 1.0,
                "common_valid_count": 58,
            },
        },
        "grid": {
            "bounds": [
                [float(frame["X"].min()), float(frame["X"].max())],
                [float(frame["Y"].min()), float(frame["Y"].max())],
                [float(frame["Z"].min()), float(frame["Z"].max())],
            ],
            "resolution": list(FIXTURE_GRID_RESOLUTION),
            "max_cells": 100_000,
        },
        "selection_reason": "测试夹具基线：winner 取允许矩阵成员，粗网格控制物化耗时",
    }


def _fixture_baseline(source) -> OfficialBaseline:
    doc = _fixture_baseline_dict(source)
    return OfficialBaseline(
        schema=doc["schema"],
        source_sha256=doc["source_sha256"],
        standardized_rows=doc["standardized_rows"],
        candidate_report_sha256=doc["candidate_report_sha256"],
        validation=doc["validation"],
        selection_rule=tuple(doc["selection_rule"]),
        winner=doc["winner"],
        grid=doc["grid"],
        selection_reason=doc["selection_reason"],
        sha256="f" * 64,
    )


def _baseline_from_doc(doc: dict) -> OfficialBaseline:
    return OfficialBaseline(
        schema=doc["schema"],
        source_sha256=doc["source_sha256"],
        standardized_rows=doc["standardized_rows"],
        candidate_report_sha256=doc["candidate_report_sha256"],
        validation=doc["validation"],
        selection_rule=tuple(doc["selection_rule"]),
        winner=doc["winner"],
        grid=doc["grid"],
        selection_reason=doc["selection_reason"],
        sha256="f" * 64,
    )


def _write_fixture_baseline(path: Path, source) -> Path:
    path.write_text(
        json.dumps(_fixture_baseline_dict(source), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _case_config(runtime, case_id: str = PRESET_CASE_ID) -> dict:
    with runtime.session() as session:
        case = session.get(tables.Case, case_id)
        return tables.loads_canonical(case.config_json) if case is not None else {}


def _selections(runtime, case_id: str = PRESET_CASE_ID) -> list:
    with runtime.session() as session:
        return (
            session.query(tables.FormalSelection)
            .filter(tables.FormalSelection.case_id == case_id)
            .all()
        )


# ---------------------------------------------------------------------------
# 基线加载与验证（fail-closed 合同）
# ---------------------------------------------------------------------------


def test_default_baseline_path_is_repo_relative_and_missing_fails_closed(tmp_path: Path):
    """真实基线由 Task 5 冻结；本任务不创建受控文件，缺失 load 必须 fail-closed。"""

    assert DEFAULT_BASELINE_PATH == Path("config/presets/gas-official-baseline.json")
    assert not DEFAULT_BASELINE_PATH.is_absolute()
    with pytest.raises(PlatformError) as excinfo:
        load_official_baseline(tmp_path / "missing-baseline.json")
    assert excinfo.value.code == PRESET_BASELINE_INVALID
    assert excinfo.value.details["reason"] == "missing_baseline"
    assert excinfo.value.http_status == 409


def test_fixture_baseline_verifies_against_fixture_source(source_path: Path):
    source = load_gas_preset(source_path)
    baseline = _fixture_baseline(source)
    verify_official_baseline(source, baseline)
    assert baseline.winner["algorithm"] == "idw"
    assert baseline.validation == {"method": "spatial_kfold", "folds": 5, "seed": 20260723}


def test_load_baseline_from_json_roundtrip(tmp_path: Path, source_path: Path):
    source = load_gas_preset(source_path)
    baseline_path = _write_fixture_baseline(tmp_path / "baseline.json", source)
    baseline = load_official_baseline(baseline_path)
    verify_official_baseline(source, baseline)
    assert len(baseline.sha256) == 64
    assert baseline.sha256 != "f" * 64  # 指纹来自文件字节


@pytest.mark.parametrize(
    "mutate, reason",
    [
        pytest.param(lambda doc: doc.update(schema="wrong-schema"), "schema", id="schema"),
        pytest.param(
            lambda doc: doc.update(source_sha256="0" * 64), "source_sha256", id="source_sha256"
        ),
        pytest.param(
            lambda doc: doc.update(standardized_rows=57),
            "standardized_rows",
            id="standardized_rows",
        ),
        pytest.param(
            lambda doc: doc.update(validation={"method": "random", "folds": 3, "seed": 1}),
            "validation",
            id="validation",
        ),
        pytest.param(
            lambda doc: doc.update(
                validation={"method": "spatial_kfold", "folds": 6, "seed": 20260723}
            ),
            "validation",
            id="validation_folds_contract",
        ),
        pytest.param(
            lambda doc: doc["winner"].update(algorithm="dsi_like"),
            "winner_algorithm",
            id="winner_algorithm",
        ),
        pytest.param(
            lambda doc: doc["winner"].update(parameters={"power": 9.0, "neighbor_count": 3}),
            "winner_parameters",
            id="winner_parameters",
        ),
        pytest.param(
            lambda doc: doc["winner"]["metrics"].update(rmse=float("nan")),
            "winner_metrics",
            id="winner_metrics",
        ),
        pytest.param(
            lambda doc: doc.update(selection_rule=["r2_desc"]),
            "selection_rule",
            id="selection_rule",
        ),
        pytest.param(
            lambda doc: doc.update(candidate_report_sha256="not-a-sha"),
            "candidate_report_sha256",
            id="candidate_report_sha256",
        ),
    ],
)
def test_verify_baseline_rejects_contract_violations(source_path: Path, mutate, reason: str):
    source = load_gas_preset(source_path)
    doc = _fixture_baseline_dict(source)
    mutate(doc)
    baseline = _baseline_from_doc(doc)
    with pytest.raises(PlatformError) as excinfo:
        verify_official_baseline(source, baseline)
    assert excinfo.value.code == PRESET_BASELINE_INVALID
    assert excinfo.value.details["reason"] == reason


def test_verify_baseline_rejects_kriging_winner_outside_matrix(source_path: Path):
    """ordinary_kriging winner 合法，但参数必须落在允许矩阵内。"""

    source = load_gas_preset(source_path)
    doc = _fixture_baseline_dict(source)
    doc["winner"]["algorithm"] = "ordinary_kriging"
    doc["winner"]["parameters"] = {"variogram_model": "spherical", "neighbor_count": 16}
    verify_official_baseline(source, _baseline_from_doc(doc))

    doc["winner"]["parameters"] = {"variogram_model": "cubic", "neighbor_count": 16}
    with pytest.raises(PlatformError) as excinfo:
        verify_official_baseline(source, _baseline_from_doc(doc))
    assert excinfo.value.details["reason"] == "winner_parameters"


def test_verify_baseline_rejects_folds_incompatible_with_xy_columns(tmp_path: Path):
    """58 点源若 XY 采样位置少于 5 折，折数/柱数不兼容必须 fail-closed。"""

    import numpy as np
    import pandas as pd

    index = np.arange(58, dtype=np.int64)
    column = index % 4  # 仅 4 个 XY 采样位置，少于 folds=5
    level = index // 4
    frame = pd.DataFrame(
        {
            "X": 200.0 + column * 5.0,
            "Y": 300.0 + column * 2.5,
            "Z": 121.0 + level * 3.5,
            "CH4_content": 0.05 + index * 0.5,
        }
    )
    low_column_path = tmp_path / "gas-low-columns.csv"
    frame.to_csv(low_column_path, index=False, encoding="utf-8")
    source = load_gas_preset(low_column_path)
    assert source.frame[["X", "Y"]].drop_duplicates().shape[0] == 4

    doc = _fixture_baseline_dict(source)
    baseline = _baseline_from_doc(doc)
    with pytest.raises(PlatformError) as excinfo:
        verify_official_baseline(source, baseline)
    assert excinfo.value.code == PRESET_BASELINE_INVALID
    assert excinfo.value.details["reason"] == "validation_fold_columns"


def test_verify_baseline_rejects_grid_not_covering_source(source_path: Path):
    source = load_gas_preset(source_path)
    doc = _fixture_baseline_dict(source)
    doc["grid"]["bounds"][0] = [0.0, 100.0]  # X 上界远小于源 X 范围
    with pytest.raises(PlatformError) as excinfo:
        verify_official_baseline(source, _baseline_from_doc(doc))
    assert excinfo.value.code == PRESET_BASELINE_INVALID
    assert excinfo.value.details["reason"] == "grid_bounds_coverage"


def test_verify_baseline_rejects_grid_cells_over_cap(source_path: Path):
    source = load_gas_preset(source_path)
    doc = _fixture_baseline_dict(source)
    doc["grid"]["resolution"] = [0.01, 0.01, 0.01]  # 节点数远超 max_cells
    with pytest.raises(PlatformError) as excinfo:
        verify_official_baseline(source, _baseline_from_doc(doc))
    assert excinfo.value.details["reason"] == "grid_cells"


# ---------------------------------------------------------------------------
# seed：只读预置链创建
# ---------------------------------------------------------------------------


def test_seed_gas_creates_read_only_preset_chain(runtime, source_path: Path):
    source = load_gas_preset(source_path)
    baseline = _fixture_baseline(source)
    seeded = seed_gas_preset(runtime, source_path=source_path, baseline=baseline)

    assert seeded.case_id == PRESET_CASE_ID == "gas"
    assert seeded.workspace_kind == "builtin_preset"
    assert seeded.official_result.result_id
    assert seeded.official_result.materialized is True
    assert seeded.official_result.url == f"/results/{seeded.official_result.result_id}"
    assert seeded.source_sha256 == source.sha256
    assert seeded.baseline_sha256 == baseline.sha256

    with runtime.session() as session:
        dataset = session.get(tables.DatasetVersion, seeded.dataset_version_id)
        assert dataset.status == "validated"
        assert dataset.version == 1
        profile = tables.loads_canonical(dataset.profile_json)
        assert profile["row_count"] == 58
        assert profile["valid_row_count"] == 58
        mapping = profile["mapping"]
        assert mapping["x"] == "X"
        assert mapping["y"] == "Y"
        assert mapping["z"] == "Z"
        assert mapping["value"] == "CH4_content"
        assert mapping["value_name"] == "CH4_content"
        assert mapping["coordinate_kind"] == "local_linear"
        # CH4_content 单位 ml/g（用户权威确认，绝不静默换算）
        assert mapping["value_unit"] == "ml/g"

        candidate = session.get(tables.CandidateResult, seeded.official_result.result_id)
        assert candidate.status == "succeeded"
        assert candidate.grid_path is not None
        params = tables.loads_canonical(candidate.params_json)
        assert params == FIXTURE_WINNER_PARAMETERS

        run = session.get(tables.Run, seeded.run_id)
        assert run.status == "succeeded"
        experiment = session.get(tables.Experiment, seeded.experiment_id)
        experiment_params = tables.loads_canonical(experiment.params_json)
        assert experiment_params["algorithm"] == "idw"
        assert experiment_params["search_mode"] == "manual"
        assert experiment_params["validation"] == dict(VALIDATION_CONTRACT)
        assert experiment_params["grid"]["resolution"] == list(FIXTURE_GRID_RESOLUTION)

    selections = _selections(runtime)
    assert len(selections) == 1
    assert selections[0].candidate_result_id == seeded.official_result.result_id
    assert selections[0].selected_by == SEED_SELECTED_BY
    assert "用户实验不得改写" in selections[0].note

    config = _case_config(runtime)
    assert config["workspace_kind"] == "builtin_preset"
    assert config["read_only"] is True
    assert config["preset_version"] == PRESET_VERSION
    assert config["source_sha256"] == source.sha256
    assert config["baseline_sha256"] == baseline.sha256
    # 工作台 provenance 键由 seed 写入（legacy_adapter 读取，无需硬编码）
    assert config["data_form"] == EXPECTED_DATA_FORM
    assert config["fields"] == EXPECTED_FIELDS
    assert config["value_unit"] == "ml/g"
    assert config["coordinate_kind"] == "local_linear"
    assert config["badge"] == PRESET_BADGE

    with runtime.session() as session:
        featured = featured_result_for_case(session, PRESET_CASE_ID)
    assert featured is not None
    assert featured.result_id == seeded.official_result.result_id
    assert featured.materialized is True


def test_seed_is_idempotent_and_never_replaces_existing_official_selection(
    runtime, source_path: Path
):
    source = load_gas_preset(source_path)
    baseline = _fixture_baseline(source)
    first = seed_gas_preset(runtime, source_path=source_path, baseline=baseline)
    second = seed_gas_preset(runtime, source_path=source_path, baseline=baseline)
    assert second.official_result.result_id == first.official_result.result_id
    assert second.dataset_version_id == first.dataset_version_id
    assert len(_selections(runtime)) == 1
    with runtime.session() as session:
        assert (
            session.query(tables.Run)
            .filter(tables.Run.experiment_id == first.experiment_id)
            .count()
            == 1
        )


def test_seed_refuses_to_overwrite_when_fingerprints_differ(runtime, source_path: Path):
    source = load_gas_preset(source_path)
    baseline = _fixture_baseline(source)
    seeded = seed_gas_preset(runtime, source_path=source_path, baseline=baseline)
    with runtime.session() as session:
        case = session.get(tables.Case, PRESET_CASE_ID)
        config = tables.loads_canonical(case.config_json)
        config["baseline_sha256"] = "0" * 64
        case.config_json = tables.dumps_canonical(config)
        session.commit()
    with pytest.raises(PlatformError) as excinfo:
        seed_gas_preset(runtime, source_path=source_path, baseline=baseline)
    assert excinfo.value.code == PRESET_BASELINE_INVALID
    # 原正式选择保持不变，绝不覆盖
    selections = _selections(runtime)
    assert len(selections) == 1
    assert selections[0].candidate_result_id == seeded.official_result.result_id


def test_seed_refuses_to_overwrite_when_preset_version_differs(runtime, source_path: Path):
    source = load_gas_preset(source_path)
    baseline = _fixture_baseline(source)
    seeded = seed_gas_preset(runtime, source_path=source_path, baseline=baseline)
    with runtime.session() as session:
        case = session.get(tables.Case, PRESET_CASE_ID)
        config = tables.loads_canonical(case.config_json)
        config["preset_version"] = "gas-ch4-58/v0-stale"
        case.config_json = tables.dumps_canonical(config)
        session.commit()
    with pytest.raises(PlatformError) as excinfo:
        seed_gas_preset(runtime, source_path=source_path, baseline=baseline)
    assert excinfo.value.code == PRESET_BASELINE_INVALID
    assert excinfo.value.details["reason"] == "preset_version"
    assert len(_selections(runtime)) == 1
    assert _selections(runtime)[0].candidate_result_id == seeded.official_result.result_id


def test_seed_concurrent_calls_never_create_double_selection(runtime, source_path: Path):
    source = load_gas_preset(source_path)
    baseline = _fixture_baseline(source)
    outcomes = []

    def worker():
        outcomes.append(
            seed_gas_preset(runtime, source_path=source_path, baseline=baseline)
            .official_result.result_id
        )

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=600)
    assert len(outcomes) == 2
    assert len(set(outcomes)) == 1
    assert len(_selections(runtime)) == 1


def test_seed_failure_leaves_no_partial_state(runtime, source_path: Path, monkeypatch):
    source = load_gas_preset(source_path)
    baseline = _fixture_baseline(source)

    def boom(*args, **kwargs):
        raise RuntimeError("injected runner failure")

    monkeypatch.setattr("geomodeling.platform.gas_preset.execute_run", boom, raising=False)
    with pytest.raises(Exception, match="injected runner failure"):
        seed_gas_preset(runtime, source_path=source_path, baseline=baseline)
    with runtime.session() as session:
        assert session.get(tables.Case, PRESET_CASE_ID) is None
        assert session.query(tables.DatasetVersion).count() == 0
        assert session.query(tables.Experiment).count() == 0
        assert session.query(tables.Run).count() == 0
        assert session.query(tables.CandidateResult).count() == 0
        assert session.query(tables.FormalSelection).count() == 0
    assert not (runtime.settings.datasets_dir / PRESET_CASE_ID).exists()
    assert not (runtime.settings.uploads_dir / PRESET_CASE_ID).exists()


def test_seed_without_baseline_fails_closed_when_missing(
    runtime, source_path: Path, tmp_path: Path
):
    """显式基线路径缺失：seed 必须 fail-closed 且不留残留。"""

    with pytest.raises(PlatformError) as excinfo:
        seed_gas_preset(
            runtime, source_path=source_path, baseline_path=tmp_path / "missing-baseline.json"
        )
    assert excinfo.value.code == PRESET_BASELINE_INVALID
    assert excinfo.value.details["reason"] == "missing_baseline"
    with runtime.session() as session:
        assert session.get(tables.Case, PRESET_CASE_ID) is None


def test_seed_rejects_baseline_bound_to_other_source(runtime, source_path: Path):
    source = load_gas_preset(source_path)
    doc = _fixture_baseline_dict(source)
    doc["source_sha256"] = "0" * 64
    baseline = _baseline_from_doc(doc)
    with pytest.raises(PlatformError) as excinfo:
        seed_gas_preset(runtime, source_path=source_path, baseline=baseline)
    assert excinfo.value.code == PRESET_BASELINE_INVALID
    with runtime.session() as session:
        assert session.get(tables.Case, PRESET_CASE_ID) is None


def test_seed_via_baseline_path(runtime, tmp_path: Path, source_path: Path):
    """baseline 路径注入：从 JSON 文件加载并验证（生产默认路径同通道）。"""

    source = load_gas_preset(source_path)
    baseline_path = _write_fixture_baseline(tmp_path / "baseline.json", source)
    seeded = seed_gas_preset(runtime, source_path=source_path, baseline_path=baseline_path)
    assert seeded.workspace_kind == "builtin_preset"
    assert seeded.official_result.result_id


# ---------------------------------------------------------------------------
# API：只读保护、案例卡身份与 legacy 瓦斯卡退役
# ---------------------------------------------------------------------------


def _make_client(tmp_path: Path, *, seed: bool):
    from fastapi.testclient import TestClient

    from geomodeling.api.app import create_app
    from geomodeling.api.deps import (
        ApiSettings,
        get_app_config,
        get_iserver_client,
        get_settings,
    )
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
        source_path = write_gas_fixture(tmp_path / "gas-source.csv")
        source = load_gas_preset(source_path)
        seed_gas_preset(runtime, source_path=source_path, baseline=_fixture_baseline(source))
    app.state.platform_runtime = runtime
    return TestClient(app)


@pytest.fixture(scope="module")
def seeded_client(tmp_path_factory):
    return _make_client(tmp_path_factory.mktemp("gas-seeded"), seed=True)


@pytest.fixture()
def fresh_client(tmp_path):
    return _make_client(tmp_path, seed=False)


def _cards(client) -> dict:
    response = client.get("/api/cases")
    assert response.status_code == 200, response.text
    return {card["case_id"]: card for card in response.json()["cases"]}


def _build_user_candidate(client, runtime) -> str:
    """在瓦斯预置案例中制造一个用户实验成功候选（正常产品链路）。"""

    import uuid

    from geomodeling.modeling.runner import execute_run

    with runtime.session() as session:
        dataset = (
            session.query(tables.DatasetVersion)
            .filter(tables.DatasetVersion.case_id == PRESET_CASE_ID)
            .one()
        )
        dataset_id = dataset.id
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


def test_seeded_gas_appears_once_as_builtin_preset_card(seeded_client):
    response = seeded_client.get("/api/cases")
    assert response.status_code == 200, response.text
    cards = [card for card in response.json()["cases"] if card["case_id"] == "gas"]
    assert len(cards) == 1, "seed 后 gas 只能出现一张统一 seed 卡"
    card = cards[0]
    assert card["workspace_kind"] == "builtin_preset"
    assert card["source_kind"] == "builtin_preset"
    assert card["status"] == "active"
    assert card["capabilities"] == {
        "data_summary": True,
        "experiments": True,
        "official_result": True,
        "native_volume": True,
    }
    assert card["official_result"]["materialized"] is True
    assert card["official_result"]["url"].startswith("/results/")
    assert card["primary_dataset"]["status"] == "validated"
    assert card["primary_dataset"]["profile"]["mapping"]["value"] == "CH4_content"
    provenance = card["provenance_summary"]
    assert provenance["preset_version"] == PRESET_VERSION
    assert provenance["data_form"] == EXPECTED_DATA_FORM
    assert provenance["fields"] == EXPECTED_FIELDS
    assert provenance["value_unit"] == "ml/g"
    assert provenance["coordinate_kind"] == "local_linear"
    assert provenance["badge"] == PRESET_BADGE


def test_unseeded_runtime_shows_gas_preset_descriptor_card(fresh_client):
    """v0.8.0 第三批 Task 4：legacy 瓦斯卡退役；未 seed 运行库改出预置描述卡。

    描述卡可见但能力全 false（同微震/电阻率预置描述符模式）；provenance 取
    入库基线事实（gas_preset 模块常量：58 个合格样品、X/Y/Z/CH4_content、
    ml/g、局部线性米制），绝无绝对路径与"暂缓"文案，绝不读外部文件。
    """

    cards = _cards(fresh_client)
    card = cards["gas"]
    assert card["workspace_kind"] == "builtin_preset"
    assert card["source_kind"] == "builtin_preset"
    assert card["status"] == "initialization_required"
    assert card["capabilities"] == {
        "data_summary": False,
        "experiments": False,
        "official_result": False,
        "native_volume": False,
    }
    assert card["official_result"] is None
    assert card["primary_dataset"] is None
    provenance = card["provenance_summary"]
    assert provenance["preset_version"] == PRESET_VERSION
    assert provenance["data_form"] == EXPECTED_DATA_FORM
    assert provenance["fields"] == EXPECTED_FIELDS
    assert provenance["value_unit"] == "ml/g"
    assert provenance["coordinate_kind"] == "local_linear"
    assert provenance["coordinate_unit"] == "m"  # 局部线性米制
    assert provenance["badge"] == PRESET_BADGE
    serialized = json.dumps(card, ensure_ascii=False)
    assert "暂缓" not in serialized
    assert "parked" not in serialized
    assert ":\\" not in serialized


def test_no_legacy_card_remains_in_case_list(seeded_client, fresh_client):
    """gas 是最后一张 legacy 卡：退役后任何运行库状态下都没有 builtin_legacy 卡。"""

    for client in (seeded_client, fresh_client):
        response = client.get("/api/cases")
        assert response.status_code == 200, response.text
        body = response.json()
        legacy = [card for card in body["cases"] if card["source_kind"] == "builtin_legacy"]
        assert legacy == [], "首页/案例列表不再出现任何 legacy 卡"
        assert "暂缓" not in response.text
        assert "parked" not in response.text


def test_three_preset_cards_coexist(fresh_client):
    """未 seed 运行库：微震/电阻率/瓦斯三张预置描述卡并存（同一形态）。"""

    cards = _cards(fresh_client)
    for case_id in ("builtin-microseismic-vx-1911", "resistivity", "gas"):
        card = cards[case_id]
        assert card["workspace_kind"] == "builtin_preset"
        assert card["source_kind"] == "builtin_preset"
        assert card["status"] == "initialization_required"
        assert card["capabilities"]["experiments"] is False
        assert card["capabilities"]["official_result"] is False


def test_gas_workspace_is_builtin_preset(seeded_client):
    """已 seed 运行库返回统一 builtin_preset 工作台 DTO。"""

    response = seeded_client.get("/api/cases/gas/workspace")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["workspace_kind"] == "builtin_preset"
    assert body["source_kind"] == "builtin_preset"
    assert body["data_preparation"]["state"] == "validated"
    assert body["capabilities"] == {
        "data_summary": True,
        "experiments": True,
        "official_result": True,
        "native_volume": True,
    }
    assert body["primary_dataset"]["status"] == "validated"
    assert body["primary_dataset"]["profile"]["mapping"]["value"] == "CH4_content"
    assert body["primary_dataset"]["profile"]["mapping"]["value_unit"] == "ml/g"
    assert body["official_result"]["materialized"] is True
    assert body["official_result"]["url"].startswith("/results/")
    provenance = body["provenance_summary"]
    assert provenance["preset_version"] == PRESET_VERSION
    assert provenance["data_form"] == EXPECTED_DATA_FORM
    assert provenance["fields"] == EXPECTED_FIELDS
    assert provenance["value_unit"] == "ml/g"
    assert provenance["coordinate_kind"] == "local_linear"
    assert provenance["badge"] == PRESET_BADGE
    # 不再落回 legacy 卡字段
    assert "v03_stage" not in body
    assert "unit_note" not in body
    assert "source_path" not in response.text


def test_unseeded_gas_workspace_returns_preset_not_initialized(fresh_client):
    """未 seed 运行库：微震/电阻率同款"预置未初始化"语义，不再返回 legacy 工作台。"""

    response = fresh_client.get("/api/cases/gas/workspace")
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "PRESET_NOT_INITIALIZED"


def test_read_only_preset_rejects_user_formal_selection(seeded_client):
    runtime = seeded_client.app.state.platform_runtime
    official_before = _cards(seeded_client)["gas"]["official_result"]["result_id"]
    selections_before = len(_selections(runtime))

    user_candidate = _build_user_candidate(seeded_client, runtime)
    response = seeded_client.post(
        f"/api/results/{user_candidate}/select-formal",
        json={"note": "用户尝试顶替官方成果", "selected_by": "user"},
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "READ_ONLY_CASE_FORMAL_SELECTION"
    # 无新增选择、官方结果不变
    assert len(_selections(runtime)) == selections_before
    assert _cards(seeded_client)["gas"]["official_result"]["result_id"] == official_before


def test_public_payloads_never_leak_absolute_paths(seeded_client, source_path: Path, tmp_path):
    cards_text = seeded_client.get("/api/cases").text
    assert ":\\" not in cards_text
    assert str(tmp_path) not in cards_text
    assert "source_path" not in cards_text

    # 错误 details 同样无绝对路径（指纹篡改 fail-closed 的公共载荷）
    source = load_gas_preset(source_path)
    doc = _fixture_baseline_dict(source)
    doc["source_sha256"] = "0" * 64
    with pytest.raises(PlatformError) as excinfo:
        verify_official_baseline(source, _baseline_from_doc(doc))
    payload_text = json.dumps(excinfo.value.public_payload(), ensure_ascii=False)
    assert ":\\" not in payload_text
    assert str(tmp_path) not in payload_text


# ---------------------------------------------------------------------------
# CLI：seed-gas 维护命令
# ---------------------------------------------------------------------------


def test_cli_seed_gas_success_outputs_logical_identity(tmp_path: Path):
    from typer.testing import CliRunner

    from geomodeling.preset_cli import preset_app

    source_path = write_gas_fixture(tmp_path / "gas-source.csv")
    source = load_gas_preset(source_path)
    baseline_path = _write_fixture_baseline(tmp_path / "baseline.json", source)
    data_dir = tmp_path / "cli-runtime"

    result = CliRunner().invoke(
        preset_app,
        [
            "seed-gas",
            "--source",
            str(source_path),
            "--baseline",
            str(baseline_path),
            "--data-dir",
            str(data_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["case_id"] == "gas"
    assert payload["workspace_kind"] == "builtin_preset"
    assert payload["official_result"]["result_id"]
    assert payload["source_sha256"] == source.sha256
    # 输出只含逻辑身份，绝无本机绝对路径
    assert ":\\" not in result.output
    assert str(tmp_path) not in result.output


def test_cli_seed_gas_missing_source_fails_closed(tmp_path: Path):
    from typer.testing import CliRunner

    from geomodeling.preset_cli import preset_app

    result = CliRunner().invoke(
        preset_app,
        [
            "seed-gas",
            "--source",
            str(tmp_path / "missing.csv"),
            "--data-dir",
            str(tmp_path / "cli-runtime"),
        ],
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error"]["code"] == PRESET_SOURCE_INVALID
    assert ":\\" not in payload["error"]["details"].get("reason", "")


def test_cli_seed_gas_missing_baseline_fails_closed(tmp_path: Path):
    from typer.testing import CliRunner

    from geomodeling.preset_cli import preset_app

    source_path = write_gas_fixture(tmp_path / "gas-source.csv")
    result = CliRunner().invoke(
        preset_app,
        [
            "seed-gas",
            "--source",
            str(source_path),
            "--baseline",
            str(tmp_path / "missing-baseline.json"),
            "--data-dir",
            str(tmp_path / "cli-runtime"),
        ],
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error"]["code"] == PRESET_BASELINE_INVALID
    assert payload["error"]["details"]["reason"] == "missing_baseline"
