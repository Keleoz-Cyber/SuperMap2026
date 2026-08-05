"""FastAPI application: v0.4 generic platform + v0.3.1 resistivity adapter.

Run locally:

    uvicorn geomodeling.api.app:app --host 127.0.0.1 --port 8000

The browser talks only to this API; iServer admin credentials stay on the
server side (environment variables), and iServer outages degrade to a
recoverable "publish failed / unavailable" state without touching modeling
evidence.

Integration contract (Task 10):

- one ``PlatformRuntime`` and one ``JobWorker`` are owned by the lifespan;
- legacy exact routes (``/api/cases/resistivity*``) are registered *before*
  the v0.4 routers so the dynamic ``/api/cases/{case_id}`` can never
  swallow them;
- ``GET /api/cases`` merges the immutable legacy cards with persisted
  upload cases (the legacy adapter never writes to SQLite);
- the v0.6 ``professional`` router (Task 17) is registered after the
  microseismic router and before the frontend static mount — its exact
  prefixes never shadow legacy or microseismic routes;
- the v0.6.1 ``rendering`` router (Task 7) is registered after the result
  routes and before the frontend static mount — capability/status/manifest/
  NetCDF GETs are pure queries, POSTs are the only explicit mutations;
- all route errors share the v0.4 envelope
  ``{"error": {"code", "message", "details"}}`` and never leak local paths.
"""

from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from geomodeling.api import case_service
from geomodeling.api.deps import (
    PROJECT_VERSION,
    ApiSettings,
    get_app_config,
    get_iserver_client,
    get_settings,
)
from geomodeling.api.routes import (
    cases,
    datasets,
    demo,
    experiments,
    professional,
    rendering,
    results,
    runs,
)
from geomodeling.platform import PlatformRuntime
from geomodeling.platform.errors import (
    CASE_NOT_FOUND,
    PRESET_NOT_INITIALIZED,
    REDACTED_PATH,
    PlatformError,
    platform_error_handler,
)
from geomodeling.platform.legacy_adapter import (
    legacy_case_cards,
    merged_case_cards,
    workspace_case_card,
)
from geomodeling.platform.microseismic_preset import PRESET_CASE_ID, PRESET_VERSION
from geomodeling.platform.public_dto import public_dataset
from geomodeling.platform.repositories import (
    CaseRepository,
    DatasetRepository,
    featured_result_for_case,
)
from geomodeling.platform.worker import JobWorker
from geomodeling.publishing import (
    IServerClient,
    BrowserLoadReport,
    S3MBContractError,
    probe_iserver,
    record_browser_load,
)

# 公开错误文本中的本机路径占位替换（盘符/UNC/用户目录），URL 不受影响。
_LOCAL_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\|~[\\/])[^\s'\"]*")


def _envelope(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message, "details": {}}}


async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Convert legacy HTTPException details into the v0.4 error envelope."""

    detail = exc.detail
    if not isinstance(detail, str):
        detail = json.dumps(detail, ensure_ascii=False, default=str)
    message = _LOCAL_PATH_RE.sub(REDACTED_PATH, detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(f"HTTP_{exc.status_code}", message),
        headers=getattr(exc, "headers", None),
    )


@asynccontextmanager
async def platform_lifespan(app: FastAPI):
    """Own the v0.4 runtime and worker; shutdown stops work and closes DB."""

    runtime = PlatformRuntime()
    runtime.initialize()
    runtime.recover_interrupted_runs()
    worker = JobWorker(runtime)
    app.state.platform_runtime = runtime
    app.state.job_worker = worker
    try:
        yield
    finally:
        worker.shutdown(wait=True)
        runtime.close()


def _latest_validated_public_dataset(dataset_repo, case_id: str) -> dict | None:
    """案例最新已验证数据版本的白名单公开 DTO；没有则 None。"""

    versions = dataset_repo.list_for_case(case_id)
    validated = [record for record in versions if record.status == "validated"]
    if not validated:
        return None
    return public_dataset(validated[-1])


def create_app() -> FastAPI:
    app = FastAPI(title="GeoModelingPlatform API", version=PROJECT_VERSION, lifespan=platform_lifespan)

    app.add_exception_handler(PlatformError, platform_error_handler)
    app.add_exception_handler(HTTPException, http_error_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------- health
    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "version": PROJECT_VERSION,
            "time": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------ iServer
    @app.get("/api/iserver/status")
    def iserver_status(client: IServerClient = Depends(get_iserver_client)) -> dict:
        try:
            return probe_iserver(client).model_dump(mode="json")
        finally:
            client.close()

    # -------------------------------------------------------------- cases
    @app.get("/api/cases")
    def case_cards(request: Request) -> dict:
        # 运行时缺失（如未进入 lifespan 的纯 legacy 测试）时只回 legacy 卡片
        runtime = getattr(request.app.state, "platform_runtime", None)
        records = []
        featured = {}
        primary_datasets = {}
        if runtime is not None:
            with runtime.session() as session:
                records = CaseRepository(session).list_all()
                dataset_repo = DatasetRepository(session)
                # v0.6.1：每张上传卡少量查询给出主打成果直达链接（正式选择优先）
                featured = {
                    record.id: featured_result_for_case(session, record.id)
                    for record in records
                }
                # v0.7.0：最新已验证数据版本作为工作台 primary_dataset（白名单 DTO）
                primary_datasets = {
                    record.id: _latest_validated_public_dataset(dataset_repo, record.id)
                    for record in records
                }
        return {"cases": merged_case_cards(records, featured, primary_datasets)}

    @app.get("/api/cases/{case_id}/workspace")
    def case_workspace(case_id: str, request: Request) -> dict:
        """统一案例工作台 DTO（legacy/预置/上传同一公共形态）。

        未 seed 的预置案例返回类型化 ``PRESET_NOT_INITIALIZED``（409）；
        未知案例 404；响应只含相对链接与脱敏元数据。
        """

        for card in legacy_case_cards():
            if card["case_id"] == case_id:
                return card

        runtime = getattr(request.app.state, "platform_runtime", None)
        record = None
        if runtime is not None:
            with runtime.session() as session:
                try:
                    record = CaseRepository(session).get(case_id)
                except PlatformError as exc:
                    if exc.code != CASE_NOT_FOUND:
                        raise
                if record is not None:
                    featured = featured_result_for_case(session, record.id)
                    primary = _latest_validated_public_dataset(
                        DatasetRepository(session), record.id
                    )
                    return workspace_case_card(
                        record, featured_result=featured, primary_dataset=primary
                    )
        if case_id == PRESET_CASE_ID:
            raise PlatformError(
                PRESET_NOT_INITIALIZED,
                "微震预置案例尚未初始化：需由维护者执行文档化 seed 命令",
                {"preset_version": PRESET_VERSION},
                http_status=409,
            )
        raise PlatformError(CASE_NOT_FOUND, "案例不存在", {"case_id": case_id}, http_status=404)


    @app.get("/api/cases/resistivity")
    def resistivity(
        settings: ApiSettings = Depends(get_settings),
        config=Depends(get_app_config),
    ) -> dict:
        return case_service.resistivity_detail(config, settings.metrics_json)

    @app.get("/api/cases/resistivity/publish-status")
    def resistivity_publish_status(
        settings: ApiSettings = Depends(get_settings),
        config=Depends(get_app_config),
        client: IServerClient = Depends(get_iserver_client),
    ) -> dict:
        try:
            return case_service.publish_status(config, client, settings.evidence_dir)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        finally:
            client.close()

    @app.get("/api/cases/resistivity/points")
    def resistivity_points(
        decimate: int = Query(default=1, ge=1, le=100),
        config=Depends(get_app_config),
    ) -> dict:
        try:
            return case_service.resistivity_points(config, decimate=decimate)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/cases/resistivity/voxel-cells")
    def resistivity_voxel_cells(
        refresh: bool = Query(default=False),
        settings: ApiSettings = Depends(get_settings),
        config=Depends(get_app_config),
        client: IServerClient = Depends(get_iserver_client),
    ) -> dict:
        try:
            return case_service.voxel_cells(config, client, settings.voxel_cache_dir, refresh=refresh)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=f"voxel cache not generated: {exc}") from exc
        except S3MBContractError as exc:
            raise HTTPException(status_code=503, detail=f"S3M 缓存契约校验失败：{exc}") from exc
        except ConnectionError as exc:
            raise HTTPException(status_code=503, detail=f"iServer tile fetch failed: {exc}") from exc
        finally:
            client.close()

    # ----------------------------------------------------------- evidence
    @app.post("/api/evidence/browser-load", status_code=201)
    def browser_load(
        report: BrowserLoadReport,
        settings: ApiSettings = Depends(get_settings),
    ) -> dict:
        record = record_browser_load(report, settings.evidence_dir)
        return {"recorded": True, "record": record.model_dump(mode="json")}

    # ----------------------------------------------------- v0.4 platform
    # 必须在 legacy 精确路由之后注册，/api/cases/resistivity 才不会被
    # 动态路由 /api/cases/{case_id} 吞掉。
    app.include_router(demo.router)
    app.include_router(cases.router)
    app.include_router(datasets.router)
    app.include_router(experiments.router)
    app.include_router(runs.router)
    app.include_router(results.router)
    # v0.7.0：DAT 微震导入/派生路由退出产品面（预置 CSV 案例取代）；
    # 派生服务层与历史运行时文件保留，通用结果/数据集读取不受影响。
    # v0.6 专业分析路由：精确前缀，不遮蔽 legacy 与微震路由；前端挂载之前注册
    app.include_router(professional.router)
    # v0.6.1 原生体渲染路由：显式 POST 变异 + 纯查询 GET；结果路由之后、
    # 前端静态挂载之前注册，精确前缀不遮蔽 legacy 与微震路由
    app.include_router(rendering.router)

    # -------------------------------------------------------- frontend
    settings = get_settings()
    if settings.frontend_dist is not None:
        app.mount("/", StaticFiles(directory=str(settings.frontend_dist), html=True), name="web")

    return app


app = create_app()
