"""Result materialization, preview, slices, formal selection, exports, publications."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from pathlib import Path

from geomodeling.api.deps import get_platform_runtime
from geomodeling.platform import PlatformRuntime, tables
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.exports import build_export
from geomodeling.platform.publications import request_publication
from geomodeling.platform.repositories import FormalSelectionRepository
from geomodeling.platform.results import materialize, preview, serve_slice
from geomodeling.platform.schemas import FormalSelectionBody, FormalSelectionRequest
from geomodeling.platform.supermap_volume import export_supermap_volume
from geomodeling.platform.supermap_voxel_netcdf import export_supermap_voxel_netcdf

router = APIRouter(tags=["v0.4-results"])


@router.post("/api/results/{result_id}/materialize")
def materialize_result(
    result_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    return materialize(runtime, result_id)


@router.get("/api/results/{result_id}")
def get_result(
    result_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    metadata = materialize(runtime, result_id)  # 幂等：已生成则直接读
    return metadata


@router.get("/api/results/{result_id}/preview")
def get_result_preview(
    result_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    materialize(runtime, result_id)
    return preview(runtime, result_id)


@router.get("/api/results/{result_id}/slices")
def get_result_slice(
    result_id: str,
    axis: str = Query(...),
    index: int = Query(..., ge=0),
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    materialize(runtime, result_id)
    return serve_slice(runtime, result_id, axis, index)


@router.post("/api/results/{result_id}/select-formal", status_code=201)
def select_formal(
    result_id: str,
    request: FormalSelectionBody,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    with runtime.session() as session:
        candidate = session.get(tables.CandidateResult, result_id)
        if candidate is None:
            raise PlatformError("CANDIDATE_NOT_FOUND", "成果不存在", {"result_id": result_id}, http_status=404)
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
        selection = FormalSelectionRepository(session).select(
            experiment.case_id,
            FormalSelectionRequest(
                candidate_result_id=result_id,
                note=request.note,
                selected_by=request.selected_by,
            ),
        )
    return selection.model_dump(mode="json")


@router.get("/api/cases/{case_id}/formal-selections")
def list_formal_selections(
    case_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    with runtime.session() as session:
        rows = (
            session.query(tables.FormalSelection)
            .filter(tables.FormalSelection.case_id == case_id)
            .order_by(tables.FormalSelection.created_at.asc())
            .all()
        )
    return {
        "case_id": case_id,
        "selections": [
            {
                "id": row.id,
                "candidate_result_id": row.candidate_result_id,
                "selected_by": row.selected_by,
                "note": row.note,
                "created_at": row.created_at,
            }
            for row in rows
        ],
    }


@router.post("/api/results/{result_id}/exports", status_code=201)
def create_export(
    result_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    return build_export(runtime, result_id)


@router.post("/api/results/{result_id}/supermap-volume-export", status_code=201)
def create_supermap_volume_export(
    result_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    """Create an idempotent iDesktopX DatasetVolume input package."""

    return export_supermap_volume(runtime, result_id)


@router.get("/api/results/{result_id}/supermap-volume-export")
def get_supermap_volume_export(
    result_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    return export_supermap_volume(runtime, result_id)


@router.get("/api/supermap-volume-exports/{export_id}/download")
def download_supermap_volume_export(
    export_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> FileResponse:
    if not export_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in export_id):
        raise PlatformError("VOLUME_EXPORT_INVALID", "体元导出 ID 无效", http_status=400)
    package_path = runtime.settings.supermap_volume_package(export_id)
    if not package_path.is_file():
        raise PlatformError("VOLUME_EXPORT_NOT_FOUND", "体元导出不存在", {"export_id": export_id}, http_status=404)
    return FileResponse(package_path, media_type="application/zip", filename="supermap-volume.zip")


@router.post("/api/results/{result_id}/supermap-voxel-netcdf-export", status_code=201)
def create_supermap_voxel_netcdf_export(
    result_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    """v0.6.1 POC：确定性 NetCDF classic/v3 导出（VoxelGridLayer3D 直读）。"""

    return export_supermap_voxel_netcdf(runtime, result_id)


@router.get("/api/results/{result_id}/supermap-voxel-netcdf-export")
def get_supermap_voxel_netcdf_export(
    result_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    return export_supermap_voxel_netcdf(runtime, result_id)


_VOXEL_NC_SAFE_EXPORT_ID = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


def _voxel_netcdf_export_file(runtime: PlatformRuntime, export_id: str, filename: str) -> Path:
    if not export_id or any(char not in _VOXEL_NC_SAFE_EXPORT_ID for char in export_id):
        raise PlatformError("VOXEL_NC_RESULT_INVALID", "NetCDF 导出 ID 无效", http_status=400)
    file_path = runtime.settings.supermap_voxel_netcdf_export_dir(export_id) / filename
    if not file_path.is_file():
        raise PlatformError("VOXEL_NC_NOT_FOUND", "NetCDF 导出不存在", {"export_id": export_id}, http_status=404)
    return file_path


@router.get("/api/supermap-voxel-netcdf-exports/{export_id}/manifest")
def get_supermap_voxel_netcdf_manifest(
    export_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> FileResponse:
    file_path = _voxel_netcdf_export_file(runtime, export_id, "manifest.json")
    return FileResponse(file_path, media_type="application/json; charset=utf-8", filename="manifest.json")


@router.get("/api/supermap-voxel-netcdf-exports/{export_id}/volume.nc")
def download_supermap_voxel_netcdf(
    export_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> FileResponse:
    file_path = _voxel_netcdf_export_file(runtime, export_id, "volume.nc")
    return FileResponse(file_path, media_type="application/x-netcdf", filename="volume.nc")


@router.get("/api/exports/{export_id}/download")
def download_export(
    export_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> FileResponse:
    with runtime.session() as session:
        row = session.get(tables.Export, export_id)
        if row is None:
            raise PlatformError("EXPORT_NOT_FOUND", "导出不存在", {"export_id": export_id}, http_status=404)
    return FileResponse(
        row.package_path,
        media_type="application/zip",
        filename="result-package.zip",
    )


@router.post("/api/results/{result_id}/publications", status_code=201)
def create_publication(
    result_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    return request_publication(runtime, result_id)
