"""v0.8.0 Task 2：电阻率散点预置只读 seed 链测试。

夹具策略：源 CSV 用 ``test_resistivity_preset.write_resistivity_fixture``
（确定性合成 17,549 行硬合同）；官方基线是测试内构造的夹具基线对象
（满足 ``verify_official_baseline`` 全部合同：schema、source_sha256 绑定、
空间 5 折验证合同、winner 参数在允许矩阵内、有限指标、粗网格覆盖源坐标
范围）。夹具网格刻意取粗分辨率（约 168 节点），把物化耗时控制在秒级；
真实数值基线由 Task 5 冻结进 ``config/presets/resistivity-official-baseline.json``，
本文件绝不创建该受控文件。
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
from geomodeling.platform.repositories import featured_result_for_case
from geomodeling.platform.resistivity_preset import (
    BASELINE_SCHEMA,
    DEFAULT_BASELINE_PATH,
    PRESET_CASE_ID,
    PRESET_VERSION,
    SEED_SELECTED_BY,
    SELECTION_RULE,
    VALIDATION_CONTRACT,
    OfficialBaseline,
    load_official_baseline,
    load_resistivity_preset,
    seed_resistivity_preset,
    verify_official_baseline,
)
from test_resistivity_preset import write_resistivity_fixture

#: 夹具基线 winner：允许矩阵成员（真实 winner 由 Task 5 候选分析决出）
FIXTURE_WINNER_PARAMETERS = {
    "variogram_model": "spherical",
    "neighbor_count": 12,
    "z_scale": 1.0,
}

#: 夹具粗网格分辨率：X/Y/Z 三轴节点约 7×4×6=168，控制物化耗时
FIXTURE_GRID_RESOLUTION = [500.0, 10.0, 200.0]


@pytest.fixture()
def runtime(tmp_path: Path):
    rt = PlatformRuntime(tmp_path / "runtime")
    rt.initialize()
    yield rt
    rt.close()


@pytest.fixture()
def source_path(tmp_path: Path) -> Path:
    return write_resistivity_fixture(tmp_path / "rho-source.csv", rows=17_549)


def _fixture_baseline_dict(source) -> dict:
    """满足 verify 合同的夹具基线文档（网格覆盖源坐标范围、粗分辨率）。"""

    frame = source.frame
    return {
        "schema": BASELINE_SCHEMA,
        "preset_version": PRESET_VERSION,
        "source_sha256": source.sha256,
        "candidate_report_sha256": "e" * 64,
        "validation": dict(VALIDATION_CONTRACT),
        "selection_rule": list(SELECTION_RULE),
        "winner": {
            "algorithm": "ordinary_kriging",
            "parameters": dict(FIXTURE_WINNER_PARAMETERS),
            "metrics": {
                "rmse": 1.0,
                "mae": 0.5,
                "r2": 0.9,
                "bias": 0.01,
                "coverage": 1.0,
                "common_valid_count": 17_549,
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


def test_default_baseline_path_is_repo_relative_and_missing_until_task5():
    """Task 5 才冻结真实基线；默认路径缺失时 load 必须 fail-closed。"""

    assert DEFAULT_BASELINE_PATH == Path("config/presets/resistivity-official-baseline.json")
    assert not DEFAULT_BASELINE_PATH.is_file(), "Task 2 绝不创建真实基线文件"
    with pytest.raises(PlatformError) as excinfo:
        load_official_baseline(DEFAULT_BASELINE_PATH)
    assert excinfo.value.code == PRESET_BASELINE_INVALID
    assert excinfo.value.details["reason"] == "missing_baseline"
    assert excinfo.value.http_status == 409


def test_fixture_baseline_verifies_against_fixture_source(source_path: Path):
    source = load_resistivity_preset(source_path)
    baseline = _fixture_baseline(source)
    verify_official_baseline(source, baseline)
    assert baseline.winner["algorithm"] == "ordinary_kriging"
    assert baseline.validation == {"method": "spatial_kfold", "folds": 5, "seed": 20260723}


def test_load_baseline_from_json_roundtrip(tmp_path: Path, source_path: Path):
    source = load_resistivity_preset(source_path)
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
            lambda doc: doc.update(validation={"method": "random", "folds": 3, "seed": 1}),
            "validation",
            id="validation",
        ),
        pytest.param(
            lambda doc: doc["winner"].update(parameters={"variogram_model": "cubic"}),
            "winner_parameters",
            id="winner_parameters",
        ),
        pytest.param(
            lambda doc: doc["winner"].update(algorithm="idw"),
            "winner_parameters",
            id="winner_algorithm",
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
    ],
)
def test_verify_baseline_rejects_contract_violations(
    source_path: Path, mutate, reason: str
):
    source = load_resistivity_preset(source_path)
    doc = _fixture_baseline_dict(source)
    mutate(doc)
    baseline = OfficialBaseline(
        schema=doc["schema"],
        source_sha256=doc["source_sha256"],
        candidate_report_sha256=doc["candidate_report_sha256"],
        validation=doc["validation"],
        selection_rule=tuple(doc["selection_rule"]),
        winner=doc["winner"],
        grid=doc["grid"],
        selection_reason=doc["selection_reason"],
        sha256="f" * 64,
    )
    with pytest.raises(PlatformError) as excinfo:
        verify_official_baseline(source, baseline)
    assert excinfo.value.code == PRESET_BASELINE_INVALID
    assert excinfo.value.details["reason"] == reason


def test_verify_baseline_rejects_grid_not_covering_source(source_path: Path):
    source = load_resistivity_preset(source_path)
    doc = _fixture_baseline_dict(source)
    doc["grid"]["bounds"][0] = [0.0, 100.0]  # X 上界远小于源 X 范围
    baseline = OfficialBaseline(
        schema=doc["schema"],
        source_sha256=doc["source_sha256"],
        candidate_report_sha256=doc["candidate_report_sha256"],
        validation=doc["validation"],
        selection_rule=tuple(doc["selection_rule"]),
        winner=doc["winner"],
        grid=doc["grid"],
        selection_reason=doc["selection_reason"],
        sha256="f" * 64,
    )
    with pytest.raises(PlatformError) as excinfo:
        verify_official_baseline(source, baseline)
    assert excinfo.value.code == PRESET_BASELINE_INVALID
    assert excinfo.value.details["reason"] == "grid_bounds_coverage"


# ---------------------------------------------------------------------------
# seed：只读预置链创建
# ---------------------------------------------------------------------------


def test_seed_resistivity_creates_read_only_preset_chain(runtime, source_path: Path):
    source = load_resistivity_preset(source_path)
    baseline = _fixture_baseline(source)
    seeded = seed_resistivity_preset(runtime, source_path=source_path, baseline=baseline)

    assert seeded.case_id == PRESET_CASE_ID == "resistivity"
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
        assert profile["row_count"] == 17_549
        assert profile["valid_row_count"] == 17_549
        mapping = profile["mapping"]
        assert mapping["x"] == "X"
        assert mapping["y"] == "Y"
        assert mapping["z"] == "Z"
        assert mapping["value"] == "RHO"
        assert mapping["value_name"] == "RHO"
        assert mapping["coordinate_kind"] == "local_linear"
        # RHO 单位待来源确认：诚实表述，绝不写未确认单位
        assert mapping["value_unit"] == "RHO 单位待来源确认"

        candidate = session.get(tables.CandidateResult, seeded.official_result.result_id)
        assert candidate.status == "succeeded"
        assert candidate.grid_path is not None
        params = tables.loads_canonical(candidate.params_json)
        assert params == FIXTURE_WINNER_PARAMETERS

        run = session.get(tables.Run, seeded.run_id)
        assert run.status == "succeeded"
        experiment = session.get(tables.Experiment, seeded.experiment_id)
        experiment_params = tables.loads_canonical(experiment.params_json)
        assert experiment_params["algorithm"] == "ordinary_kriging"
        assert experiment_params["search_mode"] == "manual"
        assert experiment_params["validation"] == dict(VALIDATION_CONTRACT)

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
    assert config["data_form"] == "三维 X/Y/Z/RHO（局部工程坐标）"
    assert config["value_unit"] == "RHO 单位待来源确认"
    assert config["coordinate_kind"] == "local_linear"
    assert config["badge"] == "散点预置 · 官方普通克里金成果"

    with runtime.session() as session:
        featured = featured_result_for_case(session, PRESET_CASE_ID)
    assert featured is not None
    assert featured.result_id == seeded.official_result.result_id
    assert featured.materialized is True


def test_seed_is_idempotent_and_never_replaces_existing_official_selection(
    runtime, source_path: Path
):
    source = load_resistivity_preset(source_path)
    baseline = _fixture_baseline(source)
    first = seed_resistivity_preset(runtime, source_path=source_path, baseline=baseline)
    second = seed_resistivity_preset(runtime, source_path=source_path, baseline=baseline)
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
    source = load_resistivity_preset(source_path)
    baseline = _fixture_baseline(source)
    seeded = seed_resistivity_preset(runtime, source_path=source_path, baseline=baseline)
    with runtime.session() as session:
        case = session.get(tables.Case, PRESET_CASE_ID)
        config = tables.loads_canonical(case.config_json)
        config["baseline_sha256"] = "0" * 64
        case.config_json = tables.dumps_canonical(config)
        session.commit()
    with pytest.raises(PlatformError) as excinfo:
        seed_resistivity_preset(runtime, source_path=source_path, baseline=baseline)
    assert excinfo.value.code == PRESET_BASELINE_INVALID
    # 原正式选择保持不变，绝不覆盖
    selections = _selections(runtime)
    assert len(selections) == 1
    assert selections[0].candidate_result_id == seeded.official_result.result_id


def test_seed_concurrent_calls_never_create_double_selection(runtime, source_path: Path):
    source = load_resistivity_preset(source_path)
    baseline = _fixture_baseline(source)
    outcomes = []

    def worker():
        outcomes.append(
            seed_resistivity_preset(
                runtime, source_path=source_path, baseline=baseline
            ).official_result.result_id
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
    source = load_resistivity_preset(source_path)
    baseline = _fixture_baseline(source)

    def boom(*args, **kwargs):
        raise RuntimeError("injected runner failure")

    monkeypatch.setattr(
        "geomodeling.platform.resistivity_preset.execute_run", boom, raising=False
    )
    with pytest.raises(Exception, match="injected runner failure"):
        seed_resistivity_preset(runtime, source_path=source_path, baseline=baseline)
    with runtime.session() as session:
        assert session.get(tables.Case, PRESET_CASE_ID) is None
        assert session.query(tables.DatasetVersion).count() == 0
        assert session.query(tables.Experiment).count() == 0
        assert session.query(tables.Run).count() == 0
        assert session.query(tables.CandidateResult).count() == 0
        assert session.query(tables.FormalSelection).count() == 0
    assert not (runtime.settings.datasets_dir / PRESET_CASE_ID).exists()
    assert not (runtime.settings.uploads_dir / PRESET_CASE_ID).exists()


def test_seed_without_baseline_fails_closed_when_default_missing(runtime, source_path: Path):
    """默认基线文件缺失（Task 5 前）：seed 必须 fail-closed 且不留残留。"""

    with pytest.raises(PlatformError) as excinfo:
        seed_resistivity_preset(runtime, source_path=source_path)
    assert excinfo.value.code == PRESET_BASELINE_INVALID
    assert excinfo.value.details["reason"] == "missing_baseline"
    with runtime.session() as session:
        assert session.get(tables.Case, PRESET_CASE_ID) is None


def test_seed_rejects_baseline_bound_to_other_source(runtime, source_path: Path):
    source = load_resistivity_preset(source_path)
    doc = _fixture_baseline_dict(source)
    doc["source_sha256"] = "0" * 64
    baseline = OfficialBaseline(
        schema=doc["schema"],
        source_sha256=doc["source_sha256"],
        candidate_report_sha256=doc["candidate_report_sha256"],
        validation=doc["validation"],
        selection_rule=tuple(doc["selection_rule"]),
        winner=doc["winner"],
        grid=doc["grid"],
        selection_reason=doc["selection_reason"],
        sha256="f" * 64,
    )
    with pytest.raises(PlatformError) as excinfo:
        seed_resistivity_preset(runtime, source_path=source_path, baseline=baseline)
    assert excinfo.value.code == PRESET_BASELINE_INVALID
    with runtime.session() as session:
        assert session.get(tables.Case, PRESET_CASE_ID) is None


def test_seed_via_baseline_path(runtime, tmp_path: Path, source_path: Path):
    """baseline 路径注入：从 JSON 文件加载并验证（生产默认路径同通道）。"""

    source = load_resistivity_preset(source_path)
    baseline_path = _write_fixture_baseline(tmp_path / "baseline.json", source)
    seeded = seed_resistivity_preset(
        runtime, source_path=source_path, baseline_path=baseline_path
    )
    assert seeded.workspace_kind == "builtin_preset"
    assert seeded.official_result.result_id


# ---------------------------------------------------------------------------
# API：只读保护与案例卡身份
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
        source_path = write_resistivity_fixture(tmp_path / "rho-source.csv", rows=17_549)
        source = load_resistivity_preset(source_path)
        seed_resistivity_preset(
            runtime, source_path=source_path, baseline=_fixture_baseline(source)
        )
    app.state.platform_runtime = runtime
    return TestClient(app)


@pytest.fixture(scope="module")
def seeded_client(tmp_path_factory):
    return _make_client(tmp_path_factory.mktemp("rho-seeded"), seed=True)


@pytest.fixture()
def fresh_client(tmp_path):
    return _make_client(tmp_path, seed=False)


def _cards(client) -> dict:
    response = client.get("/api/cases")
    assert response.status_code == 200, response.text
    return {card["case_id"]: card for card in response.json()["cases"]}


def _build_user_candidate(client, runtime) -> str:
    """在电阻率预置案例中制造一个用户实验成功候选（正常产品链路）。"""

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


def test_seeded_resistivity_appears_once_as_builtin_preset_card(seeded_client):
    response = seeded_client.get("/api/cases")
    assert response.status_code == 200, response.text
    cards = [card for card in response.json()["cases"] if card["case_id"] == "resistivity"]
    assert len(cards) == 1, "seed 后 resistivity 只能出现一张统一 seed 卡"
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
    assert card["primary_dataset"]["profile"]["mapping"]["value"] == "RHO"
    provenance = card["provenance_summary"]
    assert provenance["preset_version"] == PRESET_VERSION
    assert provenance["data_form"] == "三维 X/Y/Z/RHO（局部工程坐标）"
    assert provenance["value_unit"] == "RHO 单位待来源确认"
    assert provenance["coordinate_kind"] == "local_linear"
    assert provenance["badge"] == "散点预置 · 官方普通克里金成果"


def test_unseeded_runtime_keeps_legacy_resistivity_card(fresh_client):
    """未 seed 运行库保持 Task 6 前现状：只有 builtin_legacy 电阻率卡。"""

    cards = _cards(fresh_client)
    card = cards["resistivity"]
    assert card["workspace_kind"] == "builtin_legacy"
    assert card["capabilities"]["native_volume"] is True
    assert card["capabilities"]["experiments"] is False
    assert card["official_result"] is None


def test_read_only_preset_rejects_user_formal_selection(seeded_client):
    runtime = seeded_client.app.state.platform_runtime
    official_before = _cards(seeded_client)["resistivity"]["official_result"]["result_id"]
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
    assert _cards(seeded_client)["resistivity"]["official_result"]["result_id"] == official_before


def test_public_payloads_never_leak_absolute_paths(seeded_client, source_path: Path, tmp_path):
    cards_text = seeded_client.get("/api/cases").text
    assert ":\\" not in cards_text
    assert str(tmp_path) not in cards_text
    assert "source_path" not in cards_text

    # 错误 details 同样无绝对路径（指纹篡改 fail-closed 的公共载荷）
    source = load_resistivity_preset(source_path)
    doc = _fixture_baseline_dict(source)
    doc["source_sha256"] = "0" * 64
    baseline = OfficialBaseline(
        schema=doc["schema"],
        source_sha256=doc["source_sha256"],
        candidate_report_sha256=doc["candidate_report_sha256"],
        validation=doc["validation"],
        selection_rule=tuple(doc["selection_rule"]),
        winner=doc["winner"],
        grid=doc["grid"],
        selection_reason=doc["selection_reason"],
        sha256="f" * 64,
    )
    with pytest.raises(PlatformError) as excinfo:
        verify_official_baseline(source, baseline)
    payload_text = json.dumps(excinfo.value.public_payload(), ensure_ascii=False)
    assert ":\\" not in payload_text
    assert str(tmp_path) not in payload_text


# ---------------------------------------------------------------------------
# CLI：seed-resistivity 维护命令
# ---------------------------------------------------------------------------


def test_cli_seed_resistivity_success_outputs_logical_identity(tmp_path: Path):
    from typer.testing import CliRunner

    from geomodeling.preset_cli import preset_app

    source_path = write_resistivity_fixture(tmp_path / "rho-source.csv", rows=17_549)
    source = load_resistivity_preset(source_path)
    baseline_path = _write_fixture_baseline(tmp_path / "baseline.json", source)
    data_dir = tmp_path / "cli-runtime"

    result = CliRunner().invoke(
        preset_app,
        [
            "seed-resistivity",
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
    assert payload["case_id"] == "resistivity"
    assert payload["workspace_kind"] == "builtin_preset"
    assert payload["official_result"]["result_id"]
    assert payload["source_sha256"] == source.sha256
    # 输出只含逻辑身份，绝无本机绝对路径
    assert ":\\" not in result.output
    assert str(tmp_path) not in result.output


def test_cli_seed_resistivity_missing_source_fails_closed(tmp_path: Path):
    from typer.testing import CliRunner

    from geomodeling.preset_cli import preset_app

    result = CliRunner().invoke(
        preset_app,
        [
            "seed-resistivity",
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


def test_cli_seed_resistivity_missing_baseline_fails_closed(tmp_path: Path):
    from typer.testing import CliRunner

    from geomodeling.preset_cli import preset_app

    source_path = write_resistivity_fixture(tmp_path / "rho-source.csv", rows=17_549)
    result = CliRunner().invoke(
        preset_app,
        [
            "seed-resistivity",
            "--source",
            str(source_path),
            "--data-dir",
            str(tmp_path / "cli-runtime"),
        ],
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error"]["code"] == PRESET_BASELINE_INVALID
    assert payload["error"]["details"]["reason"] == "missing_baseline"
