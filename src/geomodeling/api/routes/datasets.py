"""Dataset inspection, field-mapping, and quality routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, Query

from geomodeling.api.deps import get_platform_runtime
from geomodeling.platform import PlatformRuntime, ingest, quality as quality_mod, tables
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.repositories import DatasetRepository
from geomodeling.platform.schemas import DatasetStatus, FieldMapping

router = APIRouter(prefix="/api/datasets", tags=["v0.4-datasets"])

QUALITY_NOT_EVALUATED = "QUALITY_NOT_EVALUATED"
WARNING_CONFIRMATION_MISMATCH = "WARNING_CONFIRMATION_MISMATCH"
DATASET_NOT_MAPPED = "DATASET_NOT_MAPPED"


@router.get("/{dataset_id}")
def get_dataset(
    dataset_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    with runtime.session() as session:
        record = DatasetRepository(session).get(dataset_id)
    return record.model_dump(mode="json")


@router.get("/{dataset_id}/points")
def dataset_points(
    dataset_id: str,
    decimate: int = Query(default=1, ge=1, le=100),
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    """标准化点数据（实测点叠加层用）；只读，始终来自标准化工件。"""

    record, profile = _load_quality_context(runtime, dataset_id)
    standardized = record.standardized_path or profile.get("standardized_path")
    if record.status == DatasetStatus.UPLOADED or not standardized:
        raise PlatformError(
            DATASET_NOT_MAPPED,
            "数据集尚未完成字段映射，没有标准化点数据",
            {"dataset_id": dataset_id, "status": record.status},
            http_status=409,
        )
    frame = pd.read_parquet(Path(standardized))
    valid = frame.loc[frame["is_numeric_valid"]].reset_index(drop=True)
    dimension = "3d" if profile.get("dimension") == "3d" else "2d"
    step = max(1, int(decimate))
    sliced = valid.iloc[::step]
    return {
        "dataset_id": dataset_id,
        "dimension": dimension,
        "count": len(valid),
        "served": len(sliced),
        "decimate": step,
        "x": sliced["x"].round(6).tolist(),
        "y": sliced["y"].round(6).tolist(),
        "z": sliced["z"].round(6).tolist() if dimension == "3d" else None,
        "values": sliced["value"].round(6).tolist(),
        "value_range": [float(valid["value"].min()), float(valid["value"].max())] if len(valid) else None,
        "value_name": (profile.get("mapping") or {}).get("value_name"),
        "source_sha256": profile.get("source_sha256"),
    }


@router.get("/{dataset_id}/inspection")
def inspect_dataset(
    dataset_id: str,
    sheet: str | None = Query(default=None),
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    settings = runtime.settings
    with runtime.session() as session:
        record = DatasetRepository(session).get(dataset_id)
    profile = dict(record.profile)
    result = ingest.inspect_source(
        settings, Path(record.source_path), profile.get("suffix", ""), sheet
    )
    result["dataset_id"] = dataset_id
    result["case_id"] = record.case_id
    result["profile"] = profile
    return result


@router.post("/{dataset_id}/mapping")
def map_dataset(
    dataset_id: str,
    mapping: FieldMapping,
    sheet: str | None = Query(default=None),
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    settings = runtime.settings
    with runtime.session() as session:
        repo = DatasetRepository(session)
        record = repo.get(dataset_id)
        profile = dict(record.profile)
        summary = ingest.standardize(
            settings,
            record.case_id,
            record.id,
            Path(record.source_path),
            profile.get("suffix", ""),
            mapping,
            sheet,
        )
        # 重新映射使既有质量报告与警告确认全部失效
        profile.pop("quality", None)
        if record.status == DatasetStatus.UPLOADED:
            mapped = repo.transition_status(dataset_id, DatasetStatus.MAPPED)
        elif record.status == DatasetStatus.BLOCKED:
            mapped = repo.transition_status(dataset_id, DatasetStatus.MAPPED)
        else:
            mapped = record

        profile.update(
            {
                "dimension": mapping.dimension,
                "mapping": mapping.model_dump(mode="json"),
                "sheet": summary["sheet"],
                "row_count": summary["row_count"],
                "valid_row_count": summary["valid_row_count"],
                "invalid_row_count": summary["invalid_row_count"],
                "standardized_path": summary["standardized_path"],
                "standardized_sha256": summary["standardized_sha256"],
            }
        )
        row = session.get(tables.DatasetVersion, dataset_id)
        row.standardized_path = summary["standardized_path"]
        row.profile_json = tables.dumps_canonical(profile)
        session.commit()

    result = mapped.model_dump(mode="json")
    result["profile"] = profile
    return result


def _load_quality_context(runtime: PlatformRuntime, dataset_id: str):
    with runtime.session() as session:
        record = DatasetRepository(session).get(dataset_id)
    profile = dict(record.profile)
    return record, profile


@router.post("/{dataset_id}/validate")
def validate_dataset(
    dataset_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    record, profile = _load_quality_context(runtime, dataset_id)
    if record.status not in (DatasetStatus.MAPPED, DatasetStatus.BLOCKED, DatasetStatus.VALIDATED):
        raise PlatformError(
            DATASET_NOT_MAPPED,
            "数据集尚未完成字段映射，不能执行质量校验",
            {"dataset_id": dataset_id, "status": record.status},
            http_status=409,
        )
    mapping = FieldMapping.model_validate(profile.get("mapping"))
    frame = pd.read_parquet(Path(profile["standardized_path"]))
    report = quality_mod.evaluate_quality(
        frame=frame,
        mapping=mapping,
        source_sha256=profile.get("source_sha256", ""),
        standardized_sha256=profile.get("standardized_sha256", ""),
    )
    profile["quality"] = report

    with runtime.session() as session:
        repo = DatasetRepository(session)
        if report["status"] == "blocked" and record.status != DatasetStatus.BLOCKED:
            repo.transition_status(dataset_id, DatasetStatus.BLOCKED)
        elif report["status"] != "blocked" and record.status == DatasetStatus.MAPPED:
            repo.transition_status(dataset_id, DatasetStatus.VALIDATED)
        row = session.get(tables.DatasetVersion, dataset_id)
        row.profile_json = tables.dumps_canonical(profile)
        session.commit()
    return report


@router.get("/{dataset_id}/quality")
def get_quality(
    dataset_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    _, profile = _load_quality_context(runtime, dataset_id)
    report = profile.get("quality")
    if report is None:
        raise PlatformError(
            QUALITY_NOT_EVALUATED,
            "尚未执行质量校验",
            {"dataset_id": dataset_id},
            http_status=404,
        )
    return report


@router.post("/{dataset_id}/quality/confirm-warnings")
def confirm_warnings(
    dataset_id: str,
    payload: dict[str, Any],
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    _, profile = _load_quality_context(runtime, dataset_id)
    report = profile.get("quality")
    if report is None:
        raise PlatformError(
            QUALITY_NOT_EVALUATED,
            "尚未执行质量校验",
            {"dataset_id": dataset_id},
            http_status=404,
        )
    offered = set(payload.get("issue_codes") or [])
    required = quality_mod.open_warning_codes(report)
    if offered != required:
        raise PlatformError(
            WARNING_CONFIRMATION_MISMATCH,
            "确认集合必须与当前未决警告代码完全一致",
            {"offered": sorted(offered), "required": sorted(required)},
            http_status=409,
        )
    report["confirmed"] = True
    report["confirmed_issue_codes"] = sorted(required)
    profile["quality"] = report
    with runtime.session() as session:
        row = session.get(tables.DatasetVersion, dataset_id)
        row.profile_json = tables.dumps_canonical(profile)
        session.commit()
    return report
