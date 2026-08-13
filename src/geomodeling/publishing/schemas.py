"""Pydantic contracts for SuperMap iServer runtime probing and publish evidence.

These models describe *runtime* evidence collected from a live iServer.
They never mutate the v0.1/v0.2a registries; they sit next to them as a
separate evidence layer, per docs/project-guide.md.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SceneIdentity(BaseModel):
    """Expected identity of the iServer realspace scene for a result."""

    service_url: str
    scene_name: str


class VoxelCacheIdentity(BaseModel):
    """Expected identity of the published S3M voxel cache for a result."""

    service_url: str
    cache_data_name: str


class EvidenceStateName(str, Enum):
    """Ordered publish evidence states from docs/project-guide.md."""

    MODEL_SUCCEEDED = "model_succeeded"
    ARTIFACT_EXPORTED = "artifact_exported"
    ISERVER_PUBLISHED = "iserver_published"
    SERVICE_METADATA_VERIFIED = "service_metadata_verified"
    BROWSER_LOADED = "browser_loaded"
    MANUAL_VISUAL_CHECKED = "manual_visual_checked"


EVIDENCE_STATE_ORDER: list[EvidenceStateName] = [
    EvidenceStateName.MODEL_SUCCEEDED,
    EvidenceStateName.ARTIFACT_EXPORTED,
    EvidenceStateName.ISERVER_PUBLISHED,
    EvidenceStateName.SERVICE_METADATA_VERIFIED,
    EvidenceStateName.BROWSER_LOADED,
    EvidenceStateName.MANUAL_VISUAL_CHECKED,
]


class EvidenceSource(str, Enum):
    LIVE_PROBE = "live_probe"
    REGISTRY = "registry"
    CONFIG = "config"
    BROWSER_REPORT = "browser_report"
    MANUAL = "manual"
    NONE = "none"


class EvidenceState(BaseModel):
    """One step of the publish evidence chain."""

    state: EvidenceStateName
    ok: bool = False
    source: EvidenceSource = EvidenceSource.NONE
    checked_at: datetime | None = None
    detail: str = ""


class EvidenceChain(BaseModel):
    """Full publish evidence chain for one SuperMap result dataset."""

    result_id: str
    states: list[EvidenceState] = Field(default_factory=list)

    def state_map(self) -> dict[EvidenceStateName, EvidenceState]:
        return {s.state: s for s in self.states}


class ServiceCheck(BaseModel):
    """Live verification result for one published iServer service."""

    name: str
    service_type: str
    url: str
    reachable: bool = False
    http_status: int | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    checked_at: datetime = Field(default_factory=utc_now)


class IServerStatus(BaseModel):
    """Runtime status of the local iServer as seen by the platform backend."""

    base_url: str
    checked_at: datetime = Field(default_factory=utc_now)
    reachable: bool = False
    http_status: int | None = None
    version: str | None = None
    license_summary: str | None = None
    services: list[ServiceCheck] = Field(default_factory=list)
    error: str | None = None


class RenderKind(str, Enum):
    """What the browser actually rendered for a browser-load report."""

    ISERVER_SCENE = "iserver_scene"
    S3M_VOXEL_CACHE = "s3m_voxel_cache"
    FALLBACK_POINTS = "fallback_points"


class BrowserLoadReport(BaseModel):
    """Browser-side report of an attempted render.

    Only reports with ``success=True``, a non-fallback ``render_kind`` and a
    positive ``validated_count`` may move the publish evidence chain's
    ``browser_loaded`` state; anything else is diagnostic-only. The
    authoritative evidence time is the server receive time, not the
    client-reported clock.
    """

    case_id: str
    result_id: str
    service_url: str
    scene_name: str | None = None
    layer_count: int | None = None
    success: bool = False
    render_kind: RenderKind = RenderKind.FALLBACK_POINTS
    validated_count: int = 0
    client: str = "web"
    note: str = ""
    reported_at: datetime | None = None


class BrowserLoadEvidenceRecord(BaseModel):
    """Persisted browser-load evidence (written under outputs/, git-ignored)."""

    case_id: str
    result_id: str
    service_url: str
    scene_name: str | None = None
    layer_count: int | None = None
    success: bool = False
    render_kind: RenderKind = RenderKind.FALLBACK_POINTS
    validated_count: int = 0
    client: str = "web"
    note: str = ""
    reported_at: datetime
    received_at: datetime = Field(default_factory=utc_now)
