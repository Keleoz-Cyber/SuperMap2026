"""v0.7.0 Batch 1：微震 CSV 预置源合同测试（Task 1）。

受控 CSV 是用户指定标准化文件的原字节拷贝（9 列表头，含 SAMPLE_IDS 等
溯源列）；加载器钉死完整表头、1911 行、有限数值与唯一 XYZ，并向公共
层只暴露 4 个建模列与摘要指纹，绝不返回本机源路径。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from geomodeling.platform.errors import PRESET_SOURCE_INVALID, PlatformError
from geomodeling.platform.microseismic_preset import (
    ORIGINAL_SOURCE_NAME,
    ORIGINAL_SOURCE_SHA256,
    PRESET_CASE_ID,
    PRESET_VERSION,
    REQUIRED_COLUMNS,
    SOURCE_COLUMNS,
    TRACKED_CSV_BYTES,
    TRACKED_CSV_SHA256,
    load_microseismic_preset,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
TRACKED_CSV = REPO_ROOT / "data" / "presets" / "microseismic" / "microseismic-vx-1911.csv"


@pytest.fixture()
def preset_csv() -> Path:
    return TRACKED_CSV


def test_tracked_csv_is_byte_identified_and_never_outside_repo(preset_csv: Path):
    assert preset_csv.is_file()
    # .gitattributes `*.csv text eol=lf`：任何平台检出均为 LF 字节
    digest = hashlib.sha256(preset_csv.read_bytes()).hexdigest()
    assert digest == TRACKED_CSV_SHA256
    assert preset_csv.stat().st_size == TRACKED_CSV_BYTES
    assert preset_csv.resolve().is_relative_to(REPO_ROOT)
    # 溯源记录：用户指定原始文件（CRLF 形态）身份随模块保存
    assert ORIGINAL_SOURCE_SHA256 == "4011de85e1fa7e49999fc5ae66a73e00a59dbec372a417ae0728d0a338c7765e"
    assert ORIGINAL_SOURCE_NAME.endswith("_1911.csv")


def test_load_preset_requires_1911_unique_finite_vx_rows(preset_csv: Path):
    source = load_microseismic_preset(preset_csv)
    assert source.row_count == 1911
    assert source.columns == ("X_LOCAL_M", "Y_LOCAL_M", "Z_LOCAL_M", "VX_KM_S")
    assert source.source_columns == SOURCE_COLUMNS
    assert source.value_unit == "km/s"
    assert source.coordinate_kind == "local_linear"
    assert source.sha256 == TRACKED_CSV_SHA256
    assert list(source.frame.columns) == list(REQUIRED_COLUMNS)
    # Vx 保持 km/s，不静默换算 m/s
    assert float(source.frame["VX_KM_S"].max()) < 10.0


def test_preset_identity_is_stable_and_public():
    assert PRESET_CASE_ID == "builtin-microseismic-vx-1911"
    assert PRESET_VERSION == "microseismic-vx-1911/v1"


def _write(tmp_path: Path, frame: pd.DataFrame, name: str = "candidate.csv") -> Path:
    target = tmp_path / name
    frame.to_csv(target, index=False, encoding="utf-8-sig")
    return target


def _valid_frame() -> pd.DataFrame:
    base = pd.read_csv(TRACKED_CSV, encoding="utf-8-sig")
    return base


def test_load_preset_rejects_wrong_header(tmp_path: Path):
    frame = _valid_frame().drop(columns=["N_MERGED"])
    with pytest.raises(PlatformError) as excinfo:
        load_microseismic_preset(_write(tmp_path, frame))
    assert excinfo.value.code == PRESET_SOURCE_INVALID


def test_load_preset_rejects_wrong_row_count(tmp_path: Path):
    frame = _valid_frame().iloc[:-1]
    with pytest.raises(PlatformError) as excinfo:
        load_microseismic_preset(_write(tmp_path, frame))
    assert excinfo.value.code == PRESET_SOURCE_INVALID


def test_load_preset_rejects_nonfinite_values(tmp_path: Path):
    frame = _valid_frame()
    frame.loc[0, "VX_KM_S"] = float("nan")
    with pytest.raises(PlatformError) as excinfo:
        load_microseismic_preset(_write(tmp_path, frame))
    assert excinfo.value.code == PRESET_SOURCE_INVALID


def test_load_preset_rejects_duplicate_xyz(tmp_path: Path):
    frame = _valid_frame()
    frame.loc[1, ["X_LOCAL_M", "Y_LOCAL_M", "Z_LOCAL_M"]] = frame.loc[
        0, ["X_LOCAL_M", "Y_LOCAL_M", "Z_LOCAL_M"]
    ]
    with pytest.raises(PlatformError) as excinfo:
        load_microseismic_preset(_write(tmp_path, frame))
    assert excinfo.value.code == PRESET_SOURCE_INVALID


def test_load_preset_missing_file_raises_typed_error(tmp_path: Path):
    with pytest.raises(PlatformError) as excinfo:
        load_microseismic_preset(tmp_path / "missing.csv")
    assert excinfo.value.code == PRESET_SOURCE_INVALID


# ---------------------------------------------------------------------------
# Task 2：官方普通克里金候选分析与基线冻结
# ---------------------------------------------------------------------------

from geomodeling.platform.microseismic_preset import (  # noqa: E402
    DEFAULT_BASELINE_PATH,
    NEIGHBOR_COUNTS,
    VARIOGRAM_MODELS,
    Z_SCALES,
    PresetSource,
    analyze_preset_candidates,
    load_official_baseline,
    preset_candidate_matrix,
    rank_preset_candidates,
    verify_official_baseline,
)
from geomodeling.platform.errors import PRESET_BASELINE_INVALID  # noqa: E402


def _entry(variogram_model, *, neighbor_count=24, z_scale=1.0, rmse, mae, r2):
    return {
        "params": {
            "variogram_model": variogram_model,
            "neighbor_count": neighbor_count,
            "z_scale": z_scale,
        },
        "metrics": {"rmse": rmse, "mae": mae, "r2": r2},
    }


def test_candidate_matrix_is_exactly_27_members():
    matrix = preset_candidate_matrix()
    assert len(matrix) == 27
    assert {m["variogram_model"] for m in matrix} == set(VARIOGRAM_MODELS)
    assert {m["neighbor_count"] for m in matrix} == set(NEIGHBOR_COUNTS)
    assert {m["z_scale"] for m in matrix} == set(Z_SCALES)


def test_rank_candidates_uses_finite_common_metrics_then_canonical_params():
    ranked = rank_preset_candidates(
        [
            _entry("gaussian", rmse=0.4, mae=0.2, r2=0.5),
            _entry("spherical", rmse=0.4, mae=0.2, r2=0.5),
            _entry("exponential", rmse=float("nan"), mae=0.1, r2=0.9),
        ]
    )
    assert [item["params"]["variogram_model"] for item in ranked] == ["gaussian", "spherical"]


def test_rank_candidates_orders_rmse_then_mae_then_r2():
    ranked = rank_preset_candidates(
        [
            _entry("spherical", rmse=0.41, mae=0.20, r2=0.90),
            _entry("gaussian", rmse=0.40, mae=0.21, r2=0.80),
            _entry("exponential", rmse=0.40, mae=0.20, r2=0.70),
        ]
    )
    assert [item["params"]["variogram_model"] for item in ranked] == [
        "exponential",
        "gaussian",
        "spherical",
    ]


def _synthetic_source() -> PresetSource:
    rng = np.random.default_rng(42)
    xs, ys, zs = [], [], []
    for ix in range(4):
        for iy in range(5):
            for iz in range(3):
                xs.append(ix * 120.0)
                ys.append(iy * 110.0)
                zs.append(-900.0 + iz * 150.0)
    x = np.array(xs)
    y = np.array(ys)
    z = np.array(zs)
    vx = 2.0 + 0.3 * np.sin(x / 300) + 0.2 * np.cos(y / 260) - 0.1 * (z / 900)
    vx += rng.normal(0, 0.01, size=len(vx))
    frame = pd.DataFrame(
        {"X_LOCAL_M": x, "Y_LOCAL_M": y, "Z_LOCAL_M": z, "VX_KM_S": vx}
    )
    return PresetSource(
        frame=frame,
        sha256="synthetic",
        row_count=len(frame),
        columns=REQUIRED_COLUMNS,
        source_columns=SOURCE_COLUMNS,
    )


def test_analyze_preset_candidates_builds_deterministic_27_candidate_report():
    source = _synthetic_source()
    report = analyze_preset_candidates(source)
    assert len(report.candidates) == 27
    assert report.validation == {"method": "spatial_kfold", "folds": 5, "seed": 20260723}
    again = analyze_preset_candidates(source)
    assert report.sha256 == again.sha256
    ranked = rank_preset_candidates(report.candidates)
    assert ranked, "合成源上必须存在有限指标候选"
    first = ranked[0]["params"]
    assert first["variogram_model"] in VARIOGRAM_MODELS


def test_committed_baseline_verifies_against_tracked_source(preset_csv: Path):
    source = load_microseismic_preset(preset_csv)
    baseline = load_official_baseline(DEFAULT_BASELINE_PATH)
    verify_official_baseline(source, baseline)
    assert baseline.winner["algorithm"] == "ordinary_kriging"
    assert baseline.winner["parameters"]["variogram_model"] in VARIOGRAM_MODELS


def test_verify_baseline_rejects_source_fingerprint_mismatch(preset_csv: Path):
    source = load_microseismic_preset(preset_csv)
    baseline = load_official_baseline(DEFAULT_BASELINE_PATH)
    tampered = PresetSource(
        frame=source.frame,
        sha256="0" * 64,
        row_count=source.row_count,
        columns=source.columns,
        source_columns=source.source_columns,
    )
    with pytest.raises(PlatformError) as excinfo:
        verify_official_baseline(tampered, baseline)
    assert excinfo.value.code == PRESET_BASELINE_INVALID


def test_verify_baseline_rejects_report_fingerprint_mismatch(preset_csv: Path):
    source = load_microseismic_preset(preset_csv)
    baseline = load_official_baseline(DEFAULT_BASELINE_PATH)
    report = analyze_preset_candidates(_synthetic_source())
    with pytest.raises(PlatformError) as excinfo:
        verify_official_baseline(source, baseline, report=report)
    assert excinfo.value.code == PRESET_BASELINE_INVALID


def test_baseline_grid_within_max_cells_and_covers_source_range(preset_csv: Path):
    source = load_microseismic_preset(preset_csv)
    baseline = load_official_baseline(DEFAULT_BASELINE_PATH)
    bounds = baseline.grid["bounds"]
    resolution = baseline.grid["resolution"]
    cells = 1
    for (lo, hi), res in zip(bounds, resolution):
        assert hi > lo and res > 0
        cells *= int(round((hi - lo) / res)) + 1
    assert 0 < cells <= baseline.grid["max_cells"]
    for idx, col in enumerate(("X_LOCAL_M", "Y_LOCAL_M", "Z_LOCAL_M")):
        assert bounds[idx][0] <= float(source.frame[col].min())
        assert bounds[idx][1] >= float(source.frame[col].max())
