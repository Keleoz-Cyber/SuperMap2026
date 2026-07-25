"""固定演示数据下载路由（不暴露本机路径，fail-closed）。"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse

from geomodeling.demo_assets import get_demo_dataset

router = APIRouter(prefix="/api/demo", tags=["demo"])


@router.get("/datasets/platform-demo-3d")
def download_platform_demo_3d() -> FileResponse:
    asset = get_demo_dataset()
    return FileResponse(
        asset.path,
        media_type="text/csv; charset=utf-8",
        filename="platform_demo_3d.csv",
    )
