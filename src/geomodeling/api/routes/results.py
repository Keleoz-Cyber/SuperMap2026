"""Result materialization, preview, slices, formal selection, exports, publications.

v0.6.1（Task 7）：``GET /api/results/{id}``、``/preview``、``/slices`` 是纯
查询——只读已物化工件，未物化 404 ``RESULT_NOT_MATERIALIZED``；
``POST /materialize`` 是唯一创建操作。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from geomodeling.api.deps import get_platform_runtime
from geomodeling.platform import PlatformRuntime, tables
from geomodeling.platform.errors import PlatformError, READ_ONLY_CASE_FORMAL_SELECTION
from geomodeling.platform.exports import build_export
from geomodeling.platform.publications import request_publication
from geomodeling.platform.repositories import (
    FormalSelectionRepository,
    require_active_candidate,
    require_active_case,
    require_active_export,
)
from geomodeling.platform.results import (
    materialize,
    preview,
    read_materialized_metadata,
    serve_slice,
)
from geomodeling.platform.schemas import FormalSelectionBody, FormalSelectionRequest

router = APIRouter(tags=["v0.4-results"])


@router.post("/api/results/{result_id}/materialize")
def materialize_result(
    result_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    require_active_candidate(runtime, result_id)
    return materialize(runtime, result_id)


@router.get("/api/results/{result_id}")
def get_result(
    result_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    require_active_candidate(runtime, result_id)
    # 纯查询：只读已物化 metadata；未物化 404，绝不隐式物化
    return read_materialized_metadata(runtime, result_id)


@router.get("/api/results/{result_id}/preview")
def get_result_preview(
    result_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    require_active_candidate(runtime, result_id)
    return preview(runtime, result_id)


@router.get("/api/results/{result_id}/slices")
def get_result_slice(
    result_id: str,
    axis: str = Query(...),
    index: int = Query(..., ge=0),
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    require_active_candidate(runtime, result_id)
    return serve_slice(runtime, result_id, axis, index)


def _case_is_read_only(session, case_id: str) -> bool:
    """read_only 官方案例判定（持久化配置；缺行按非只读处理，不改变既有语义）。"""

    case_row = session.get(tables.Case, case_id)
    if case_row is None:
        return False
    return tables.loads_canonical(case_row.config_json).get("read_only") is True


@router.post("/api/results/{result_id}/select-formal", status_code=201)
def select_formal(
    result_id: str,
    request: FormalSelectionBody,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    require_active_candidate(runtime, result_id)
    with runtime.session() as session:
        candidate = session.get(tables.CandidateResult, result_id)
        if candidate is None:
            raise PlatformError(
                "CANDIDATE_NOT_FOUND",
                "成果不存在",
                {"result_id": result_id},
                http_status=404,
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
        # v0.7.0 审查修复（Blocker）：read_only 案例（如 builtin_preset 官方
        # 案例）禁止产品面新增正式选择——官方成果只能由内部 seed 登记，
        # 用户实验不得顶替。只读判定来自持久化 Case 配置，不依赖用户输入。
        case_row = session.get(tables.Case, experiment.case_id)
        case_config = (
            tables.loads_canonical(case_row.config_json) if case_row is not None else {}
        )
        if case_config.get("read_only") is True:
            raise PlatformError(
                READ_ONLY_CASE_FORMAL_SELECTION,
                "官方案例为只读：正式成果已由官方登记，不能另行选择",
                {"case_id": experiment.case_id},
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
    require_active_case(runtime, case_id)
    with runtime.session() as session:
        rows = (
            session.query(tables.FormalSelection)
            .filter(tables.FormalSelection.case_id == case_id)
            .order_by(tables.FormalSelection.created_at.asc())
            .all()
        )
    return {
        "case_id": case_id,
        # v0.7.0 审查修复：产品面是否允许新增正式选择（read_only 官方案例禁止）；
        # 前端据此隐藏选择控件，API 写路径仍独立强制同一判定
        "selection_allowed": not _case_is_read_only(session, case_id),
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
    require_active_candidate(runtime, result_id)
    return build_export(runtime, result_id)


@router.get("/api/exports/{export_id}/download")
def download_export(
    export_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> FileResponse:
    require_active_export(runtime, export_id)
    with runtime.session() as session:
        row = session.get(tables.Export, export_id)
        if row is None:
            raise PlatformError(
                "EXPORT_NOT_FOUND",
                "导出不存在",
                {"export_id": export_id},
                http_status=404,
            )
    # v0.7.0 第二批：剖面分析包与成果证据包按 export_kind 区分下载文件名
    manifest = tables.loads_canonical(row.manifest_json) if row.manifest_json else {}
    filename = (
        "slice-analysis.zip"
        if manifest.get("export_kind") == "slice_analysis"
        else "result-package.zip"
    )
    return FileResponse(
        row.package_path,
        media_type="application/zip",
        filename=filename,
    )


@router.post("/api/results/{result_id}/publications", status_code=201)
def create_publication(
    result_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    require_active_candidate(runtime, result_id)
    return request_publication(runtime, result_id)
