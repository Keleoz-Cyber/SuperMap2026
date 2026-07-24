"""Result materialization, preview, and slice serving.

A succeeded candidate is materialized once: the interpolator is refit on
all validated rows and evaluated on the persisted rule grid, written as
``grid.npz`` plus ``metadata.json`` through an atomic directory replace.
Previews are deterministically decimated at 50,000 cells; slices always
read the persisted artifact — they never rerun interpolation.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from geomodeling.modeling.contracts import GridDefinition
from geomodeling.modeling.grid import derive_grid
from geomodeling.modeling.idw import IDWInterpolator
from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator
from geomodeling.modeling.slices import GridResult, extract_slice
from geomodeling.platform import tables
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.schemas import Algorithm, GridSpec
from geomodeling.platform.settings import PlatformSettings

RESULT_NOT_MATERIALIZED = "RESULT_NOT_MATERIALIZED"
CANDIDATE_NOT_SUCCEEDED = "CANDIDATE_NOT_SUCCEEDED"
PREVIEW_CELL_CAP = 50_000
DEFAULT_AXIS_NODES = 11

_INTERPOLATORS = {
    Algorithm.IDW.value: IDWInterpolator(),
    Algorithm.ORDINARY_KRIGING.value: OrdinaryKrigingInterpolator(),
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
    with runtime.session() as session:
        candidate = session.get(tables.CandidateResult, result_id)
        if candidate is None:
            raise PlatformError(
                "CANDIDATE_NOT_FOUND", "成果不存在", {"result_id": result_id}, http_status=404
            )
        run = session.get(tables.Run, candidate.run_id)
        experiment = session.get(tables.Experiment, run.experiment_id)
        return candidate, run, experiment


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
    grid_path = runtime.settings.result_grid(result_id)
    metadata_path = grid_path.parent / "metadata.json"
    if grid_path.exists() and metadata_path.exists():
        return json.loads(metadata_path.read_text(encoding="utf-8"))

    params = tables.loads_canonical(experiment.params_json)
    dataset = None
    with runtime.session() as session:
        dataset = session.get(tables.DatasetVersion, params["dataset_version_id"])
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
    fitted = interpolator.fit(points, values, validated)

    grid_spec = GridSpec.model_validate(params["grid"]) if params.get("grid") else None
    grid = _grid_spec_from_data(valid, dimension, grid_spec)
    query = np.stack(np.meshgrid(*grid.axes, indexing="ij"), axis=-1).reshape(-1, len(grid.axes))
    batch = fitted.predict(query, cancel=lambda: False)
    shape = grid.shape
    grid_values = batch.values.reshape(shape)
    nodata = batch.is_nodata.reshape(shape)

    # 原子落盘：临时目录写齐 → 校验 → 目录替换
    final_dir = grid_path.parent
    final_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="result-", dir=final_dir.parent))
    tmp_grid = tmp_dir / "grid.npz"
    np.savez_compressed(tmp_grid, axes=np.array(grid.axes, dtype=object), values=grid_values, is_nodata=nodata)
    grid_sha = _sha256(tmp_grid)
    finite = grid_values[np.isfinite(grid_values)]
    metadata = {
        "result_id": result_id,
        "run_id": run.id,
        "experiment_id": experiment.id,
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
        "fingerprint": candidate.fingerprint,
        "validation": params.get("validation"),
        "created_at": tables.utc_now_iso(),
    }
    (tmp_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    with np.load(tmp_grid, allow_pickle=True) as probe:
        if probe["values"].shape != tuple(shape):
            raise PlatformError("RESULT_ARTIFACT_INVALID", "成果网格形状校验失败")
    os.replace(tmp_grid, grid_path)
    os.replace(tmp_dir / "metadata.json", metadata_path)
    tmp_dir.rmdir()

    with runtime.session() as session:
        row = session.get(tables.CandidateResult, result_id)
        row.grid_path = str(grid_path)
        session.commit()
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


def preview(runtime: PlatformRuntime, result_id: str) -> dict[str, Any]:
    grid = load_grid(runtime, result_id)
    shape = grid.values.shape
    total = int(np.prod(shape))
    stride = max(1, int(np.ceil((total / PREVIEW_CELL_CAP) ** (1 / len(shape)))))
    index = tuple(range(0, axis_len, stride) for axis_len in shape)
    values = grid.values[np.ix_(*index)]
    nodata = grid.is_nodata[np.ix_(*index)]
    coords = np.stack(
        np.meshgrid(*[grid.axes[i][list(idx)] for i, idx in enumerate(index)], indexing="ij"),
        axis=-1,
    ).reshape(-1, len(shape))
    served = int(np.prod(values.shape))
    return {
        "result_id": result_id,
        "dimension": grid.dimension,
        "original_cell_count": total,
        "served_cell_count": served,
        "stride": stride,
        "x": coords[:, 0].round(4).tolist(),
        "y": coords[:, 1].round(4).tolist(),
        "z": coords[:, 2].round(4).tolist() if grid.dimension == "3d" else None,
        "values": np.round(values.reshape(-1), 5).tolist(),
        "is_nodata": nodata.reshape(-1).tolist(),
        "value_range": list(grid.metadata["value_range"]),
    }


def serve_slice(runtime: PlatformRuntime, result_id: str, axis: str, index: int) -> dict[str, Any]:
    grid = load_grid(runtime, result_id)
    result = extract_slice(grid, axis=axis, index=index)  # type: ignore[arg-type]
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
