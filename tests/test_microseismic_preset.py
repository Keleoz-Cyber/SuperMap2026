"""v0.7.0 Batch 1：微震 CSV 预置源合同测试（Task 1）。

受控 CSV 内置在仓库 ``example_data/微震局部三维点_3Sigma_去重均值_1911.csv``
（v0.8.0 第三批起默认源即用户指定原始标准化文件本身：纯 CRLF + UTF-8 BOM
形态，``example_data/*.csv`` 关闭 EOL 归一化，字节级冻结合同见
tests/test_example_data_contract.py）。9 列表头含 SAMPLE_IDS 等溯源列；
加载器钉死完整表头、1911 行、有限数值与唯一 XYZ，并向公共层只暴露 4 个
建模列与摘要指纹，绝不返回本机源路径。v0.7.0 时代的 LF 归一化入库副本
（``data/presets/microseismic/microseismic-vx-1911.csv``，sha256
ea3917c2…）已随默认源切换删除——同一逻辑数据，字节身份统一回原始形态。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from geomodeling.platform.errors import PRESET_SOURCE_INVALID, PlatformError
from geomodeling.platform.microseismic_preset import (
    DEFAULT_PRESET_CSV,
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
from geomodeling.platform.settings import example_data_path

REPO_ROOT = Path(__file__).resolve().parents[1]
#: v0.8.0 第三批：默认源即项目内 example_data/ 内置原始文件（CRLF+BOM 形态）
TRACKED_CSV = example_data_path(ORIGINAL_SOURCE_NAME)
#: 已删除的 v0.7.0 LF 归一化入库副本路径（默认源切换后冗余，绝不复活）
RETIRED_TRACKED_CSV = (
    REPO_ROOT / "data" / "presets" / "microseismic" / "microseismic-vx-1911.csv"
)


@pytest.fixture()
def preset_csv() -> Path:
    return TRACKED_CSV


def test_tracked_csv_is_byte_identified_and_never_outside_repo(preset_csv: Path):
    assert preset_csv.is_file()
    # example_data/*.csv 关闭 EOL 归一化：原始 CRLF + UTF-8 BOM 字节任何平台检出不变
    digest = hashlib.sha256(preset_csv.read_bytes()).hexdigest()
    assert digest == TRACKED_CSV_SHA256
    assert preset_csv.stat().st_size == TRACKED_CSV_BYTES
    assert preset_csv.resolve().is_relative_to(REPO_ROOT)
    assert preset_csv.read_bytes().startswith(b"\xef\xbb\xbf")
    # 身份迁移：内置默认源即用户指定原始文件（CRLF+BOM 形态），
    # 审计常量与受控身份同值（同一逻辑数据，字节形态统一回原始 CRLF）
    assert ORIGINAL_SOURCE_SHA256 == "4011de85e1fa7e49999fc5ae66a73e00a59dbec372a417ae0728d0a338c7765e"
    assert ORIGINAL_SOURCE_SHA256 == TRACKED_CSV_SHA256
    assert ORIGINAL_SOURCE_NAME.endswith("_1911.csv")
    assert preset_csv.name == ORIGINAL_SOURCE_NAME


def test_default_preset_csv_resolves_to_bundled_example_data():
    """默认源只解析到项目内 example_data/；旧 data/presets 副本已删除。"""
    assert DEFAULT_PRESET_CSV == TRACKED_CSV
    assert DEFAULT_PRESET_CSV.parent.name == "example_data"
    assert DEFAULT_PRESET_CSV.resolve().is_relative_to(REPO_ROOT)
    assert not RETIRED_TRACKED_CSV.exists()


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


# ---------------------------------------------------------------------------
# Task 3：官方成果 seed（常规生命周期链）
# ---------------------------------------------------------------------------

import threading  # noqa: E402

from geomodeling.platform import PlatformRuntime, tables  # noqa: E402
from geomodeling.platform.microseismic_preset import (  # noqa: E402
    seed_microseismic_preset,
)
from geomodeling.platform.repositories import featured_result_for_case  # noqa: E402


@pytest.fixture()
def runtime(tmp_path: Path):
    rt = PlatformRuntime(tmp_path / "runtime")
    rt.initialize()
    yield rt
    rt.close()


def _case_config(runtime, case_id: str) -> dict:
    with runtime.session() as session:
        case = session.get(tables.Case, case_id)
        return tables.loads_canonical(case.config_json) if case is not None else {}


def test_seed_creates_validated_dataset_official_result_and_formal_selection(runtime):
    seeded = seed_microseismic_preset(runtime)
    assert seeded.case_id == PRESET_CASE_ID
    assert seeded.workspace_kind == "builtin_preset"
    assert seeded.official_result.materialized is True
    assert seeded.official_result.url == f"/results/{seeded.official_result.result_id}"

    with runtime.session() as session:
        dataset = session.get(tables.DatasetVersion, seeded.dataset_version_id)
        assert dataset.status == "validated"
        profile = tables.loads_canonical(dataset.profile_json)
        assert profile["mapping"]["value_name"] == "Vx"
        assert profile["mapping"]["value_unit"] == "km/s"
        assert profile["mapping"]["coordinate_kind"] == "local_linear"
        assert profile["row_count"] == 1911
        assert profile["valid_row_count"] == 1911

        candidate = session.get(tables.CandidateResult, seeded.official_result.result_id)
        assert candidate.status == "succeeded"
        assert candidate.grid_path is not None
        params = tables.loads_canonical(candidate.params_json)
        assert params["variogram_model"] == "exponential"
        assert params["neighbor_count"] == 12
        assert params["z_scale"] == 2.0

        selections = (
            session.query(tables.FormalSelection)
            .filter(tables.FormalSelection.case_id == PRESET_CASE_ID)
            .all()
        )
        assert len(selections) == 1
        assert selections[0].candidate_result_id == seeded.official_result.result_id

    config = _case_config(runtime, PRESET_CASE_ID)
    assert config["workspace_kind"] == "builtin_preset"
    assert config["preset_version"] == PRESET_VERSION
    assert config["read_only"] is True
    assert config["source_sha256"] == TRACKED_CSV_SHA256

    featured = None
    with runtime.session() as session:
        featured = featured_result_for_case(session, PRESET_CASE_ID)
    assert featured is not None and featured.materialized is True


def test_seed_is_idempotent_and_never_replaces_existing_official_selection(runtime):
    first = seed_microseismic_preset(runtime)
    second = seed_microseismic_preset(runtime)
    assert second.official_result.result_id == first.official_result.result_id
    with runtime.session() as session:
        assert (
            session.query(tables.FormalSelection)
            .filter(tables.FormalSelection.case_id == PRESET_CASE_ID)
            .count()
            == 1
        )
        assert (
            session.query(tables.Run)
            .filter(tables.Run.experiment_id == first.experiment_id)
            .count()
            == 1
        )


def test_seed_concurrent_calls_never_create_double_selection(runtime):
    outcomes = []

    def worker():
        outcomes.append(seed_microseismic_preset(runtime).official_result.result_id)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=600)
    assert len(set(outcomes)) == 1
    with runtime.session() as session:
        assert (
            session.query(tables.FormalSelection)
            .filter(tables.FormalSelection.case_id == PRESET_CASE_ID)
            .count()
            == 1
        )


def test_seed_refuses_to_overwrite_when_fingerprints_differ(runtime):
    seeded = seed_microseismic_preset(runtime)
    with runtime.session() as session:
        case = session.get(tables.Case, PRESET_CASE_ID)
        config = tables.loads_canonical(case.config_json)
        config["baseline_sha256"] = "0" * 64
        case.config_json = tables.dumps_canonical(config)
        session.commit()
    with pytest.raises(PlatformError) as excinfo:
        seed_microseismic_preset(runtime)
    assert excinfo.value.code == PRESET_BASELINE_INVALID
    # 原正式选择保持不变
    with runtime.session() as session:
        selections = (
            session.query(tables.FormalSelection)
            .filter(tables.FormalSelection.case_id == PRESET_CASE_ID)
            .all()
        )
        assert len(selections) == 1
        assert selections[0].candidate_result_id == seeded.official_result.result_id


def test_seed_failure_leaves_no_partial_state(runtime, monkeypatch):
    import geomodeling.modeling.runner as runner_module

    def boom(*args, **kwargs):
        raise RuntimeError("injected runner failure")

    monkeypatch.setattr(runner_module, "execute_run", boom)
    monkeypatch.setattr(
        "geomodeling.platform.microseismic_preset.execute_run", boom, raising=False
    )
    with pytest.raises(Exception):
        seed_microseismic_preset(runtime)
    with runtime.session() as session:
        assert session.get(tables.Case, PRESET_CASE_ID) is None
        assert session.query(tables.DatasetVersion).count() == 0
        assert session.query(tables.Experiment).count() == 0
        assert session.query(tables.Run).count() == 0
        assert session.query(tables.CandidateResult).count() == 0
        assert session.query(tables.FormalSelection).count() == 0
    dataset_dir = runtime.settings.datasets_dir / PRESET_CASE_ID
    assert not dataset_dir.exists()
