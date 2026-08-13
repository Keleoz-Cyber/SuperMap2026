"""Result materialization, preview, and slice serving.

A succeeded candidate is materialized once: the interpolator is refit on
all validated rows and evaluated on the persisted rule grid, written as
``grid.npz`` plus ``metadata.json`` through an atomic directory replace.
Previews are deterministically decimated at 50,000 cells; slices always
read the persisted artifact — they never rerun interpolation.

v0.6.1（Task 7）：结果 metadata/preview/slices 的 GET 路径是纯查询——
``POST /materialize`` 是唯一创建操作；``read_materialized_metadata`` 与
``load_grid`` 只读既有工件，绝不隐式物化。

v0.6 专业候选（Task 15，设计 §5.3/§6.4/§9/§10）：物化在同一事务式目录
流水中额外落盘专业不确定性网格——Kriging 原生标准差（能力按算法矩阵，
IDW 为 ``not_applicable`` 且绝不生成空文件占位）与全算法经验误差尺度
（来自候选 OOF 工件，与候选同一空间变换指纹；邻点不足即 NoData，绝不
用全局 RMSE 填充）。所有不确定性场与值网格共享同一物理坐标轴；最终
模型在全部有效建模数据上重新拟合并标记 ``final_full_data_fit``（人工
固定参数策略继续用已确认参数，折内参数只用于验证指标，两类参数在
metadata 中分别展示）。同级临时目录写齐 → 回读校验 shape/hash → 原子
替换 → 替换成功后才更新数据库工件行；失败逐步清理且清理异常不覆盖
业务异常。重复 materialize 重读既有工件并验证（manifest 哈希 + 网格
形状），不盲目重算。legacy 候选路径逐字节兼容：不产生任何专业文件，
metadata 不含 ``professional`` 键。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from geomodeling.modeling.anisotropy import KrigingAnisotropySpec, build_kriging_transform
from geomodeling.modeling.contracts import GridDefinition
from geomodeling.modeling.dsi_like import DSILikeInterpolator
from geomodeling.modeling.grid import derive_grid
from geomodeling.modeling.idw import IDWInterpolator
from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator
from geomodeling.modeling.kriging_rf_residual import KrigingRFResidualInterpolator
from geomodeling.modeling.random_forest import RandomForestSpatialInterpolator
from geomodeling.modeling.professional_contracts import (
    CapabilityState,
    EmpiricalUncertaintySpec,
    NeighborhoodSpec,
    capabilities_for,
)
from geomodeling.modeling.slices import GridResult, extract_slice
from geomodeling.platform.slice_analysis import extract_grid_plane
from geomodeling.modeling.uncertainty import empirical_error_scale, identity_transform
from geomodeling.platform import tables
from geomodeling.platform.ml_artifacts import read_ml_fields_manifest, write_ml_fields
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.experiments import PROFESSIONAL_CAPABILITY_NOT_APPLICABLE
from geomodeling.platform.schemas import Algorithm, GridSpec
from geomodeling.platform.settings import PlatformSettings

RESULT_NOT_MATERIALIZED = "RESULT_NOT_MATERIALIZED"
RESULT_ARTIFACT_INVALID = "RESULT_ARTIFACT_INVALID"
CANDIDATE_NOT_SUCCEEDED = "CANDIDATE_NOT_SUCCEEDED"
PREVIEW_CELL_CAP = 50_000
DEFAULT_AXIS_NODES = 11

# 与 runner.py 同串（两处常量不互引，避免 runner ↔ results 循环依赖，
# 与 professional.py 的 CANCEL_REQUESTED 同款约定）。
PROFESSIONAL_ARTIFACT_WRITE_FAILED = "PROFESSIONAL_ARTIFACT_WRITE_FAILED"
PROFESSIONAL_ARTIFACT_INCOMPLETE = "PROFESSIONAL_ARTIFACT_INCOMPLETE"
PROFESSIONAL_LAYER_NOT_MATERIALIZED = "PROFESSIONAL_LAYER_NOT_MATERIALIZED"
PREVIEW_LAYER_UNKNOWN = "PREVIEW_LAYER_UNKNOWN"

PREVIEW_LAYERS = ("value", "empirical_error", "kriging_std")

# 预览层 → （工件文件名，数组键）
_LAYER_ARTIFACTS = {
    "empirical_error": ("empirical_error_scale.npz", "scale"),
    "kriging_std": ("kriging_standard_deviation.npz", "values"),
}

# 专业 npz 工件 → 必须与值网格同形状的数组键（同一物理轴）
_PROFESSIONAL_NPZ_KEYS = {
    "empirical_error_scale.npz": ("scale", "is_nodata", "neighbor_count"),
    "kriging_standard_deviation.npz": ("values", "is_nodata"),
}

_INTERPOLATORS = {
    Algorithm.IDW.value: IDWInterpolator(),
    Algorithm.ORDINARY_KRIGING.value: OrdinaryKrigingInterpolator(),
    Algorithm.DSI_LIKE.value: DSILikeInterpolator(),
    Algorithm.RANDOM_FOREST_SPATIAL.value: RandomForestSpatialInterpolator(),
    Algorithm.KRIGING_RF_RESIDUAL.value: KrigingRFResidualInterpolator(),
}

_ML_ALGORITHMS = {
    Algorithm.RANDOM_FOREST_SPATIAL.value,
    Algorithm.KRIGING_RF_RESIDUAL.value,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _grid_spec_from_data(
    frame: pd.DataFrame, dimension: str, requested: GridSpec | None
) -> GridDefinition:
    coord_cols = ["x", "y"] + (["z"] if dimension == "3d" else [])
    points = frame[coord_cols].to_numpy(dtype="float64")
    if requested is not None:
        return derive_grid(points, dimension, requested)
    bounds = [(float(points[:, i].min()), float(points[:, i].max())) for i in range(points.shape[1])]
    resolution = [
        (hi - lo) / (DEFAULT_AXIS_NODES - 1) if hi > lo else 1.0
        for lo, hi in bounds
    ]
    return derive_grid(points, dimension, GridSpec(bounds=bounds, resolution=resolution))


def _load_candidate(runtime, result_id: str):
    """Resolve result → run → experiment, verifying every ownership link."""

    with runtime.session() as session:
        candidate = session.get(tables.CandidateResult, result_id)
        if candidate is None:
            raise PlatformError(
                "CANDIDATE_NOT_FOUND", "成果不存在", {"result_id": result_id}, http_status=404
            )
        run = session.get(tables.Run, candidate.run_id)
        if run is None:
            raise PlatformError(
                "RUN_NOT_FOUND",
                "成果所属运行缺失，归属链不完整",
                {"result_id": result_id, "run_id": candidate.run_id},
                http_status=409,
            )
        experiment = session.get(tables.Experiment, run.experiment_id)
        if experiment is None:
            raise PlatformError(
                "EXPERIMENT_NOT_FOUND",
                "成果所属实验缺失，归属链不完整",
                {"result_id": result_id, "experiment_id": run.experiment_id},
                http_status=409,
            )
        return candidate, run, experiment


def _mapping_property_semantics(
    profile: dict[str, Any], *, case_id: str | None = None
) -> dict[str, str]:
    """property 三键（v0.6.1 渲染语义）：property_name/units/coordinate_kind。

    取自数据集 profile 的 ``mapping.value_name`` / ``mapping.value_unit`` /
    ``mapping.coordinate_kind``，**不固定 rho 语义**（通用电阻率类与微震
    profile 走同一映射）；``value_unit`` 缺失才回退字面 ``"unknown"``。正常
    profile 经 FieldMapping 校验必有 value_name/coordinate_kind，回退值只
    兜底绕过验证写入的旧 profile。
    """

    from geomodeling.platform.property_semantics import normalize_property_unit

    mapping = profile.get("mapping", {}) if isinstance(profile, dict) else {}
    value_name = str(mapping.get("value_name") or "value")
    workspace_kind = "builtin_preset" if case_id == "resistivity" else None
    units = normalize_property_unit(
        case_id=case_id,
        workspace_kind=workspace_kind,
        value_name=value_name,
        value_unit=mapping.get("value_unit"),
    )
    return {
        "property_name": value_name,
        "units": str(units or "unknown"),
        "coordinate_kind": str(mapping.get("coordinate_kind") or "local_linear"),
    }


def _result_metadata(
    *,
    result_id: str,
    run,
    experiment,
    dataset_version_id: str,
    params: dict[str, Any],
    candidate_params: dict[str, Any],
    dimension: str,
    grid: GridDefinition,
    grid_values: np.ndarray,
    nodata: np.ndarray,
    grid_sha: str,
    profile: dict[str, Any],
    fingerprint: str,
) -> dict[str, Any]:
    """结果级 metadata（键顺序即落盘 JSON 顺序，逐位确定）。

    v0.6.1（Task 4）在尾部追加 property 三键（``property_name``/``units``/
    ``coordinate_kind``，取自 profile.mapping）；只对**新物化**成果生效——
    幂等重读绝不改写既有 metadata.json，渲染源解析对新老 metadata 均可读。
    """

    shape = grid.shape
    finite = grid_values[np.isfinite(grid_values)]
    return {
        "result_id": result_id,
        "run_id": run.id,
        "experiment_id": experiment.id,
        "dataset_version_id": dataset_version_id,
        "algorithm": params["algorithm"],
        "parameters": candidate_params,
        "dimension": dimension,
        "shape": list(shape),
        "cell_count": int(np.prod(shape)),
        "bounds": [list(map(float, b)) for b in grid.bounds],
        "resolution": [float(r) for r in grid.resolution],
        "value_range": [float(finite.min()), float(finite.max())] if finite.size else [None, None],
        "nodata_count": int(nodata.sum()),
        "grid_sha256": grid_sha,
        "source_sha256": profile.get("source_sha256"),
        "standardized_sha256": profile.get("standardized_sha256"),
        "fingerprint": fingerprint,
        "validation": params.get("validation"),
        "created_at": tables.utc_now_iso(),
        # v0.6.1（Task 4）追加：渲染 property 语义三键（顺序锁定在尾部）
        **_mapping_property_semantics(profile, case_id=experiment.case_id),
    }


# ---------------------------------------------------------------------------
# 专业物化（Task 15）：不确定性网格、参数出处、事务式落盘
# ---------------------------------------------------------------------------


def _professional_distance_transform(algorithm: str, candidate_params: dict[str, Any], dimension: str):
    """候选的经验误差距离变换（与拟合距离同一空间、同一指纹）。

    Kriging 候选复用其确认规范 ``SpatialTransform``；IDW 候选使用 legacy
    ``z_scale`` 距离空间（2D 为恒等变换），两者都携带规范变换指纹。
    """

    if algorithm == Algorithm.ORDINARY_KRIGING.value:
        anisotropy = candidate_params.get("anisotropy")
        if anisotropy is None:
            raise PlatformError(
                PROFESSIONAL_ARTIFACT_INCOMPLETE,
                "专业 Kriging 候选缺少确认的各向异性变换",
                {"algorithm": algorithm},
                http_status=409,
            )
        return build_kriging_transform(KrigingAnisotropySpec.model_validate(anisotropy))
    if dimension == "3d":
        return build_kriging_transform(
            KrigingAnisotropySpec.from_legacy_z_scale(float(candidate_params.get("z_scale", 1.0)))
        )
    return identity_transform(2)


def _empirical_spec_for(
    professional: dict[str, Any], candidate_params: dict[str, Any]
) -> EmpiricalUncertaintySpec:
    """经验不确定性配置：显式误差邻域优先，否则复用候选搜索邻域（§10.2）。"""

    spec = EmpiricalUncertaintySpec.model_validate(professional.get("empirical_uncertainty") or {})
    if spec.neighborhood is None and candidate_params.get("neighborhood") is not None:
        spec = spec.model_copy(
            update={"neighborhood": NeighborhoodSpec.model_validate(candidate_params["neighborhood"])}
        )
    return spec


def _parameter_provenance(
    algorithm: str, professional: dict[str, Any], batch
) -> dict[str, Any]:
    """折内参数与全数据拟合参数分别标记（§6.4 末段），互不混述。

    自动策略：物化时在全部有效建模数据上重新拟合一次，标记
    ``final_full_data_fit``；人工固定参数策略继续用已确认参数
    （``manual_confirmed``，用户先验）。折内参数只用于验证指标。
    """

    if algorithm == Algorithm.ORDINARY_KRIGING.value:
        manual = professional.get("parameter_strategy") == "manual"
        final_origin = "manual_confirmed" if manual else "final_full_data_fit"
        validation_origin = "manual_confirmed" if manual else "automatic_candidate"
    else:
        # IDW 无拟合参数：折内仅训练子集邻域树，物化树覆盖全部有效行
        final_origin = "final_full_data_fit"
        validation_origin = "fold_training_subsets"
    provenance: dict[str, Any] = {
        "validation": {
            "origin": validation_origin,
            "scope": "fold_training_subsets",
            "evidence": "prediction_diagnostics.json",
        },
        "final": {
            "origin": final_origin,
            "scope": "all_valid_rows",
        },
    }
    variogram = (batch.diagnostics or {}).get("variogram")
    if variogram is not None:
        provenance["final"]["variogram"] = variogram
    return provenance


def materialize(runtime: PlatformRuntime, result_id: str) -> dict[str, Any]:
    """Materialize the full-resolution grid for a succeeded candidate (idempotent)."""

    candidate, run, experiment = _load_candidate(runtime, result_id)
    if candidate.status != "succeeded":
        raise PlatformError(
            CANDIDATE_NOT_SUCCEEDED,
            "只有成功候选可以生成正式成果",
            {"result_id": result_id, "status": candidate.status},
            http_status=409,
        )

    # 归属链最后一环：result → run → experiment → dataset 全部核验后才返回。
    params = tables.loads_canonical(experiment.params_json)
    dataset_version_id = params["dataset_version_id"]
    with runtime.session() as session:
        dataset = session.get(tables.DatasetVersion, dataset_version_id)
    if dataset is None:
        raise PlatformError(
            "DATASET_NOT_FOUND",
            "成果所属数据版本缺失，归属链不完整",
            {"result_id": result_id, "dataset_version_id": dataset_version_id},
            http_status=409,
        )

    grid_path = runtime.settings.result_grid(result_id)
    metadata_path = grid_path.parent / "metadata.json"
    professional = params.get("professional") or None
    if grid_path.exists() and metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        # 旧版落盘的 metadata 可能缺该字段，读取时补齐而不改写工件。
        metadata.setdefault("dataset_version_id", dataset_version_id)
        if professional is not None and runtime.settings.professional_result_manifest(result_id).is_file():
            # 幂等重读：回读既有专业工件并验证（manifest 哈希 + 网格形状），不盲目重算
            _verify_professional_materialization(runtime, result_id, metadata)
        if params["algorithm"] in _ML_ALGORITHMS:
            read_ml_fields_manifest(
                grid_path.parent,
                expected_grid_sha256=metadata.get("grid_sha256"),
            )
        return metadata

    profile = tables.loads_canonical(dataset.profile_json)
    mapping = profile.get("mapping", {})
    dimension = "3d" if mapping.get("dimension") == "3d" else "2d"

    frame = pd.read_parquet(Path(profile["standardized_path"]))
    valid = frame.loc[frame["is_numeric_valid"]].reset_index(drop=True)
    coord_cols = ["x", "y"] + (["z"] if dimension == "3d" else [])
    points = valid[coord_cols].to_numpy(dtype="float64")
    values = valid["value"].to_numpy(dtype="float64")

    interpolator = _INTERPOLATORS[params["algorithm"]]
    candidate_params = tables.loads_canonical(candidate.params_json)
    validated = interpolator.validate_parameters(candidate_params, dimension)
    # 最终物化拟合：在全部有效建模数据上重新拟合一次（设计 §6.4 末段；
    # 折内参数只用于验证指标，全数据拟合参数只用于最终空间成果）
    fitted = interpolator.fit(points, values, validated)

    grid_spec = GridSpec.model_validate(params["grid"]) if params.get("grid") else None
    grid = _grid_spec_from_data(valid, dimension, grid_spec)
    query = np.stack(np.meshgrid(*grid.axes, indexing="ij"), axis=-1).reshape(-1, len(grid.axes))
    batch = fitted.predict(query, cancel=lambda: False)
    shape = grid.shape
    grid_values = batch.values.reshape(shape)
    nodata = batch.is_nodata.reshape(shape)

    if professional is not None:
        # 专业候选：不确定性网格与 metadata/manifest 在同一事务式流水中落盘；
        # 失败逐步清理且不更新任何数据库状态。
        return _write_professional_materialization(
            runtime,
            candidate=candidate,
            run=run,
            experiment=experiment,
            params=params,
            professional=professional,
            candidate_params=candidate_params,
            profile=profile,
            dataset_version_id=dataset_version_id,
            dimension=dimension,
            grid=grid,
            query=query,
            batch=batch,
            result_id=result_id,
        )

    if params["algorithm"] in _ML_ALGORITHMS:
        return _write_ml_materialization(
            runtime,
            candidate=candidate,
            run=run,
            experiment=experiment,
            params=params,
            candidate_params=candidate_params,
            profile=profile,
            dataset_version_id=dataset_version_id,
            dimension=dimension,
            grid=grid,
            batch=batch,
            result_id=result_id,
        )

    # 原子落盘：临时目录写齐 → 校验 → 目录替换（legacy 路径逐字节不变）
    final_dir = grid_path.parent
    final_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="result-", dir=final_dir.parent))
    tmp_grid = tmp_dir / "grid.npz"
    np.savez_compressed(tmp_grid, axes=np.array(grid.axes, dtype=object), values=grid_values, is_nodata=nodata)
    grid_sha = _sha256(tmp_grid)
    metadata = _result_metadata(
        result_id=result_id,
        run=run,
        experiment=experiment,
        dataset_version_id=dataset_version_id,
        params=params,
        candidate_params=candidate_params,
        dimension=dimension,
        grid=grid,
        grid_values=grid_values,
        nodata=nodata,
        grid_sha=grid_sha,
        profile=profile,
        fingerprint=candidate.fingerprint,
    )
    (tmp_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    with np.load(tmp_grid, allow_pickle=True) as probe:
        if probe["values"].shape != tuple(shape):
            raise PlatformError(RESULT_ARTIFACT_INVALID, "成果网格形状校验失败")
    os.replace(tmp_grid, grid_path)
    os.replace(tmp_dir / "metadata.json", metadata_path)
    tmp_dir.rmdir()

    with runtime.session() as session:
        row = session.get(tables.CandidateResult, result_id)
        row.grid_path = str(grid_path)
        session.commit()
    return metadata


def _write_ml_materialization(
    runtime: PlatformRuntime,
    *,
    candidate,
    run,
    experiment,
    params: dict[str, Any],
    candidate_params: dict[str, Any],
    profile: dict[str, Any],
    dataset_version_id: str,
    dimension: str,
    grid: GridDefinition,
    batch,
    result_id: str,
) -> dict[str, Any]:
    """Write the primary ML field and all auxiliary fields as one verified set."""

    algorithm = params["algorithm"]
    shape = grid.shape
    grid_values = batch.values.reshape(shape)
    nodata = batch.is_nodata.reshape(shape)
    result_dir = runtime.settings.result_grid(result_id).parent
    result_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="ml-result-", dir=result_dir.parent))
    try:
        tmp_grid = tmp_dir / "grid.npz"
        np.savez_compressed(
            tmp_grid,
            axes=np.array(grid.axes, dtype=object),
            values=grid_values,
            is_nodata=nodata,
        )
        grid_sha = _sha256(tmp_grid)
        if algorithm == Algorithm.RANDOM_FOREST_SPATIAL.value:
            field_names = ("model_dispersion",)
        else:
            field_names = (
                "model_dispersion",
                "kriging_baseline",
                "residual_correction",
            )
        fields: dict[str, np.ndarray] = {}
        field_nodata: dict[str, np.ndarray] = {}
        for name in field_names:
            values = batch.auxiliary.get(name)
            if values is None:
                raise PlatformError(
                    "ML_ARTIFACT_INVALID",
                    "机器学习候选缺少必需辅助场",
                    {"algorithm": algorithm, "field": name},
                    http_status=409,
                )
            reshaped = np.asarray(values, dtype="float64").reshape(shape)
            fields[name] = reshaped
            field_nodata[name] = nodata | ~np.isfinite(reshaped)
        ml_manifest = write_ml_fields(
            tmp_dir,
            algorithm=algorithm,
            axes=grid.axes,
            fields=fields,
            nodata=field_nodata,
            main_grid_sha256=grid_sha,
            property_unit=_mapping_property_semantics(
                profile, case_id=experiment.case_id
            ).get("units"),
        )
        metadata = _result_metadata(
            result_id=result_id,
            run=run,
            experiment=experiment,
            dataset_version_id=dataset_version_id,
            params=params,
            candidate_params=candidate_params,
            dimension=dimension,
            grid=grid,
            grid_values=grid_values,
            nodata=nodata,
            grid_sha=grid_sha,
            profile=profile,
            fingerprint=candidate.fingerprint,
        )
        metadata["ml_fields"] = ml_manifest["fields"]
        metadata["ml"] = {
            "feature_version": candidate_params.get("feature_version"),
            "sklearn_version": (batch.diagnostics or {}).get("sklearn_version")
            or ((batch.diagnostics or {}).get("residual_model") or {}).get("sklearn_version"),
            "limitations": [
                "模型离散度为树间预测标准差参考，不是严格概率置信区间。",
                "机器学习结果必须结合空间交叉验证指标和地质背景解释。",
            ],
        }
        tmp_metadata = tmp_dir / "metadata.json"
        tmp_metadata.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        with np.load(tmp_grid, allow_pickle=True) as probe:
            if probe["values"].shape != tuple(shape):
                raise PlatformError(RESULT_ARTIFACT_INVALID, "成果网格形状校验失败")
        read_ml_fields_manifest(tmp_dir, expected_grid_sha256=grid_sha)

        for name in ("grid.npz", "ml_fields.npz", "ml_fields.json", "metadata.json"):
            os.replace(tmp_dir / name, result_dir / name)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    with runtime.session() as session:
        row = session.get(tables.CandidateResult, result_id)
        row.grid_path = str(runtime.settings.result_grid(result_id))
        session.commit()
    return metadata


def _write_professional_materialization(
    runtime: PlatformRuntime,
    *,
    candidate,
    run,
    experiment,
    params: dict[str, Any],
    professional: dict[str, Any],
    candidate_params: dict[str, Any],
    profile: dict[str, Any],
    dataset_version_id: str,
    dimension: str,
    grid: GridDefinition,
    query: np.ndarray,
    batch,
    result_id: str,
) -> dict[str, Any]:
    """专业候选物化：不确定性网格 + metadata/manifest，事务式原子暴露。

    全部计算先于任何写入；同级临时目录写齐 → 回读校验 shape/hash → 原子
    替换（跟踪已替换文件）→ manifest 校验 → 结果 grid/metadata 落盘 →
    最后才更新数据库（候选 ``grid_path`` + 专业工件行 manifest）。失败逐
    步清理已替换的新工件（run 期 fold/OOF/诊断证据不动），清理异常只记
    日志，绝不覆盖原业务异常。
    """

    # 同包私有复用（与 fold_artifacts 复用 splits 私有助手同款约定）；
    # 延迟导入避免 platform.professional ↔ platform.results 循环依赖。
    from geomodeling.platform.professional import (
        _atomic_write_file,
        _cleanup_failed_write,
        _json_bytes,
        _npz_bytes,
        verify_manifest,
    )

    algorithm = params["algorithm"]
    shape = grid.shape
    capabilities = capabilities_for(algorithm)
    grid_path = runtime.settings.result_grid(result_id)
    metadata_path = grid_path.parent / "metadata.json"
    professional_dir = runtime.settings.professional_result_dir(result_id)
    manifest_path = runtime.settings.professional_result_manifest(result_id)

    # ------------------------------------------------------------------
    # 1. 计算（任何写入前完成；失败即传播，无部分状态）
    # ------------------------------------------------------------------
    oof_path = professional_dir / "out_of_fold_predictions.parquet"
    assignments_path = professional_dir / "fold_assignments.parquet"
    diagnostics_path = professional_dir / "prediction_diagnostics.json"
    for evidence in (oof_path, assignments_path, diagnostics_path):
        if not evidence.is_file():
            raise PlatformError(
                PROFESSIONAL_ARTIFACT_INCOMPLETE,
                "专业候选折证据不完整，无法物化",
                {"result_id": result_id, "artifact": evidence.name},
                http_status=409,
            )
    spec = _empirical_spec_for(professional, candidate_params)
    transform = _professional_distance_transform(algorithm, candidate_params, dimension)
    oof = pd.read_parquet(oof_path)
    coord_cols = ["x", "y"] + (["z"] if dimension == "3d" else [])
    # 查询点=规则网格物理节点；残差为 OOF 折外记录（is_nodata 行残差为
    # NaN，由经验误差模块在进入邻域前排除）
    empirical = empirical_error_scale(
        residual_points=oof[coord_cols].to_numpy(dtype="float64"),
        residuals=oof["residual"].to_numpy(dtype="float64"),
        query=query,
        spec=spec,
        distance_transform=transform,
    )

    grid_values = batch.values.reshape(shape)
    nodata = batch.is_nodata.reshape(shape)
    native_std_available = (
        algorithm == Algorithm.ORDINARY_KRIGING.value
        and capabilities.native_kriging_std is CapabilityState.SUPPORTED
    )

    payloads: dict[str, bytes] = {
        "empirical_error_scale.npz": _npz_bytes(
            scale=empirical.scale.reshape(shape),
            is_nodata=empirical.is_nodata.reshape(shape),
            neighbor_count=empirical.neighbor_count.reshape(shape),
        )
    }
    if native_std_available:
        std_flat = batch.auxiliary.get("kriging_standard_deviation")
        if std_flat is None:
            raise PlatformError(
                PROFESSIONAL_ARTIFACT_INCOMPLETE,
                "Kriging 候选缺少原生标准差辅助数组",
                {"result_id": result_id},
                http_status=409,
            )
        std = np.asarray(std_flat, dtype="float64").reshape(shape)
        # NaN 处理与值网格一致：NoData 处 NaN + is_nodata 掩膜
        payloads["kriging_standard_deviation.npz"] = _npz_bytes(
            values=std,
            is_nodata=~np.isfinite(std),
        )
    provenance = _parameter_provenance(algorithm, professional, batch)
    grid_identity = {
        "shape": list(shape),
        "bounds": [list(map(float, b)) for b in grid.bounds],
        "resolution": [float(r) for r in grid.resolution],
    }
    neighborhood_summary = {
        "candidate_result_id": result_id,
        "algorithm": algorithm,
        "candidate_neighborhood": candidate_params.get("neighborhood"),
        "empirical_uncertainty": spec.model_dump(mode="json"),
        "empirical_error_scale": empirical.diagnostics,
        "final_fit_diagnostics": batch.diagnostics,
        "created_at": tables.utc_now_iso(),
    }
    payloads["neighborhood_summary.json"] = _json_bytes(neighborhood_summary)
    professional_metadata = {
        "candidate_result_id": result_id,
        "run_id": run.id,
        "experiment_id": experiment.id,
        "algorithm": algorithm,
        "fingerprint": candidate.fingerprint,
        "confirmation_id": professional.get("confirmation_id"),
        "capabilities": capabilities.model_dump(mode="json"),
        "parameter_provenance": provenance,
        "grid": grid_identity,
        "transform_fingerprint": empirical.diagnostics.get("transform_fingerprint"),
        "artifacts": {
            "empirical_error_scale": {
                "available": True,
                "capability": capabilities.empirical_error_scale.value,
                "coverage": empirical.diagnostics["coverage"],
                "covered_queries": empirical.diagnostics["covered_queries"],
                "total_queries": empirical.diagnostics["total_queries"],
            },
            "kriging_standard_deviation": {
                "available": bool(native_std_available),
                "capability": capabilities.native_kriging_std.value,
            },
        },
        "created_at": tables.utc_now_iso(),
    }
    payloads["metadata.json"] = _json_bytes(professional_metadata)

    # ------------------------------------------------------------------
    # 2. 同级临时目录写齐 → 回读校验 shape/hash → 原子替换 → manifest 校验
    # ------------------------------------------------------------------
    professional_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="professional-", dir=professional_dir.parent))
    moved: list[Path] = []
    try:
        for name, data in payloads.items():
            (tmp_dir / name).write_bytes(data)
        entries: dict[str, dict[str, Any]] = {}
        for name, expected in payloads.items():
            blob = (tmp_dir / name).read_bytes()
            if blob != expected:
                raise PlatformError(
                    PROFESSIONAL_ARTIFACT_WRITE_FAILED, "专业工件回读校验失败", {"file": name}
                )
            entries[name] = {
                "file": name,
                "sha256": hashlib.sha256(blob).hexdigest(),
                "bytes": len(blob),
            }
        # 形状回读：所有不确定性场与值网格共享同一物理坐标轴
        for name, keys in _PROFESSIONAL_NPZ_KEYS.items():
            if name not in payloads:
                continue
            with np.load(tmp_dir / name) as bundle:
                for key in keys:
                    if bundle[key].shape != tuple(shape):
                        raise PlatformError(
                            RESULT_ARTIFACT_INVALID,
                            "专业不确定性场形状与值网格不一致",
                            {"artifact": name, "key": key},
                        )
        for name in payloads:
            os.replace(tmp_dir / name, professional_dir / name)
            moved.append(professional_dir / name)

        # fold/OOF/诊断已在 run 期落盘：纳入 manifest 身份，不重复写
        artifact_entries: dict[str, dict[str, Any]] = {}
        for logical, evidence in (
            ("fold_assignments", assignments_path),
            ("out_of_fold_predictions", oof_path),
            ("prediction_diagnostics", diagnostics_path),
        ):
            artifact_entries[logical] = {
                "file": evidence.name,
                "sha256": _sha256(evidence),
                "bytes": evidence.stat().st_size,
            }
        artifact_entries["empirical_error_scale"] = entries["empirical_error_scale.npz"]
        if native_std_available:
            # IDW 的 native_kriging_std 为 not_applicable：manifest 以 capability
            # 明示“不适用”，绝不生成空文件占位
            artifact_entries["kriging_standard_deviation"] = entries[
                "kriging_standard_deviation.npz"
            ]
        artifact_entries["neighborhood_summary"] = entries["neighborhood_summary.json"]
        artifact_entries["metadata"] = entries["metadata.json"]
        manifest = {
            "version": 1,
            "candidate_result_id": result_id,
            "confirmation_id": professional.get("confirmation_id"),
            "fingerprint": candidate.fingerprint,
            "directory": str(professional_dir),
            "artifacts": artifact_entries,
            "capabilities": capabilities.model_dump(mode="json"),
            "config": {
                "neighborhood": professional.get("neighborhood"),
                "empirical_uncertainty": professional.get("empirical_uncertainty"),
            },
            "materialization": {
                "final_fit_origin": provenance["final"]["origin"],
                "transform_fingerprint": empirical.diagnostics.get("transform_fingerprint"),
                "grid": grid_identity,
                "empirical_error_scale": {
                    "coverage": empirical.diagnostics["coverage"],
                    "covered_queries": empirical.diagnostics["covered_queries"],
                    "total_queries": empirical.diagnostics["total_queries"],
                },
                "created_at": tables.utc_now_iso(),
            },
            "created_at": tables.utc_now_iso(),
        }
        _atomic_write_file(
            manifest_path, _json_bytes(manifest), error_code=PROFESSIONAL_ARTIFACT_WRITE_FAILED
        )
        moved.append(manifest_path)
        verify_manifest(manifest)
    except PlatformError:
        _cleanup_failed_write(tmp_dir, moved, professional_dir)
        raise
    except Exception as exc:
        _cleanup_failed_write(tmp_dir, moved, professional_dir)
        raise PlatformError(
            PROFESSIONAL_ARTIFACT_WRITE_FAILED, "专业工件写入失败", {"reason": str(exc)[:200]}
        ) from exc
    shutil.rmtree(tmp_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # 3. 结果级 grid/metadata 落盘（与 legacy 同一原子模式）
    # ------------------------------------------------------------------
    final_dir = grid_path.parent
    final_dir.mkdir(parents=True, exist_ok=True)
    grid_tmp_dir = Path(tempfile.mkdtemp(prefix="result-", dir=final_dir.parent))
    tmp_grid = grid_tmp_dir / "grid.npz"
    np.savez_compressed(
        tmp_grid, axes=np.array(grid.axes, dtype=object), values=grid_values, is_nodata=nodata
    )
    grid_sha = _sha256(tmp_grid)
    metadata = _result_metadata(
        result_id=result_id,
        run=run,
        experiment=experiment,
        dataset_version_id=dataset_version_id,
        params=params,
        candidate_params=candidate_params,
        dimension=dimension,
        grid=grid,
        grid_values=grid_values,
        nodata=nodata,
        grid_sha=grid_sha,
        profile=profile,
        fingerprint=candidate.fingerprint,
    )
    metadata["professional"] = {
        "confirmation_id": professional.get("confirmation_id"),
        "capabilities": capabilities.model_dump(mode="json"),
        "kriging_standard_deviation": {
            "available": bool(native_std_available),
            "capability": capabilities.native_kriging_std.value,
            **(
                {"sha256": entries["kriging_standard_deviation.npz"]["sha256"]}
                if native_std_available
                else {}
            ),
        },
        "empirical_error_scale": {
            "available": True,
            "capability": capabilities.empirical_error_scale.value,
            "coverage": empirical.diagnostics["coverage"],
            "covered_queries": empirical.diagnostics["covered_queries"],
            "total_queries": empirical.diagnostics["total_queries"],
            "sha256": entries["empirical_error_scale.npz"]["sha256"],
        },
        "parameter_provenance": provenance,
        "transform_fingerprint": empirical.diagnostics.get("transform_fingerprint"),
        "manifest_sha256": _sha256(manifest_path),
    }
    (grid_tmp_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with np.load(tmp_grid, allow_pickle=True) as probe:
        if probe["values"].shape != tuple(shape):
            raise PlatformError(RESULT_ARTIFACT_INVALID, "成果网格形状校验失败")
    os.replace(tmp_grid, grid_path)
    os.replace(grid_tmp_dir / "metadata.json", metadata_path)
    grid_tmp_dir.rmdir()

    # ------------------------------------------------------------------
    # 4. 全部替换成功后才更新数据库：候选 grid_path + 专业工件行 manifest
    # ------------------------------------------------------------------
    with runtime.session() as session:
        row = session.get(tables.CandidateResult, result_id)
        row.grid_path = str(grid_path)
        artifacts_row = (
            session.query(tables.ProfessionalResultArtifacts)
            .filter(tables.ProfessionalResultArtifacts.candidate_result_id == result_id)
            .one_or_none()
        )
        if artifacts_row is None:
            raise PlatformError(
                PROFESSIONAL_ARTIFACT_INCOMPLETE,
                "专业候选缺少工件行，物化结果无法登记",
                {"result_id": result_id},
                http_status=409,
            )
        artifacts_row.manifest_json = tables.dumps_canonical(manifest)
        session.commit()
    return metadata


def _verify_professional_materialization(
    runtime: PlatformRuntime, result_id: str, metadata: dict[str, Any]
) -> None:
    """幂等重读：验证既有专业工件（manifest 哈希 + 网格形状），同步工件行漂移。

    任何哈希/大小不匹配以 ``MANIFEST_VERIFICATION_FAILED`` fail-closed；
    不确定性场形状与值网格不一致以 ``RESULT_ARTIFACT_INVALID`` 失败。
    """

    from geomodeling.platform.professional import verify_manifest  # 延迟导入避免循环依赖

    manifest_path = runtime.settings.professional_result_manifest(result_id)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verify_manifest(manifest)
    shape = tuple(metadata["shape"])
    professional_dir = manifest_path.parent
    for name, keys in _PROFESSIONAL_NPZ_KEYS.items():
        path = professional_dir / name
        if not path.is_file():
            continue  # IDW 无 Kriging 标准差层；工件身份以 manifest 声明为准
        with np.load(path) as bundle:
            for key in keys:
                if bundle[key].shape != shape:
                    raise PlatformError(
                        RESULT_ARTIFACT_INVALID,
                        "专业不确定性场形状与值网格不一致",
                        {"artifact": name, "key": key},
                    )
    # 崩遗恢复：文件已暴露但工件行 manifest 未更新时，随验证通过同步
    with runtime.session() as session:
        artifacts_row = (
            session.query(tables.ProfessionalResultArtifacts)
            .filter(tables.ProfessionalResultArtifacts.candidate_result_id == result_id)
            .one_or_none()
        )
        if artifacts_row is not None and tables.loads_canonical(artifacts_row.manifest_json) != manifest:
            artifacts_row.manifest_json = tables.dumps_canonical(manifest)
            session.commit()


def read_materialized_metadata(runtime: PlatformRuntime, result_id: str) -> dict[str, Any]:
    """纯读取已物化成果的 metadata（v0.6.1 Task 7）。

    未物化 404 ``RESULT_NOT_MATERIALIZED``；绝不创建文件、绝不改写工件——
    ``POST /materialize`` 是唯一创建操作，GET 结果元数据只读既有落盘。
    """

    metadata_path = runtime.settings.result_grid(result_id).parent / "metadata.json"
    if not metadata_path.is_file():
        raise PlatformError(
            RESULT_NOT_MATERIALIZED,
            "成果尚未生成",
            {"result_id": result_id},
            http_status=404,
        )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    _, _, experiment = _load_candidate(runtime, result_id)
    if experiment.case_id == "resistivity" and metadata.get("property_name") == "RHO":
        metadata["units"] = "Ω·m"
    return metadata


def load_grid(runtime: PlatformRuntime, result_id: str) -> GridResult:
    grid_path = runtime.settings.result_grid(result_id)
    if not grid_path.exists():
        raise PlatformError(
            RESULT_NOT_MATERIALIZED,
            "成果尚未生成，请先调用 materialize",
            {"result_id": result_id},
            http_status=404,
        )
    metadata = json.loads((grid_path.parent / "metadata.json").read_text(encoding="utf-8"))
    with np.load(grid_path, allow_pickle=True) as bundle:
        axes = tuple(np.asarray(a, dtype=float) for a in bundle["axes"])
        values = bundle["values"]
        is_nodata = bundle["is_nodata"]
    return GridResult(
        dimension=metadata["dimension"],
        axes=axes,
        values=values,
        is_nodata=is_nodata,
        metadata=metadata,
    )


def _load_uncertainty_preview_layer(
    runtime: PlatformRuntime, result_id: str, layer: str, grid: GridResult
) -> tuple[np.ndarray, np.ndarray]:
    """读取已登记的专业不确定性层；能力不适用 409，未物化 404，绝不返回 0 场。"""

    metadata = grid.metadata
    algorithm = metadata.get("algorithm")
    if layer == "kriging_std" and (
        capabilities_for(algorithm).native_kriging_std is not CapabilityState.SUPPORTED
    ):
        raise PlatformError(
            PROFESSIONAL_CAPABILITY_NOT_APPLICABLE,
            "该算法不适用 Kriging 原生标准差层",
            {"algorithm": algorithm, "layer": layer},
            http_status=409,
        )
    filename, key = _LAYER_ARTIFACTS[layer]
    path = runtime.settings.professional_result_dir(result_id) / filename
    if not metadata.get("professional") or not path.is_file():
        raise PlatformError(
            PROFESSIONAL_LAYER_NOT_MATERIALIZED,
            "该成果未物化专业不确定性层",
            {"result_id": result_id, "layer": layer},
            http_status=404,
        )
    with np.load(path) as bundle:
        return bundle[key], bundle["is_nodata"]


def preview(runtime: PlatformRuntime, result_id: str, layer: str = "value") -> dict[str, Any]:
    """有界抽稀预览：``layer=value|empirical_error|kriging_std``。

    不确定性层只读已登记工件，与值预览同一抽稀上限（≤ 50,000 单元）与
    NoData 透明语义；算法不适用的层以 409 结构化拒绝，绝不返回 0 场。
    """

    if layer not in PREVIEW_LAYERS:
        raise PlatformError(
            PREVIEW_LAYER_UNKNOWN,
            "未知预览层",
            {"layer": layer, "allowed": list(PREVIEW_LAYERS)},
            http_status=400,
        )
    grid = load_grid(runtime, result_id)
    if layer == "value":
        values = grid.values
        nodata = grid.is_nodata
        value_range = list(grid.metadata["value_range"])
    else:
        values, nodata = _load_uncertainty_preview_layer(runtime, result_id, layer, grid)
        finite_layer = values[np.isfinite(values)]
        value_range = (
            [float(finite_layer.min()), float(finite_layer.max())]
            if finite_layer.size
            else [None, None]
        )
    shape = values.shape
    total = int(np.prod(shape))
    stride = max(1, int(np.ceil((total / PREVIEW_CELL_CAP) ** (1 / len(shape)))))
    index = tuple(range(0, axis_len, stride) for axis_len in shape)
    served_values = values[np.ix_(*index)]
    served_nodata = nodata[np.ix_(*index)]
    coords = np.stack(
        np.meshgrid(*[grid.axes[i][list(idx)] for i, idx in enumerate(index)], indexing="ij"),
        axis=-1,
    ).reshape(-1, len(shape))
    served = int(np.prod(served_values.shape))
    return {
        "result_id": result_id,
        "layer": layer,
        "dimension": grid.dimension,
        "original_cell_count": total,
        "served_cell_count": served,
        "stride": stride,
        "x": coords[:, 0].round(4).tolist(),
        "y": coords[:, 1].round(4).tolist(),
        "z": coords[:, 2].round(4).tolist() if grid.dimension == "3d" else None,
        "values": np.round(served_values.reshape(-1), 5).tolist(),
        "is_nodata": served_nodata.reshape(-1).tolist(),
        "value_range": value_range,
    }


def serve_slice(runtime: PlatformRuntime, result_id: str, axis: str, index: int) -> dict[str, Any]:
    # v0.7.0 第二批：与 RenderAsset 剖面服务共用同一抽取入口
    # （slice_analysis.extract_grid_plane）；响应字段/方向/取整与旧合同逐位一致
    grid = load_grid(runtime, result_id)
    result = extract_grid_plane(
        grid.axes,
        grid.values,
        grid.is_nodata,
        axis,
        index,
        dimension=grid.dimension,
    )
    return {
        "result_id": result_id,
        "fixed_axis": result.fixed_axis,
        "fixed_coordinate": result.fixed_coordinate,
        "axes_names": list(result.axes_names),
        "axes": [a.round(6).tolist() for a in result.axes],
        "matrix": np.round(result.matrix, 5).tolist(),
        "nodata_mask": result.nodata_mask.tolist(),
        "value_range": list(result.value_range),
    }
