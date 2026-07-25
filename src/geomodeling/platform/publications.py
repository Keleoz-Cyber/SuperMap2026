"""Publication records: independent publish state for formal results.

A publication request never mutates modeling state. The current generic
adapter records the request and returns ``manual_required`` with the
export location and the manual instructions needed to publish through the
iServer admin UI — it never claims iServer publication success without
live metadata evidence.
"""

from __future__ import annotations

import uuid
from typing import Any

from geomodeling.platform import tables
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.exports import build_export

MANUAL_REQUIRED = "manual_required"


def request_publication(runtime: PlatformRuntime, result_id: str) -> dict[str, Any]:
    """Record a publication request for a result.

    iServer programmatic publishing from this machine is currently not
    supported (the workspaces REST quick-publish endpoint fails on the
    local build), so every request resolves to ``manual_required`` with
    the evidence and instructions a human needs.
    """

    with runtime.session() as session:
        candidate = session.get(tables.CandidateResult, result_id)
        if candidate is None:
            raise PlatformError("CANDIDATE_NOT_FOUND", "成果不存在", {"result_id": result_id}, http_status=404)
        run = session.get(tables.Run, candidate.run_id)
        experiment = session.get(tables.Experiment, run.experiment_id)
        existing_export = (
            session.query(tables.Export)
            .filter(tables.Export.case_id == experiment.case_id)
            .order_by(tables.Export.created_at.desc())
            .first()
        )

    if existing_export is None:
        export = build_export(runtime, result_id)
        export_id = export["id"]
    else:
        export_id = existing_export.id

    publication_id = str(uuid.uuid4())
    detail = {
        "export_id": export_id,
        # 公开证据只给资源 ID 与下载 URL，绝不回传服务器文件路径
        "download_url": f"/api/exports/{export_id}/download",
        "manual_instruction": (
            "本机 iServer 程序化发布不可用（workspaces REST 发布接口 500）。"
            "请通过 iServer 管理界面手动发布导出的成果包："
            "服务管理 → 快速创建服务 → 选择数据源，完成后回到平台登记服务 URL。"
        ),
        "iserver_rest_publish_status": "unsupported_on_this_build",
    }
    with runtime.session() as session:
        session.add(
            tables.Publication(
                id=publication_id,
                export_id=export_id,
                target="iserver",
                status=MANUAL_REQUIRED,
                detail_json=tables.dumps_canonical(detail),
            )
        )
        session.commit()
    return {
        "id": publication_id,
        "export_id": export_id,
        "status": MANUAL_REQUIRED,
        "evidence": detail,
    }
