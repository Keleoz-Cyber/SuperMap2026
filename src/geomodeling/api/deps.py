"""API application settings resolved from the environment.

Everything here has a safe default for the local defense machine; secrets
(iServer admin credentials) only ever arrive via environment variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fastapi import Request

from geomodeling.config import AppConfig, load_config
from geomodeling.platform import PlatformRuntime
from geomodeling.publishing import IServerClient

ENV_CONFIG = "GEOMODELING_CONFIG"
ENV_METRICS = "GEOMODELING_METRICS_JSON"
ENV_EVIDENCE_DIR = "GEOMODELING_EVIDENCE_DIR"
ENV_FRONTEND_DIST = "GEOMODELING_FRONTEND_DIST"
ENV_VOXEL_CACHE_DIR = "GEOMODELING_VOXEL_CACHE_DIR"

DEFAULT_CONFIG = "config/default.yaml"
DEFAULT_METRICS_CANDIDATES = [
    "outputs/release_verify/metrics/metric_summaries.json",
    "outputs/metrics/metric_summaries.json",
]
DEFAULT_EVIDENCE_DIR = "outputs/api_evidence"
DEFAULT_FRONTEND_DIST = "web/dist"
DEFAULT_VOXEL_CACHE_DIR = "../Project/cache/RHO_KRIG_FINAL_20M_40_VOL_S3M2"

PROJECT_VERSION = "0.3.0"


@dataclass(frozen=True)
class ApiSettings:
    config_path: Path
    metrics_json: Path | None
    evidence_dir: Path
    frontend_dist: Path | None
    voxel_cache_dir: Path | None


@lru_cache(maxsize=1)
def get_settings() -> ApiSettings:
    config_path = Path(os.environ.get(ENV_CONFIG, DEFAULT_CONFIG))

    metrics_env = os.environ.get(ENV_METRICS)
    if metrics_env:
        metrics_json: Path | None = Path(metrics_env)
    else:
        metrics_json = None
        for candidate in DEFAULT_METRICS_CANDIDATES:
            if Path(candidate).exists():
                metrics_json = Path(candidate)
                break

    evidence_dir = Path(os.environ.get(ENV_EVIDENCE_DIR, DEFAULT_EVIDENCE_DIR))

    dist_env = os.environ.get(ENV_FRONTEND_DIST)
    dist = Path(dist_env) if dist_env else Path(DEFAULT_FRONTEND_DIST)
    frontend_dist = dist if (dist / "index.html").exists() else None

    voxel_env = os.environ.get(ENV_VOXEL_CACHE_DIR)
    voxel_cache_dir = Path(voxel_env) if voxel_env else None

    return ApiSettings(
        config_path=config_path,
        metrics_json=metrics_json,
        evidence_dir=evidence_dir,
        frontend_dist=frontend_dist,
        voxel_cache_dir=voxel_cache_dir,
    )


@lru_cache(maxsize=1)
def get_app_config() -> AppConfig:
    return load_config(get_settings().config_path)


def get_iserver_client() -> IServerClient:
    """Fresh short-lived client per call; iServer state is probed live."""

    return IServerClient.from_env(timeout=10.0)


def get_platform_runtime(request: Request) -> PlatformRuntime:
    """v0.4 runtime attached to ``app.state`` by the lifespan (Task 10).

    Declared here so routes and tests can depend on it without touching the
    legacy settings above; tests override it via ``dependency_overrides``.
    """

    runtime = getattr(request.app.state, "platform_runtime", None)
    if runtime is None:
        raise RuntimeError("platform runtime is not attached to the application")
    return runtime
