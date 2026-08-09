"""v0.8.0 第三批 Task 5：瓦斯含量官方基线冻结与候选分析测试。

与电阻率基线测试不同，瓦斯真实源内置在仓库 ``example_data/瓦斯含量_合格
样品.csv``（58 行、28 个 XY 柱，字节级冻结合同），因此全部测试便携：
折分泄漏门、候选分析、确定性与基线复算都直接在真实内置源上运行，不设
``local_data`` 外部源跳过分支。提交的基线 JSON 只含逻辑身份、指纹与实测
指标，绝无本机绝对路径与坐标清单。

真实事实（2026-08-09 已核验）：源 SHA-256 f7d6f03d…；58 行全有限；
空间 5 折（spatial_kfold，seed 20260723，整 XY 柱分组）逐折验证行数
[12, 11, 11, 13, 11]（总和恰为 58）；官方网格 XY 20 m / Z 5 m 各向异性
分辨率，节点 151×333×12 = 603,396 ≤ max_cells。
"""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from geomodeling.modeling.splits import build_spatial_splits
from geomodeling.platform.errors import PRESET_BASELINE_INVALID, PlatformError
from geomodeling.platform.gas_preset import (
    BASELINE_SCHEMA,
    DEFAULT_BASELINE_PATH,
    DEFAULT_PRESET_CSV,
    EXPECTED_ROW_COUNT,
    IDW_NEIGHBOR_COUNTS,
    IDW_POWERS,
    KRIGING_NEIGHBOR_COUNTS,
    KRIGING_VARIOGRAM_MODELS,
    PRESET_VERSION,
    SELECTION_RULE,
    VALIDATION_CONTRACT,
    GasCandidateReport,
    OfficialBaseline,
    analyze_gas_candidates,
    idw_candidate_matrix,
    kriging_candidate_matrix,
    load_gas_preset,
    load_official_baseline,
    official_candidate_matrix,
    rank_gas_candidates,
    report_to_json,
    verify_official_baseline,
    winner_candidate_matrix,
)
from geomodeling.platform.schemas import SpatialValidationSpec
from test_gas_preset_contract import GAS_SOURCE_SHA256

#: 已核验真实源坐标范围（官方网格边界，逐轴恰为源 min/max）
REAL_BOUNDS = [[1023.802, 4016.788], [1049.716, 7688.731], [121.0375, 175.656]]

#: 官方网格：XY 20 m / Z 5 m 各向异性（XY 跨度约 3.0/6.6 km，Z 跨度 54.6 m）
REAL_GRID_RESOLUTION = [20.0, 20.0, 5.0]
REAL_GRID_SHAPE = [151, 333, 12]
REAL_GRID_CELLS = 151 * 333 * 12

#: 真实源 28 个 XY 柱在空间 5 折合同下的逐折验证行数（总和 = 58）
REAL_FOLD_VALIDATION_ROWS = [12, 11, 11, 13, 11]


@pytest.fixture(scope="module")
def real_source():
    return load_gas_preset(DEFAULT_PRESET_CSV)


@pytest.fixture(scope="module")
def report(real_source) -> GasCandidateReport:
    """真实内置源上的候选分析报告（模块级复用，避免重复评估 DSI-like）。"""

    return analyze_gas_candidates(real_source)


def _committed_doc() -> dict:
    return json.loads(DEFAULT_BASELINE_PATH.read_text(encoding="utf-8"))


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


def _grid_cells(bounds: list[list[float]], resolution: list[float]) -> int:
    cells = 1
    for (lo, hi), res in zip(bounds, resolution):
        cells *= max(2, int(round((hi - lo) / res)) + 1)
    return cells


# ---------------------------------------------------------------------------
# 折分泄漏门：3D 整 XY 柱分组，同一 XY 位置绝不跨 train/validation
# ---------------------------------------------------------------------------


def test_spatial_kfold_never_straddles_xy_columns(real_source):
    frame = real_source.frame
    points = frame[["X", "Y", "Z"]].to_numpy(dtype="float64")
    xy_keys = [tuple(row) for row in frame[["X", "Y"]].to_numpy(dtype="float64")]
    assert len(set(xy_keys)) == 28, "真实源 28 个 XY 采样位置（2026-08-09 已核验）"

    folds = build_spatial_splits(
        points, "3d", SpatialValidationSpec.model_validate(VALIDATION_CONTRACT)
    )
    assert len(folds) == 5
    for fold in folds:
        training_xy = {xy_keys[int(i)] for i in fold.training_indices}
        validation_xy = {xy_keys[int(i)] for i in fold.validation_indices}
        assert training_xy.isdisjoint(validation_xy), (
            f"fold {fold.index}：同一 XY 柱跨 train/validation 即泄漏"
        )
        assert len(fold.training_indices) + len(fold.validation_indices) == 58
        assert len(fold.validation_indices) > 0
    # 折分与源指纹绑定：逐折验证行数冻结（总和恰为 58 行源）
    assert [len(f.validation_indices) for f in folds] == REAL_FOLD_VALIDATION_ROWS
    assert sum(len(f.validation_indices) for f in folds) == 58

    # 同源同种子复算逐位一致（折分确定性）
    again = build_spatial_splits(
        points, "3d", SpatialValidationSpec.model_validate(VALIDATION_CONTRACT)
    )
    for first, second in zip(folds, again):
        np.testing.assert_array_equal(first.training_indices, second.training_indices)
        np.testing.assert_array_equal(first.validation_indices, second.validation_indices)


# ---------------------------------------------------------------------------
# 提交基线的冻结身份（便携：基线与真实源同库，直接验证）
# ---------------------------------------------------------------------------


def test_committed_baseline_is_frozen_to_verified_real_source():
    baseline = load_official_baseline(DEFAULT_BASELINE_PATH)
    assert baseline.schema == BASELINE_SCHEMA
    assert baseline.source_sha256 == GAS_SOURCE_SHA256
    assert baseline.standardized_rows == 58 == EXPECTED_ROW_COUNT

    # 官方候选验证合同 = 生产标准空间折分（与微震/电阻率官方基线同一合同）
    assert baseline.validation == {"method": "spatial_kfold", "folds": 5, "seed": 20260723}
    assert tuple(baseline.selection_rule) == SELECTION_RULE

    # winner ∈ {idw, ordinary_kriging} 且参数在允许矩阵内；指标全部有限
    matrix = winner_candidate_matrix()
    assert set(matrix) == {"idw", "ordinary_kriging"}, "DSI-like 永不在 winner 矩阵"
    assert baseline.winner["algorithm"] in matrix
    assert baseline.winner["parameters"] in matrix[baseline.winner["algorithm"]]
    metrics = baseline.winner["metrics"]
    for name in ("rmse", "mae", "r2", "bias"):
        assert np.isfinite(float(metrics[name])), name
    assert int(metrics["common_valid_count"]) == 58
    assert 0.0 < float(metrics["coverage"]) <= 1.0

    # 网格合同：XY 20 m / Z 5 m、真实源范围、节点数受上限约束
    grid = baseline.grid
    assert grid["resolution"] == REAL_GRID_RESOLUTION
    assert grid["bounds"] == REAL_BOUNDS
    assert grid["max_cells"] <= 1_000_000
    assert _grid_cells(grid["bounds"], grid["resolution"]) == REAL_GRID_CELLS == 603_396

    # 折分与源指纹绑定：基线指纹来自文件字节；候选报告指纹格式合法
    assert baseline.sha256 == hashlib.sha256(DEFAULT_BASELINE_PATH.read_bytes()).hexdigest()
    report_sha = baseline.candidate_report_sha256
    assert len(report_sha) == 64 and all(c in "0123456789abcdef" for c in report_sha)

    # DSI-like 条件评估结论块（对照候选，绝不参与官方选择）
    doc = _committed_doc()
    assert doc["preset_version"] == PRESET_VERSION
    block = doc["dsi_like"]
    assert block["status"] in {"evaluated", "excluded"}
    if block["status"] == "evaluated":
        assert block["reason"] is None
        for name in ("rmse", "mae", "r2", "bias"):
            assert np.isfinite(float(block["metrics"][name])), name
    else:
        assert isinstance(block["reason"], str) and block["reason"]


def test_committed_baseline_file_has_no_absolute_paths():
    raw = DEFAULT_BASELINE_PATH.read_text(encoding="utf-8")
    assert ":\\" not in raw
    assert "\\\\" not in raw
    json.loads(raw)  # 合法 JSON


def test_committed_baseline_verifies_against_real_source(real_source):
    """正对照：提交基线对真实内置源 verify 全链路通过。"""

    baseline = load_official_baseline(DEFAULT_BASELINE_PATH)
    verify_official_baseline(real_source, baseline)


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
            lambda doc: doc.update(selection_rule=["r2_desc"]),
            "selection_rule",
            id="selection_rule",
        ),
        pytest.param(
            lambda doc: doc.update(candidate_report_sha256="not-a-sha"),
            "candidate_report_sha256",
            id="candidate_report_sha256",
        ),
        pytest.param(
            lambda doc: doc["winner"].update(algorithm="dsi_like"),
            "winner_algorithm",
            id="winner_algorithm_dsi_like",
        ),
        pytest.param(
            lambda doc: doc["winner"].update(parameters={"power": 9.0, "neighbor_count": 3}),
            "winner_parameters",
            id="winner_params_outside_matrix",
        ),
        pytest.param(
            lambda doc: doc["winner"].update(
                parameters={"variogram_model": "gaussian", "neighbor_count": 16}
            ),
            "winner_parameters",
            id="winner_kriging_params_outside_matrix",
        ),
        pytest.param(
            lambda doc: doc["winner"]["metrics"].update(rmse=float("nan")),
            "winner_metrics",
            id="winner_metrics_nan",
        ),
        pytest.param(
            lambda doc: doc["grid"].update(max_cells=10),
            "grid_cells",
            id="grid_cells_over_cap",
        ),
        pytest.param(
            lambda doc: doc["grid"].update(bounds=[[0.0, 100.0], [0.0, 100.0], [-10.0, 0.0]]),
            "grid_bounds_coverage",
            id="grid_bounds_not_covering",
        ),
    ],
)
def test_verify_baseline_fail_closed_on_tamper(real_source, mutate, reason: str):
    doc = _committed_doc()
    mutate(doc)
    with pytest.raises(PlatformError) as excinfo:
        verify_official_baseline(real_source, _baseline_from_doc(doc))
    assert excinfo.value.code == PRESET_BASELINE_INVALID
    assert excinfo.value.details["reason"] == reason
    assert excinfo.value.http_status == 409


# ---------------------------------------------------------------------------
# 真实源候选分析：13 候选矩阵、公共有效集、确定性、复算绑定
# ---------------------------------------------------------------------------


def test_analyze_builds_13_candidate_report_on_real_source(report: GasCandidateReport):
    matrix = official_candidate_matrix()
    assert len(matrix) == 13
    assert [dict(p) for p in (e["parameters"] for e in matrix[:9])] == idw_candidate_matrix()
    assert matrix[9:] == [
        {"algorithm": "ordinary_kriging", "parameters": params}
        for params in kriging_candidate_matrix()
    ]
    assert {p["power"] for p in idw_candidate_matrix()} == set(IDW_POWERS)
    assert {p["neighbor_count"] for p in idw_candidate_matrix()} == set(IDW_NEIGHBOR_COUNTS)
    assert {p["variogram_model"] for p in kriging_candidate_matrix()} == set(
        KRIGING_VARIOGRAM_MODELS
    )
    assert {p["neighbor_count"] for p in kriging_candidate_matrix()} == set(
        KRIGING_NEIGHBOR_COUNTS
    )

    assert report.validation == {"method": "spatial_kfold", "folds": 5, "seed": 20260723}
    assert report.source_sha256 == GAS_SOURCE_SHA256
    assert tuple(report.fold_validation_rows) == tuple(REAL_FOLD_VALIDATION_ROWS)
    assert sum(report.fold_validation_rows) == 58
    assert len(report.candidates) == 13
    for entry in report.candidates:
        assert set(entry) == {"algorithm", "params", "metrics", "error"}
        assert (entry["metrics"] is None) == (entry["error"] is not None)
        assert entry["error"] is None, f"真实源上候选失败必须结构化记录：{entry}"
        metrics = entry["metrics"]
        for name in ("rmse", "mae", "r2", "bias"):
            assert np.isfinite(float(metrics[name])), (entry["algorithm"], name)
    # IDW/普通克里金在 58 个验证点上全程有限：公共有效集 = 全部 58 点
    assert report.common_valid_count == 58
    # DSI-like 是条件对照候选，绝不进入 winner 候选列表
    assert all(entry["algorithm"] in {"idw", "ordinary_kriging"} for entry in report.candidates)

    payload = report_to_json(report)
    assert payload["sha256"] == report.sha256
    assert payload["schema"] == "v0.8.0-gas-candidate-report/v1"
    assert payload["preset_version"] == PRESET_VERSION
    assert payload["common_valid_count"] == report.common_valid_count
    assert payload["fold_validation_rows"] == list(REAL_FOLD_VALIDATION_ROWS)


def test_analyze_is_deterministic_on_same_source(real_source, report: GasCandidateReport):
    """同一源两次 analyze：报告指纹与候选载荷逐位一致。"""

    again = analyze_gas_candidates(real_source)
    assert again.sha256 == report.sha256
    assert report_to_json(again) == report_to_json(report)


def test_dsi_like_conditional_evaluation_block(report: GasCandidateReport):
    """DSI-like 条件评估：全部门通过才 evaluated，任一失败 excluded（带原因）。

    门：交叉验证全部折成功 → 公共有效集非空 → 指标有限 → 全数据 fit +
    官方网格物化（网格内全有限、包围盒外 NoData）。绝不静默通过或静默丢弃。
    """

    block = report.dsi_like
    assert set(block) == {"parameters", "status", "reason", "metrics", "materialization"}
    assert block["status"] in {"evaluated", "excluded"}
    if block["status"] == "excluded":
        assert isinstance(block["reason"], str) and block["reason"]
        assert block["metrics"] is None
        assert block["materialization"] is None
        return
    assert block["reason"] is None
    metrics = block["metrics"]
    for name in ("rmse", "mae", "r2", "bias"):
        assert np.isfinite(float(metrics[name])), name
    assert int(metrics["common_valid_count"]) > 0
    assert 0.0 < float(metrics["coverage"]) <= 1.0
    materialization = block["materialization"]
    assert materialization["grid_shape"] == REAL_GRID_SHAPE
    assert materialization["node_count"] == REAL_GRID_CELLS
    assert materialization["finite_node_count"] == REAL_GRID_CELLS
    assert materialization["outside_nodata"] is True


def test_recomputed_report_matches_committed_baseline(report: GasCandidateReport):
    """复算模式：真实源重跑 analyze 必须逐位复现基线冻结的指纹与选择。"""

    baseline = load_official_baseline(DEFAULT_BASELINE_PATH)
    assert report.source_sha256 == baseline.source_sha256 == GAS_SOURCE_SHA256
    assert report.sha256 == baseline.candidate_report_sha256, (
        "候选报告指纹不可复现：折分/指标/DSI-like 评估与冻结基线脱钩"
    )
    ranked = rank_gas_candidates(report.candidates)
    assert ranked, "真实源上必须存在有限指标的 idw/kriging 候选"
    assert ranked[0]["algorithm"] == baseline.winner["algorithm"]
    assert ranked[0]["params"] == baseline.winner["parameters"]
    assert ranked[0]["metrics"] == baseline.winner["metrics"]
    # DSI-like 评估结论与基线冻结结论一致
    doc = _committed_doc()
    assert doc["dsi_like"]["status"] == report.dsi_like["status"]
    assert doc["dsi_like"]["reason"] == report.dsi_like["reason"]


# ---------------------------------------------------------------------------
# 排名规则（纯函数，合成候选）
# ---------------------------------------------------------------------------


def _candidate(algorithm: str, params: dict, rmse: float, *, mae=None, r2=None) -> dict:
    return {
        "algorithm": algorithm,
        "params": params,
        "metrics": {
            "rmse": rmse,
            "mae": rmse / 2 if mae is None else mae,
            "r2": 0.8 if r2 is None else r2,
            "bias": 0.01,
            "coverage": 1.0,
            "common_valid_count": 58,
        },
        "error": None,
    }


def test_rank_candidates_orders_and_filters_finite_metrics():
    entries = [
        _candidate("idw", {"power": 2.0, "neighbor_count": 24}, 0.41),
        _candidate("idw", {"power": 1.5, "neighbor_count": 16}, 0.40),
        _candidate(
            "ordinary_kriging",
            {"variogram_model": "spherical", "neighbor_count": 16},
            float("nan"),
        ),
        {"algorithm": "idw", "params": {"power": 3.0, "neighbor_count": 32},
         "metrics": None, "error": "SOME_FAILURE"},
    ]
    ranked = rank_gas_candidates(entries)
    assert [e["params"]["power"] for e in ranked] == [1.5, 2.0]
    assert all(e["metrics"] for e in ranked)
    kriging_only = rank_gas_candidates(entries, algorithm="ordinary_kriging")
    assert kriging_only == [], "非有限指标候选一律排除"
    idw_only = rank_gas_candidates(entries, algorithm="idw")
    assert len(idw_only) == 2


def test_rank_candidates_tiebreaks_by_mae_r2_then_canonical_params():
    first = _candidate("idw", {"power": 2.0, "neighbor_count": 16}, 0.5, mae=0.2, r2=0.7)
    second = _candidate("idw", {"power": 2.0, "neighbor_count": 24}, 0.5, mae=0.2, r2=0.9)
    third = _candidate("idw", {"power": 1.5, "neighbor_count": 16}, 0.5, mae=0.3, r2=0.9)
    ranked = rank_gas_candidates([third, first, second])
    assert [e["params"]["neighbor_count"] for e in ranked] == [24, 16, 16]
    assert ranked[0]["params"]["power"] == 2.0
    assert ranked[1]["params"]["power"] == 2.0
    assert ranked[2]["params"]["power"] == 1.5
