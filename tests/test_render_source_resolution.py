"""v0.6.1 Task 4: candidate render-source resolution without fixed ``rho`` semantics.

解析链 ``candidate -> run -> experiment -> dataset_version.profile_json``：
属性名/单位/坐标类型一律来自数据集 profile 的 ``mapping``（通用电阻率类
``value_name="属性"``、微震 ``value_name="Vx"/value_unit="km/s"``），单位缺失
才回退字面 ``"unknown"``；老 metadata 缺 property 字段仍可解析。规则网格校验
fail-closed：非 3D、轴非法、轴不规则、形状不符、全 NoData、登记哈希与实际文件
哈希不符都产生稳定错误码。
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from pathlib import Path

import numpy as np
import pytest

from geomodeling.modeling.runner import execute_run
from geomodeling.platform import PlatformRuntime, tables
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.render_assets import (
    candidate_render_capability,
    resolve_candidate_render_source,
    validate_regular_grid,
)
from geomodeling.platform.results import materialize
from test_experiment_runner import (
    insert_run,
    load_candidates,
    make_runtime,
    make_standardized,
)

GENERIC_MAPPING = {
    "value_name": "属性",
    "value_unit": None,  # 通用 profile 缺单位 → 字面 "unknown"
    "coordinate_kind": "local_linear",
}
MICROSEISMIC_MAPPING = {
    "value_name": "Vx",
    "value_unit": "km/s",
    "coordinate_kind": "local_linear",
}


def _search_payload(dataset_id: str, dimension: str) -> dict:
    return {
        "dimension": dimension,
        "algorithm": "idw",
        "dataset_version_id": dataset_id,
        "search_mode": "manual",
        "parameters": {"power": 2.0, "neighbor_count": 8},
        "validation": {
            "method": "spatial_kfold",
            "folds": 3,
            "seed": 11,
            "holdout_fraction": 0.2,
        },
        "grid": None,
    }


def _insert_experiment(
    runtime: PlatformRuntime,
    case_id: str,
    dataset_id: str,
    search: dict,
    *,
    mapping_semantics: dict,
    case_type: str,
    standardized_path: Path,
) -> str:
    mapping = {
        "dimension": search["dimension"],
        "x": "x",
        "y": "y",
        "z": "z" if search["dimension"] == "3d" else None,
        "value": "value",
        "value_name": mapping_semantics["value_name"],
        "coordinate_kind": mapping_semantics["coordinate_kind"],
    }
    if mapping_semantics.get("value_unit") is not None:
        mapping["value_unit"] = mapping_semantics["value_unit"]
    profile = {
        "source_kind": "microseismic_dat_bundle"
        if case_type == "microseismic"
        else "csv_upload",
        "mapping": mapping,
        "source_sha256": "a" * 64,
        "standardized_sha256": "b" * 64,
        "standardized_path": str(standardized_path),
        "quality": {"status": "passed", "confirmed": True},
    }
    params = {key: value for key, value in search.items() if key != "dimension"}
    experiment_id = str(uuid.uuid4())
    with runtime.session() as session:
        session.add(
            tables.Case(
                id=case_id, name="渲染源案例", case_type=case_type, config_json="{}"
            )
        )
        session.add(
            tables.DatasetVersion(
                id=dataset_id,
                case_id=case_id,
                version=1,
                status="validated",
                source_path="source/data.csv",
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
        session.commit()
    return experiment_id


def run_and_materialize(
    runtime: PlatformRuntime,
    *,
    mapping_semantics: dict,
    case_type: str = "generic",
    dimension: str = "3d",
) -> tuple[str, dict]:
    """真实 run + 物化：返回 (candidate_id, 落盘 metadata)。"""

    case_id, dataset_id = str(uuid.uuid4()), str(uuid.uuid4())
    standardized_path, _ = make_standardized(runtime, case_id, dataset_id, dimension)
    experiment_id = _insert_experiment(
        runtime,
        case_id,
        dataset_id,
        _search_payload(dataset_id, dimension),
        mapping_semantics=mapping_semantics,
        case_type=case_type,
        standardized_path=standardized_path,
    )
    run_id = insert_run(runtime, experiment_id)
    outcome = execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "succeeded"
    candidate_id = next(
        c["id"] for c in load_candidates(runtime, run_id) if c["status"] == "succeeded"
    )
    materialize(runtime, candidate_id)
    grid_path = runtime.settings.result_grid(candidate_id)
    metadata = json.loads(
        (grid_path.parent / "metadata.json").read_text(encoding="utf-8")
    )
    return candidate_id, metadata


def insert_candidate_chain(
    runtime: PlatformRuntime,
    *,
    candidate_status: str = "succeeded",
    dimension: str = "3d",
) -> str:
    """不经 runner 直接落库归属链，用于手工构造网格工件的失败场景。"""

    case_id, dataset_id, experiment_id, run_id, candidate_id = (
        str(uuid.uuid4()) for _ in range(5)
    )
    profile = {
        "source_kind": "microseismic_dat_bundle",
        "mapping": {
            "dimension": dimension,
            "x": "x",
            "y": "y",
            "z": "z" if dimension == "3d" else None,
            "value": "value",
            "value_name": "Vx",
            "value_unit": "km/s",
            "coordinate_kind": "local_linear",
        },
        "source_sha256": "a" * 64,
        "standardized_sha256": "b" * 64,
        "standardized_path": "unused.parquet",
        "quality": {"status": "passed", "confirmed": True},
    }
    params = {
        "algorithm": "idw",
        "dataset_version_id": dataset_id,
        "search_mode": "manual",
        "parameters": {"power": 2.0, "neighbor_count": 8},
        "validation": {
            "method": "spatial_kfold",
            "folds": 3,
            "seed": 11,
            "holdout_fraction": 0.2,
        },
        "grid": None,
    }
    with runtime.session() as session:
        session.add(
            tables.Case(
                id=case_id, name="微震", case_type="microseismic", config_json="{}"
            )
        )
        session.add(
            tables.DatasetVersion(
                id=dataset_id,
                case_id=case_id,
                version=1,
                status="validated",
                source_path="source/manifest.json",
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
        session.add(
            tables.Run(id=run_id, experiment_id=experiment_id, status="succeeded")
        )
        session.commit()
    # 候选行单独提交：与 run 同事务时 UOW 不保插入序，FK 约束可能失败
    with runtime.session() as session:
        session.add(
            tables.CandidateResult(
                id=candidate_id,
                run_id=run_id,
                category="final",
                fingerprint="f" * 64,
                status=candidate_status,
                params_json=tables.dumps_canonical(params["parameters"]),
            )
        )
        session.commit()
    return candidate_id


def write_grid_artifact(
    runtime: PlatformRuntime,
    result_id: str,
    *,
    axes: tuple[np.ndarray, ...],
    values: np.ndarray,
    is_nodata: np.ndarray,
    dimension: str = "3d",
    grid_sha256: str | None = None,
) -> Path:
    """手工落盘 grid.npz + metadata.json；默认登记哈希=实际文件哈希。"""

    grid_path = runtime.settings.result_grid(result_id)
    grid_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        grid_path,
        axes=np.array(axes, dtype=object),
        values=np.asarray(values, dtype="float64"),
        is_nodata=np.asarray(is_nodata, dtype=bool),
    )
    actual = hashlib.sha256(grid_path.read_bytes()).hexdigest()
    metadata = {
        "result_id": result_id,
        "dimension": dimension,
        "shape": list(np.asarray(values).shape),
        "grid_sha256": grid_sha256 or actual,
        "created_at": "2026-08-04T00:00:00+00:00",
    }
    (grid_path.parent / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return grid_path


def regular_artifact(shape: tuple[int, int, int] = (4, 5, 3)):
    axes = (
        np.linspace(0.0, 30.0, shape[0]),
        np.linspace(200.0, 240.0, shape[1]),
        np.linspace(-60.0, 0.0, shape[2]),
    )
    i, j, k = np.indices(shape)
    values = 10.0 + i + j + k
    is_nodata = np.zeros(shape, dtype=bool)
    return axes, values.astype("float64"), is_nodata


def expect_error(
    runtime: PlatformRuntime, result_id: str, code: str, http_status: int
) -> None:
    with pytest.raises(PlatformError) as excinfo:
        resolve_candidate_render_source(runtime, result_id)
    assert excinfo.value.code == code
    assert excinfo.value.http_status == http_status


# ---------------------------------------------------------------------------
# 通用/微震语义的 happy path（不固定 rho 语义）
# ---------------------------------------------------------------------------


def test_generic_profile_resolves_property_without_units(tmp_path):
    runtime = make_runtime(tmp_path)
    candidate_id, metadata = run_and_materialize(
        runtime, mapping_semantics=GENERIC_MAPPING
    )

    # 新物化 metadata 追加 property 三键（取自 profile.mapping）
    assert metadata["property_name"] == "属性"
    assert metadata["units"] == "unknown"
    assert metadata["coordinate_kind"] == "local_linear"

    source = resolve_candidate_render_source(runtime, candidate_id)
    assert source.source_kind == "candidate_result"
    assert source.source_id == candidate_id
    assert source.property_name == "属性"
    assert source.units == "unknown"
    assert source.coordinate_kind == "local_linear"
    assert source.dimension == "3d"
    assert source.grid_path == runtime.settings.result_grid(candidate_id)
    assert source.grid_sha256 == metadata["grid_sha256"]


def test_microseismic_profile_resolves_vx_property(tmp_path):
    runtime = make_runtime(tmp_path)
    candidate_id, metadata = run_and_materialize(
        runtime, mapping_semantics=MICROSEISMIC_MAPPING, case_type="microseismic"
    )

    assert metadata["property_name"] == "Vx"
    assert metadata["units"] == "km/s"

    source = resolve_candidate_render_source(runtime, candidate_id)
    assert source.property_name == "Vx"
    assert source.units == "km/s"
    assert source.coordinate_kind == "local_linear"
    assert source.grid_sha256 == metadata["grid_sha256"]


def test_old_metadata_without_property_keys_still_resolves(tmp_path):
    """老 metadata 缺 property 字段仍可解析：语义来自数据集 profile，不改写工件。"""

    runtime = make_runtime(tmp_path)
    candidate_id, metadata = run_and_materialize(
        runtime, mapping_semantics=GENERIC_MAPPING
    )
    metadata_path = runtime.settings.result_grid(candidate_id).parent / "metadata.json"
    legacy = {
        key: value
        for key, value in metadata.items()
        if key not in ("property_name", "units", "coordinate_kind")
    }
    metadata_path.write_text(
        json.dumps(legacy, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    source = resolve_candidate_render_source(runtime, candidate_id)
    assert source.property_name == "属性"
    assert source.units == "unknown"
    assert source.coordinate_kind == "local_linear"
    assert source.grid_sha256 == legacy["grid_sha256"]


def test_validate_regular_grid_returns_bounds_of_valid_values(tmp_path):
    runtime = make_runtime(tmp_path)
    candidate_id, metadata = run_and_materialize(
        runtime, mapping_semantics=GENERIC_MAPPING
    )

    grid = validate_regular_grid(
        runtime.settings.result_grid(candidate_id), metadata["grid_sha256"]
    )
    assert len(grid.axes) == 3
    assert grid.values.shape == tuple(metadata["shape"])
    assert grid.is_nodata.shape == grid.values.shape
    assert grid.valid_min <= grid.valid_max


def test_capability_reports_supported_with_display_transform(tmp_path):
    runtime = make_runtime(tmp_path)
    candidate_id, _ = run_and_materialize(
        runtime, mapping_semantics=MICROSEISMIC_MAPPING
    )

    capability = candidate_render_capability(runtime, candidate_id)
    assert capability.source_kind == "candidate_result"
    assert capability.source_id == candidate_id
    assert capability.supported is True
    assert capability.reason_code is None
    assert capability.reason is None
    assert capability.dimension == "3d"
    assert capability.grid_kind == "regular"
    assert capability.property_name == "Vx"
    assert capability.units == "km/s"
    assert capability.geolocation_status == "display_anchor_only"
    assert capability.display_transform is not None
    assert capability.display_transform["contract"] == "wgs84_display_anchor_v1"


# ---------------------------------------------------------------------------
# 归属链与物化状态
# ---------------------------------------------------------------------------


def test_missing_candidate_rejected(tmp_path):
    runtime = make_runtime(tmp_path)
    expect_error(runtime, "missing-result", "CANDIDATE_NOT_FOUND", 404)


def test_capability_reraises_missing_candidate(tmp_path):
    runtime = make_runtime(tmp_path)
    with pytest.raises(PlatformError) as excinfo:
        candidate_render_capability(runtime, "missing-result")
    assert excinfo.value.code == "CANDIDATE_NOT_FOUND"


def test_not_succeeded_candidate_rejected(tmp_path):
    runtime = make_runtime(tmp_path)
    candidate_id = insert_candidate_chain(runtime, candidate_status="failed")
    expect_error(runtime, candidate_id, "CANDIDATE_NOT_SUCCEEDED", 409)


def test_unmaterialized_result_rejected(tmp_path):
    runtime = make_runtime(tmp_path)
    candidate_id = insert_candidate_chain(runtime)
    expect_error(runtime, candidate_id, "RESULT_NOT_MATERIALIZED", 404)

    capability = candidate_render_capability(runtime, candidate_id)
    assert capability.supported is False
    assert capability.reason_code == "RESULT_NOT_MATERIALIZED"
    assert capability.display_transform is None


# ---------------------------------------------------------------------------
# 网格维度与规则性（fail-closed，稳定错误码）
# ---------------------------------------------------------------------------


def test_two_dimensional_result_rejected(tmp_path):
    runtime = make_runtime(tmp_path)
    candidate_id = insert_candidate_chain(runtime, dimension="2d")
    axes = (np.linspace(0.0, 30.0, 4), np.linspace(200.0, 240.0, 5))
    values = np.ones((4, 5))
    write_grid_artifact(
        runtime,
        candidate_id,
        axes=axes,
        values=values,
        is_nodata=np.zeros((4, 5)),
        dimension="2d",
    )
    expect_error(runtime, candidate_id, "RENDER_REQUIRES_3D", 409)

    capability = candidate_render_capability(runtime, candidate_id)
    assert capability.supported is False
    assert capability.reason_code == "RENDER_REQUIRES_3D"


def test_axis_with_fewer_than_two_nodes_rejected(tmp_path):
    runtime = make_runtime(tmp_path)
    candidate_id = insert_candidate_chain(runtime)
    axes = (np.array([0.0]), np.linspace(200.0, 240.0, 5), np.linspace(-60.0, 0.0, 3))
    values = np.ones((1, 5, 3))
    write_grid_artifact(
        runtime, candidate_id, axes=axes, values=values, is_nodata=np.zeros((1, 5, 3))
    )
    expect_error(runtime, candidate_id, "RENDER_AXIS_INVALID", 409)


@pytest.mark.parametrize(
    "axis",
    [
        np.array([0.0, np.nan, 20.0, 30.0]),  # 非有限
        np.array([0.0, 20.0, 10.0, 30.0]),  # 非单调递增
        np.array([0.0, 10.0, 10.0, 30.0]),  # 重复节点（非严格递增）
    ],
    ids=["non_finite", "non_monotonic", "duplicate"],
)
def test_invalid_axis_rejected(tmp_path, axis):
    runtime = make_runtime(tmp_path)
    candidate_id = insert_candidate_chain(runtime)
    axes, values, is_nodata = regular_artifact()
    axes = (axis, axes[1], axes[2])
    write_grid_artifact(
        runtime, candidate_id, axes=axes, values=values, is_nodata=is_nodata
    )
    expect_error(runtime, candidate_id, "RENDER_AXIS_INVALID", 409)


def test_irregular_axis_rejected(tmp_path):
    runtime = make_runtime(tmp_path)
    candidate_id = insert_candidate_chain(runtime)
    axes, values, is_nodata = regular_artifact()
    axes = (np.array([0.0, 10.0, 15.0, 30.0]), axes[1], axes[2])  # 间距 10/5/15 不均
    write_grid_artifact(
        runtime, candidate_id, axes=axes, values=values, is_nodata=is_nodata
    )
    expect_error(runtime, candidate_id, "RENDER_GRID_IRREGULAR", 409)


@pytest.mark.parametrize("mismatch", ["values", "is_nodata"])
def test_grid_shape_mismatch_rejected(tmp_path, mismatch):
    runtime = make_runtime(tmp_path)
    candidate_id = insert_candidate_chain(runtime)
    axes, values, is_nodata = regular_artifact()
    if mismatch == "values":
        values = np.ones((4, 5, 2))  # 与轴长度 (4,5,3) 不符
    else:
        is_nodata = np.zeros((4, 5, 2), dtype=bool)
    write_grid_artifact(
        runtime, candidate_id, axes=axes, values=values, is_nodata=is_nodata
    )
    expect_error(runtime, candidate_id, "RENDER_GRID_SHAPE_MISMATCH", 409)


@pytest.mark.parametrize("mode", ["all_mask", "all_non_finite"])
def test_all_nodata_rejected(tmp_path, mode):
    runtime = make_runtime(tmp_path)
    candidate_id = insert_candidate_chain(runtime)
    axes, values, is_nodata = regular_artifact()
    if mode == "all_mask":
        is_nodata = np.ones(values.shape, dtype=bool)
        values = np.full(values.shape, np.nan)
    else:
        values = np.full(values.shape, np.inf)  # 掩膜全 False 但无有限有效值
    write_grid_artifact(
        runtime, candidate_id, axes=axes, values=values, is_nodata=is_nodata
    )
    expect_error(runtime, candidate_id, "RENDER_NO_VALID_VALUES", 409)


def test_grid_identity_mismatch_rejected(tmp_path):
    runtime = make_runtime(tmp_path)
    candidate_id = insert_candidate_chain(runtime)
    axes, values, is_nodata = regular_artifact()
    write_grid_artifact(
        runtime,
        candidate_id,
        axes=axes,
        values=values,
        is_nodata=is_nodata,
        grid_sha256="0" * 64,
    )
    expect_error(runtime, candidate_id, "RENDER_GRID_IDENTITY_MISMATCH", 409)


# ---------------------------------------------------------------------------
# v0.8.0 Task 6：seed 电阻率官方成果经 candidate_result 链解析
# ---------------------------------------------------------------------------


def test_seeded_resistivity_official_result_resolves_as_candidate_source(tmp_path):
    """seed 后官方成果走统一 candidate_result 渲染源（取代 builtin_legacy 默认路径）。

    legacy 渲染源的产品解析入口已 410 退役（见 test_rendering_api /
    test_resistivity_preset_seed）；本测试锁定新链：官方候选与任何用户候选
    一样经 profile mapping 解析出 RHO/local_linear 语义。
    """

    from geomodeling.platform.resistivity_preset import (
        load_resistivity_preset,
        seed_resistivity_preset,
    )
    from test_resistivity_preset import write_resistivity_fixture
    from test_resistivity_preset_seed import _fixture_baseline

    runtime = make_runtime(tmp_path)
    source_path = write_resistivity_fixture(tmp_path / "rho-source.csv", rows=17_549)
    source = load_resistivity_preset(source_path)
    seeded = seed_resistivity_preset(
        runtime, source_path=source_path, baseline=_fixture_baseline(source)
    )

    resolved = resolve_candidate_render_source(runtime, seeded.official_result.result_id)
    assert resolved.source_kind == "candidate_result"
    assert resolved.source_id == seeded.official_result.result_id
    assert resolved.property_name == "RHO"
    assert resolved.units == "RHO 单位待来源确认"
    assert resolved.coordinate_kind == "local_linear"
    assert resolved.dimension == "3d"
