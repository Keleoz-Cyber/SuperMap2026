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
from geomodeling.api.routes import cases, datasets, experiments, results, runs
from geomodeling.platform import PlatformRuntime
from geomodeling.platform.errors import (
    REDACTED_PATH,
    PlatformError,
    platform_error_handler,
)
from geomodeling.platform.legacy_adapter import merged_case_cards
from geomodeling.platform.repositories import CaseRepository
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
        if runtime is not None:
            with runtime.session() as session:
                records = CaseRepository(session).list_all()
        return {"cases": merged_case_cards(records)}

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
    app.include_router(cases.router)
    app.include_router(datasets.router)
    app.include_router(experiments.router)
    app.include_router(runs.router)
    app.include_router(results.router)

    # -------------------------------------------------------- frontend
    settings = get_settings()
    if settings.frontend_dist is not None:
        app.mount("/", StaticFiles(directory=str(settings.frontend_dist), html=True), name="web")

    return app


app = create_app()
