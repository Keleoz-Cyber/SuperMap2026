"""v0.8.0 Task 5：电阻率散点官方基线冻结与候选分析测试。

便携测试只用确定性合成源/合成遗留分区：提交的基线 JSON 只含计数、
指纹与实测指标，绝不入库真实 CSV 内容或坐标清单。真实源 SHA-256、
分区计数与网格范围是 2026-08-08 已核验事实的冻结常量。真实源与遗留
分区的完整重核验标记 ``local_data``，仅从 ``GEOMODELING_RHO_SOURCE``
环境变量取源路径（遗留文件按标准文件名从源同目录解析），未设置即跳过。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from geomodeling.platform.errors import PRESET_BASELINE_INVALID, PlatformError
from geomodeling.platform.resistivity_preset import (
    BASELINE_SCHEMA,
    DEFAULT_BASELINE_PATH,
    DSI_NEIGHBOR_CONNECTIVITIES,
    EXPECTED_ROW_COUNT,
    IDW_CANDIDATE_PARAMETERS,
    KRIGING_NEIGHBOR_COUNTS,
    KRIGING_VARIOGRAM_MODELS,
    REQUIRED_COLUMNS,
    SELECTION_RULE,
    SPATIAL_COLUMN_OVERLAP,
    TRAINING_COLUMNS,
    TRAINING_ROWS,
    VALIDATION_COLUMNS,
    VALIDATION_ROWS,
    OfficialBaseline,
    PartitionFacts,
    ResistivityCandidateReport,
    ResistivityPresetSource,
    analyze_resistivity_candidates,
    kriging_candidate_matrix,
    load_official_baseline,
    load_resistivity_preset,
    match_legacy_partition,
    official_candidate_matrix,
    rank_resistivity_candidates,
    report_to_json,
    verify_official_baseline,
    verify_partition_facts,
)
from test_resistivity_preset import RHO_SOURCE_ENV, write_resistivity_fixture

#: 2026-08-08 已核验真实源字节指纹（源文件本身绝不入库）
REAL_SOURCE_SHA256 = "04c5914d992f397f7dcec3b0d1a6069a9ddeb4a214e5c7de121f37c861cec167"

#: 已核验真实源坐标范围（20 m 三轴官方网格边界）
REAL_BOUNDS = [[-160.0, -40.0], [220.0, 660.0], [-833.0047143, -19.5999]]

LEGACY_TRAINING_FILENAME = "地下电阻率节点_训练集90.csv"
LEGACY_VALIDATION_FILENAME = "地下电阻率节点_验证集10.csv"

PARTITION_KEYS = {
    "training_rows",
    "validation_rows",
    "training_columns",
    "validation_columns",
    "spatial_column_overlap",
    "validation_column_fingerprint",
}


@pytest.fixture()
def source_path(tmp_path: Path) -> Path:
    return write_resistivity_fixture(tmp_path / "rho-source.csv", rows=17_549)


def _committed_doc() -> dict:
    return json.loads(DEFAULT_BASELINE_PATH.read_text(encoding="utf-8"))


def _rebased_doc(source) -> dict:
    """把提交的基线文档重绑定到夹具源（指纹 + 网格覆盖），其余逐项保留。"""

    doc = _committed_doc()
    doc["source_sha256"] = source.sha256
    frame = source.frame
    doc["grid"]["bounds"] = [
        [float(frame["X"].min()), float(frame["X"].max())],
        [float(frame["Y"].min()), float(frame["Y"].max())],
        [float(frame["Z"].min()), float(frame["Z"].max())],
    ]
    return doc


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
        partition=doc["partition"],
        selection_reason=doc["selection_reason"],
        sha256="f" * 64,
    )


def _grid_cells(bounds: list[list[float]], resolution: list[float]) -> int:
    cells = 1
    for (lo, hi), res in zip(bounds, resolution):
        cells *= max(2, int(round((hi - lo) / res)) + 1)
    return cells


# ---------------------------------------------------------------------------
# 提交基线的冻结身份（便携：只读 JSON，不依赖真实源文件）
# ---------------------------------------------------------------------------


def test_committed_baseline_is_frozen_to_verified_source_and_partition_facts():
    baseline = load_official_baseline(DEFAULT_BASELINE_PATH)
    assert baseline.schema == BASELINE_SCHEMA
    assert baseline.source_sha256 == REAL_SOURCE_SHA256
    assert baseline.standardized_rows == 17_549 == EXPECTED_ROW_COUNT
    assert baseline.training_rows == 15_827 == TRAINING_ROWS
    assert baseline.validation_rows == 1_722 == VALIDATION_ROWS

    partition = baseline.partition
    assert set(partition) == PARTITION_KEYS, "分区块只存计数与指纹，绝不存坐标清单"
    assert partition["training_columns"] == 264 == TRAINING_COLUMNS
    assert partition["validation_columns"] == 29 == VALIDATION_COLUMNS
    assert partition["spatial_column_overlap"] == 0 == SPATIAL_COLUMN_OVERLAP
    fingerprint = partition["validation_column_fingerprint"]
    assert len(fingerprint) == 64 and all(c in "0123456789abcdef" for c in fingerprint)

    # 官方候选验证合同 = 生产标准空间折分（与微震官方基线同一合同）
    assert baseline.validation == {"method": "spatial_kfold", "folds": 5, "seed": 20260723}
    assert tuple(baseline.selection_rule) == SELECTION_RULE

    # winner 限定在 ordinary_kriging 候选矩阵内，指标全部有限
    assert baseline.winner["algorithm"] == "ordinary_kriging"
    assert baseline.winner["parameters"] in kriging_candidate_matrix()
    metrics = baseline.winner["metrics"]
    for name in ("rmse", "mae", "r2", "bias"):
        assert np.isfinite(float(metrics[name])), name
    assert int(metrics["common_valid_count"]) > 0
    assert 0.0 < float(metrics["coverage"]) <= 1.0

    # 网格合同合法：20 m 三轴、真实源范围、单元数受上限约束
    grid = baseline.grid
    assert grid["resolution"] == [20.0, 20.0, 20.0]
    assert grid["bounds"] == REAL_BOUNDS
    assert grid["max_cells"] <= 1_000_000
    assert _grid_cells(grid["bounds"], grid["resolution"]) == 7 * 23 * 42 == 6762

    # 指纹来自文件字节；报告指纹格式合法
    assert baseline.sha256 == hashlib.sha256(DEFAULT_BASELINE_PATH.read_bytes()).hexdigest()
    report_sha = baseline.candidate_report_sha256
    assert len(report_sha) == 64 and all(c in "0123456789abcdef" for c in report_sha)


def test_committed_baseline_file_has_no_absolute_paths_or_coordinate_lists():
    raw = DEFAULT_BASELINE_PATH.read_text(encoding="utf-8")
    assert ":\\" not in raw
    assert "\\\\" not in raw
    doc = json.loads(raw)
    assert set(doc["partition"]) == PARTITION_KEYS


def test_rebased_committed_baseline_verifies_against_fixture_source(source_path: Path):
    """正对照：重绑定到夹具源后 verify 全链路通过（夹具同为 17,549 行/293 柱）。"""

    source = load_resistivity_preset(source_path)
    verify_official_baseline(source, _baseline_from_doc(_rebased_doc(source)))


@pytest.mark.parametrize(
    "mutate, reason",
    [
        pytest.param(
            lambda doc: doc.update(source_sha256="0" * 64), "source_sha256", id="source_sha256"
        ),
        pytest.param(
            lambda doc: doc.update(standardized_rows=17_548),
            "standardized_rows",
            id="standardized_rows",
        ),
        pytest.param(
            lambda doc: doc["partition"].update(training_rows=15_826),
            "partition_training_rows",
            id="partition_training_rows",
        ),
        pytest.param(
            lambda doc: doc["partition"].update(validation_rows=1_721),
            "partition_validation_rows",
            id="partition_validation_rows",
        ),
        pytest.param(
            lambda doc: doc["partition"].update(training_columns=263),
            "partition_training_columns",
            id="partition_training_columns",
        ),
        pytest.param(
            lambda doc: doc["partition"].update(validation_columns=28),
            "partition_validation_columns",
            id="partition_validation_columns",
        ),
        pytest.param(
            lambda doc: doc["partition"].update(spatial_column_overlap=1),
            "partition_spatial_column_overlap",
            id="partition_spatial_column_overlap",
        ),
        pytest.param(
            lambda doc: doc["partition"].update(validation_column_fingerprint="z" * 64),
            "partition_fingerprint",
            id="partition_fingerprint",
        ),
        pytest.param(
            lambda doc: doc["partition"].pop("validation_column_fingerprint"),
            "partition_fingerprint",
            id="partition_fingerprint_missing",
        ),
        pytest.param(
            lambda doc: doc.update(candidate_report_sha256="0" * 4),
            "candidate_report_sha256",
            id="report_sha_format",
        ),
        pytest.param(
            lambda doc: doc["winner"].update(algorithm="idw"),
            "winner_parameters",
            id="winner_algorithm_not_kriging",
        ),
        pytest.param(
            lambda doc: doc["winner"].update(
                parameters={"variogram_model": "gaussian", "neighbor_count": 16}
            ),
            "winner_parameters",
            id="winner_params_outside_matrix",
        ),
        pytest.param(
            lambda doc: doc["winner"]["metrics"].update(rmse=float("nan")),
            "winner_metrics",
            id="winner_metrics_nan",
        ),
        pytest.param(
            lambda doc: doc.update(validation={"method": "random", "folds": 3, "seed": 1}),
            "validation",
            id="validation",
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
def test_verify_baseline_fail_closed_on_tamper(source_path: Path, mutate, reason: str):
    source = load_resistivity_preset(source_path)
    doc = _rebased_doc(source)
    mutate(doc)
    with pytest.raises(PlatformError) as excinfo:
        verify_official_baseline(source, _baseline_from_doc(doc))
    assert excinfo.value.code == PRESET_BASELINE_INVALID
    assert excinfo.value.details["reason"] == reason
    assert excinfo.value.http_status == 409


# ---------------------------------------------------------------------------
# 候选报告绑定（合成报告对象，不做重计算）
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
            "coverage": 0.9,
            "common_valid_count": 100,
        },
        "error": None,
    }


def _fake_report(source_sha256: str, report_sha256: str, candidates: list[dict]):
    return ResistivityCandidateReport(
        candidates=tuple(candidates),
        source_sha256=source_sha256,
        validation={"method": "spatial_kfold", "folds": 5, "seed": 20260723},
        common_valid_count=100,
        partition=None,
        sha256=report_sha256,
    )


def _winner_params(doc: dict) -> dict:
    return doc["winner"]["parameters"]


def test_verify_baseline_binds_candidate_report(source_path: Path):
    source = load_resistivity_preset(source_path)
    doc = _rebased_doc(source)
    baseline = _baseline_from_doc(doc)
    winner = _winner_params(doc)
    # IDW 候选 rmse 更低也不得成为官方 winner（winner 限定 kriging 矩阵）
    candidates = [
        _candidate("idw", {"power": 2.0, "neighbor_count": 24}, rmse=0.001),
        _candidate("ordinary_kriging", winner, rmse=0.5),
        _candidate(
            "ordinary_kriging",
            {"variogram_model": "exponential", "neighbor_count": 16},
            rmse=0.6,
        ),
        _candidate("dsi_like", {"neighbor_connectivity": 6}, rmse=0.4),
    ]
    report = _fake_report(source.sha256, doc["candidate_report_sha256"], candidates)
    verify_official_baseline(source, baseline, report=report)


@pytest.mark.parametrize(
    "report_sha, reason",
    [
        pytest.param("1" * 64, "candidate_report_sha256", id="report_sha_mismatch"),
    ],
)
def test_verify_baseline_rejects_unbound_report(source_path: Path, report_sha: str, reason: str):
    source = load_resistivity_preset(source_path)
    doc = _rebased_doc(source)
    baseline = _baseline_from_doc(doc)
    candidates = [_candidate("ordinary_kriging", _winner_params(doc), rmse=0.5)]
    report = _fake_report(source.sha256, report_sha, candidates)
    with pytest.raises(PlatformError) as excinfo:
        verify_official_baseline(source, baseline, report=report)
    assert excinfo.value.details["reason"] == reason


def test_verify_baseline_rejects_report_from_other_source(source_path: Path):
    source = load_resistivity_preset(source_path)
    doc = _rebased_doc(source)
    baseline = _baseline_from_doc(doc)
    report = _fake_report("0" * 64, doc["candidate_report_sha256"], [])
    with pytest.raises(PlatformError) as excinfo:
        verify_official_baseline(source, baseline, report=report)
    assert excinfo.value.details["reason"] == "report_source_sha256"


def test_verify_baseline_rejects_winner_not_report_kriging_top(source_path: Path):
    source = load_resistivity_preset(source_path)
    doc = _rebased_doc(source)
    baseline = _baseline_from_doc(doc)
    # 报告中 kriging 最优是另一组参数 → winner 不可复算，拒绝
    candidates = [
        _candidate(
            "ordinary_kriging",
            {"variogram_model": "spherical", "neighbor_count": 16},
            rmse=0.01,
        ),
        _candidate("ordinary_kriging", _winner_params(doc), rmse=0.9),
    ]
    report = _fake_report(source.sha256, doc["candidate_report_sha256"], candidates)
    with pytest.raises(PlatformError) as excinfo:
        verify_official_baseline(source, baseline, report=report)
    assert excinfo.value.details["reason"] == "winner_not_report_top"


# ---------------------------------------------------------------------------
# 最小官方候选矩阵与选择规则（纯函数）
# ---------------------------------------------------------------------------


def test_official_candidate_matrix_is_exactly_7_members():
    matrix = official_candidate_matrix()
    assert len(matrix) == 7
    by_algorithm = {}
    for entry in matrix:
        by_algorithm.setdefault(entry["algorithm"], []).append(entry["parameters"])
    assert by_algorithm["idw"] == [dict(p) for p in IDW_CANDIDATE_PARAMETERS]
    assert by_algorithm["ordinary_kriging"] == [
        {"variogram_model": model, "neighbor_count": neighbors}
        for model in KRIGING_VARIOGRAM_MODELS
        for neighbors in KRIGING_NEIGHBOR_COUNTS
    ]
    assert by_algorithm["dsi_like"] == [
        {"neighbor_connectivity": connectivity} for connectivity in DSI_NEIGHBOR_CONNECTIVITIES
    ]
    # kriging 子矩阵是 winner 的允许集合
    assert by_algorithm["ordinary_kriging"] == kriging_candidate_matrix()


def test_rank_candidates_orders_and_filters_finite_metrics():
    entries = [
        _candidate("ordinary_kriging", {"variogram_model": "spherical", "neighbor_count": 16}, 0.41),
        _candidate("ordinary_kriging", {"variogram_model": "spherical", "neighbor_count": 24}, 0.40),
        _candidate(
            "ordinary_kriging",
            {"variogram_model": "exponential", "neighbor_count": 16},
            float("nan"),
        ),
        {"algorithm": "dsi_like", "params": {"neighbor_connectivity": 26}, "metrics": None,
         "error": "DSI_LIKE_NO_SUPPORTED_NODES"},
    ]
    ranked = rank_resistivity_candidates(entries, algorithm="ordinary_kriging")
    assert [e["params"]["neighbor_count"] for e in ranked] == [24, 16]
    # 不限制算法时 dsi_like 失败候选同样被排除
    ranked_all = rank_resistivity_candidates(entries)
    assert all(e["metrics"] for e in ranked_all)
    assert len(ranked_all) == 2


# ---------------------------------------------------------------------------
# 候选分析（合成小源，便携）
# ---------------------------------------------------------------------------


def _synthetic_source() -> ResistivityPresetSource:
    """确定性合成 5×5×4 规则散点（25 柱 ≥ 5 折），无随机源之外的抖动。"""

    rng = np.random.default_rng(42)
    xs, ys, zs = [], [], []
    for ix in range(5):
        for iy in range(5):
            for iz in range(4):
                xs.append(ix * 20.0)
                ys.append(iy * 20.0)
                zs.append(-60.0 + iz * 20.0)
    x = np.array(xs)
    y = np.array(ys)
    z = np.array(zs)
    rho = 10.0 + 0.5 * np.sin(x / 25) + 0.3 * np.cos(y / 22) - 0.2 * (z / 30)
    rho += rng.normal(0, 0.01, size=len(rho))
    frame = pd.DataFrame({"X": x, "Y": y, "Z": z, "RHO": rho})
    return ResistivityPresetSource(
        frame=frame,
        sha256="synthetic",
        row_count=len(frame),
        columns=REQUIRED_COLUMNS,
    )


def test_analyze_builds_deterministic_7_candidate_report():
    source = _synthetic_source()
    report = analyze_resistivity_candidates(source)
    assert len(report.candidates) == 7
    assert report.validation == {"method": "spatial_kfold", "folds": 5, "seed": 20260723}
    assert report.source_sha256 == "synthetic"
    assert report.partition is None
    again = analyze_resistivity_candidates(source)
    assert report.sha256 == again.sha256
    # 候选失败是结构化记录而非静默通过；kriging 候选必须有有限指标
    for entry in report.candidates:
        assert set(entry) == {"algorithm", "params", "metrics", "error"}
        assert (entry["metrics"] is None) == (entry["error"] is not None)
    kriging_ranked = rank_resistivity_candidates(report.candidates, algorithm="ordinary_kriging")
    assert kriging_ranked, "合成源上必须存在有限指标的 kriging 候选"
    assert kriging_ranked[0]["params"] in kriging_candidate_matrix()
    # 报告落盘形态与指纹一致
    payload = report_to_json(report)
    assert payload["sha256"] == report.sha256
    assert payload["partition"] is None
    assert payload["common_valid_count"] == report.common_valid_count


def test_analyze_embeds_partition_facts_into_report_identity():
    source = _synthetic_source()
    facts = PartitionFacts(
        training_rows=80,
        validation_rows=20,
        training_columns=20,
        validation_columns=5,
        spatial_column_overlap=0,
        validation_column_fingerprint="a" * 64,
    )
    report = analyze_resistivity_candidates(source, partition=facts)
    assert report.partition == facts.to_dict()
    plain = analyze_resistivity_candidates(source)
    assert report.sha256 != plain.sha256, "分区事实参与报告指纹"
    assert report_to_json(report)["partition"] == facts.to_dict()


# ---------------------------------------------------------------------------
# 遗留分区匹配（合成拆分，便携；真实重核验见 local_data 段）
# ---------------------------------------------------------------------------


def _split_fixture(tmp_path: Path):
    """6 柱 × 5 层共 30 行；4 柱训练 + 2 柱验证，逐行出自同一合成源。"""

    rows = []
    for ix in range(3):
        for iy in range(2):
            for iz in range(5):
                rows.append((ix * 20.0, iy * 20.0, -iz * 10.0, 10.0 + ix + iy + iz / 10))
    frame = pd.DataFrame(rows, columns=list(REQUIRED_COLUMNS))
    training = frame.loc[frame["X"] < 40.0]  # ix ∈ {0,1} → 4 柱 × 5 层
    validation = frame.loc[frame["X"] >= 40.0]  # ix = 2 → 2 柱 × 5 层
    assert len(training) == 20 and len(validation) == 10
    source = ResistivityPresetSource(
        frame=frame, sha256="split-src", row_count=len(frame), columns=REQUIRED_COLUMNS
    )
    training_path = tmp_path / "training.csv"
    validation_path = tmp_path / "validation.csv"
    training.to_csv(training_path, index=False, encoding="utf-8")
    validation.to_csv(validation_path, index=False, encoding="utf-8")
    return source, training, validation, training_path, validation_path


def test_match_legacy_partition_recovers_counts_and_fingerprint(tmp_path: Path):
    source, _t, _v, training_path, validation_path = _split_fixture(tmp_path)
    facts = match_legacy_partition(source, training_path, validation_path)
    assert facts.training_rows == 20
    assert facts.validation_rows == 10
    assert facts.training_columns == 4
    assert facts.validation_columns == 2
    assert facts.spatial_column_overlap == 0
    fingerprint = facts.validation_column_fingerprint
    assert len(fingerprint) == 64 and all(c in "0123456789abcdef" for c in fingerprint)
    again = match_legacy_partition(source, training_path, validation_path)
    assert again == facts, "分区匹配必须确定可复算"


def test_match_legacy_partition_rejects_row_outside_source(tmp_path: Path):
    source, _t, validation, training_path, validation_path = _split_fixture(tmp_path)
    tampered = validation.copy()
    tampered.iloc[0, tampered.columns.get_loc("Z")] += 1.0
    tampered.to_csv(validation_path, index=False, encoding="utf-8")
    with pytest.raises(PlatformError) as excinfo:
        match_legacy_partition(source, training_path, validation_path)
    assert excinfo.value.code == PRESET_BASELINE_INVALID
    assert excinfo.value.details["reason"] == "legacy_validation_row_not_in_source"


def test_match_legacy_partition_rejects_row_overlap(tmp_path: Path):
    source, training, validation, training_path, validation_path = _split_fixture(tmp_path)
    overlapped = pd.concat([validation, training.head(1)], ignore_index=True)
    overlapped.to_csv(validation_path, index=False, encoding="utf-8")
    with pytest.raises(PlatformError) as excinfo:
        match_legacy_partition(source, training_path, validation_path)
    assert excinfo.value.details["reason"] == "row_overlap"


def test_match_legacy_partition_rejects_union_mismatch(tmp_path: Path):
    source, _t, validation, training_path, validation_path = _split_fixture(tmp_path)
    validation.iloc[1:].to_csv(validation_path, index=False, encoding="utf-8")
    with pytest.raises(PlatformError) as excinfo:
        match_legacy_partition(source, training_path, validation_path)
    assert excinfo.value.details["reason"] == "union_mismatch"


def test_match_legacy_partition_rejects_duplicate_rows(tmp_path: Path):
    source, training, _v, training_path, validation_path = _split_fixture(tmp_path)
    duplicated = pd.concat([training, training.head(1)], ignore_index=True)
    duplicated.to_csv(training_path, index=False, encoding="utf-8")
    with pytest.raises(PlatformError) as excinfo:
        match_legacy_partition(source, training_path, validation_path)
    assert excinfo.value.details["reason"] == "legacy_training_duplicate"


def test_verify_partition_facts_rejects_non_frozen_counts(tmp_path: Path):
    source, _t, _v, training_path, validation_path = _split_fixture(tmp_path)
    facts = match_legacy_partition(source, training_path, validation_path)
    with pytest.raises(PlatformError) as excinfo:
        verify_partition_facts(facts)
    assert excinfo.value.code == PRESET_BASELINE_INVALID
    assert excinfo.value.details["reason"] == "partition_training_rows"


# ---------------------------------------------------------------------------
# 真实源 + 真实遗留分区的完整重核验（外部私有文件，未配置即跳过）
# ---------------------------------------------------------------------------


def _real_source_path() -> Path:
    raw = os.environ.get(RHO_SOURCE_ENV)
    if not raw:
        pytest.skip(f"{RHO_SOURCE_ENV} 未设置：外部私有源不入库，便携环境跳过")
    return Path(raw)


@pytest.mark.local_data
def test_real_source_verifies_committed_baseline():
    source = load_resistivity_preset(_real_source_path())
    assert source.sha256 == REAL_SOURCE_SHA256
    baseline = load_official_baseline(DEFAULT_BASELINE_PATH)
    verify_official_baseline(source, baseline)


@pytest.mark.local_data
def test_real_legacy_partition_recomputation_matches_committed_baseline():
    source_path = _real_source_path()
    source = load_resistivity_preset(source_path)
    training_path = source_path.parent / LEGACY_TRAINING_FILENAME
    validation_path = source_path.parent / LEGACY_VALIDATION_FILENAME
    facts = match_legacy_partition(source, training_path, validation_path)
    verify_partition_facts(facts)
    baseline = load_official_baseline(DEFAULT_BASELINE_PATH)
    assert facts.to_dict() == baseline.partition
