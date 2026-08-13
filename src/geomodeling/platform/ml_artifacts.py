"""Atomic auxiliary grid fields for machine-learning results."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from geomodeling.platform.errors import PlatformError

ML_ARTIFACT_INVALID = "ML_ARTIFACT_INVALID"

_ALLOWED_FIELDS = {
    "random_forest_spatial": ("model_dispersion",),
    "kriging_rf_residual": (
        "model_dispersion",
        "kriging_baseline",
        "residual_correction",
    ),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _invalid(message: str, details: dict[str, Any] | None = None) -> PlatformError:
    return PlatformError(ML_ARTIFACT_INVALID, message, details or {}, http_status=409)


def write_ml_fields(
    directory: Path,
    *,
    algorithm: str,
    axes: tuple[np.ndarray, ...],
    fields: dict[str, np.ndarray],
    nodata: dict[str, np.ndarray] | None = None,
    main_grid_sha256: str,
    property_unit: str | None,
) -> dict[str, Any]:
    directory = Path(directory)
    expected = _ALLOWED_FIELDS.get(algorithm)
    if expected is None or tuple(fields) != expected:
        raise _invalid(
            "机器学习辅助场集合与算法不一致",
            {"algorithm": algorithm, "fields": list(fields)},
        )
    normalized_axes = tuple(np.asarray(axis, dtype="float64") for axis in axes)
    shape = tuple(len(axis) for axis in normalized_axes)
    payload: dict[str, np.ndarray] = {"axes": np.array(normalized_axes, dtype=object)}
    field_manifest: dict[str, dict[str, Any]] = {}
    for name, raw in fields.items():
        values = np.asarray(raw, dtype="float64")
        if values.shape != shape:
            raise _invalid(
                "机器学习辅助场形状与主网格不一致",
                {"field": name, "shape": list(values.shape), "expected": list(shape)},
            )
        field_nodata = (
            np.asarray(nodata[name], dtype=bool)
            if nodata is not None and name in nodata
            else np.zeros(shape, dtype=bool)
        )
        if field_nodata.shape != shape:
            raise _invalid("机器学习辅助场 NoData 形状不一致", {"field": name})
        if not np.isfinite(values[~field_nodata]).all():
            raise _invalid("机器学习辅助场包含未声明的非有限值", {"field": name})
        values = np.where(field_nodata, np.nan, values)
        payload[f"{name}__values"] = values
        payload[f"{name}__is_nodata"] = field_nodata
        field_hash = hashlib.sha256(
            values.tobytes(order="C") + field_nodata.tobytes(order="C")
        ).hexdigest()
        finite = values[np.isfinite(values)]
        field_manifest[name] = {
            "sha256": field_hash,
            "shape": list(shape),
            "value_range": [float(finite.min()), float(finite.max())],
            "nodata_count": int(field_nodata.sum()),
            "unit": property_unit,
            "palette_intent": (
                "diverging_zero_centered"
                if name == "residual_correction"
                else "sequential_nonnegative"
                if name == "model_dispersion"
                else "property_default"
            ),
        }

    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_npz_name = tempfile.mkstemp(prefix="ml-fields-", suffix=".npz", dir=directory)
    os.close(fd)
    tmp_npz = Path(tmp_npz_name)
    tmp_json = tmp_npz.with_suffix(".json")
    final_npz = directory / "ml_fields.npz"
    final_json = directory / "ml_fields.json"
    try:
        np.savez_compressed(tmp_npz, **payload)
        package_sha = _sha256(tmp_npz)
        manifest = {
            "version": 1,
            "algorithm": algorithm,
            "main_grid_sha256": main_grid_sha256,
            "shape": list(shape),
            "package_sha256": package_sha,
            "fields": field_manifest,
        }
        tmp_json.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        with np.load(tmp_npz, allow_pickle=True) as probe:
            if tuple(len(axis) for axis in probe["axes"]) != shape:
                raise _invalid("机器学习辅助场坐标轴回读失败")
        os.replace(tmp_npz, final_npz)
        os.replace(tmp_json, final_json)
        return manifest
    except BaseException:
        tmp_npz.unlink(missing_ok=True)
        tmp_json.unlink(missing_ok=True)
        raise


def read_ml_fields_manifest(
    directory: Path, *, expected_grid_sha256: str | None = None
) -> dict[str, Any]:
    directory = Path(directory)
    manifest_path = directory / "ml_fields.json"
    package_path = directory / "ml_fields.npz"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("version") != 1:
            raise ValueError("unsupported version")
        if expected_grid_sha256 is not None and manifest.get("main_grid_sha256") != expected_grid_sha256:
            raise ValueError("main grid identity mismatch")
        if _sha256(package_path) != manifest.get("package_sha256"):
            raise ValueError("package hash mismatch")
        with np.load(package_path, allow_pickle=True) as bundle:
            shape = tuple(int(value) for value in manifest["shape"])
            if tuple(len(axis) for axis in bundle["axes"]) != shape:
                raise ValueError("axis shape mismatch")
            for name, details in manifest["fields"].items():
                values = np.asarray(bundle[f"{name}__values"], dtype="float64")
                nodata = np.asarray(bundle[f"{name}__is_nodata"], dtype=bool)
                if values.shape != shape or nodata.shape != shape:
                    raise ValueError("field shape mismatch")
                digest = hashlib.sha256(
                    values.tobytes(order="C") + nodata.tobytes(order="C")
                ).hexdigest()
                if digest != details["sha256"]:
                    raise ValueError("field hash mismatch")
        return manifest
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise _invalid("机器学习辅助场工件损坏或身份不一致") from exc


def load_ml_field(
    directory: Path,
    field: str,
    *,
    expected_grid_sha256: str | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    manifest = read_ml_fields_manifest(
        directory, expected_grid_sha256=expected_grid_sha256
    )
    if field not in manifest["fields"]:
        raise _invalid("请求的机器学习辅助场不存在", {"field": field})
    with np.load(Path(directory) / "ml_fields.npz", allow_pickle=True) as bundle:
        return (
            np.asarray(bundle[f"{field}__values"], dtype="float64"),
            np.asarray(bundle[f"{field}__is_nodata"], dtype=bool),
        )
