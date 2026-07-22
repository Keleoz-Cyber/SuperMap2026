"""FastAPI application for the v0.3 browser platform.

Run locally:

    uvicorn geomodeling.api.app:app --host 127.0.0.1 --port 8000

The browser talks only to this API; iServer admin credentials stay on the
server side (environment variables), and iServer outages degrade to a
recoverable "publish failed / unavailable" state without touching modeling
evidence.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from geomodeling.api import case_service
from geomodeling.api.deps import (
    PROJECT_VERSION,
    ApiSettings,
    get_app_config,
    get_iserver_client,
    get_settings,
)
from geomodeling.publishing import (
    IServerClient,
    BrowserLoadReport,
    S3MBContractError,
    probe_iserver,
    record_browser_load,
)


def create_app() -> FastAPI:
    app = FastAPI(title="GeoModelingPlatform API", version=PROJECT_VERSION)

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
    def cases() -> dict:
        return {"cases": case_service.list_cases()}

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

    # -------------------------------------------------------- frontend
    settings = get_settings()
    if settings.frontend_dist is not None:
        app.mount("/", StaticFiles(directory=str(settings.frontend_dist), html=True), name="web")

    return app


app = create_app()
