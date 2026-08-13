"""Runtime probing of a local SuperMap iServer.

Probing answers three questions without touching modeling state:

1. Is iServer reachable and what version/license does it report?
2. Which platform-relevant services exist (data / map / 3D)?
3. For a given result dataset, does the published service metadata match
   the registered facts (datasource, dataset, type, bounds, value range)?
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .client import IServerClient
from .schemas import (
    EvidenceChain,
    EvidenceSource,
    EvidenceState,
    EvidenceStateName,
    IServerStatus,
    ServiceCheck,
)

# Services published from ../Project/WorkSpace.smwu on 2026-07-22 (manual
# evidence via the iServer admin UI; see docs/project-guide.md).
DATA_SERVICE_NAME = "data-WorkSpace"
MAP_SERVICE_NAME = "map-WorkSpace"
REALSPACE_SERVICE_NAME = "3D-WorkSpace"
RHO_DATASOURCE = "expore1"
RHO_FORMAL_DATASET = "RHO_KRIG_FINAL_20M_40"
RHO_SCENE_NAME = "RHO_三维全值域"

# Volume rendering path: iDesktopX 体元栅格生成缓存（S3M 2.0，输出目录与
# 数据集 RHO_KRIG_FINAL_20M_40_VOL_S3M2 同名）发布的三维瓦片服务。可用
# GEOMODELING_VOLUME_SERVICE 覆盖。
VOLUME_SERVICE_NAME = "3D-local3DCache-RHO_KRIG_FINAL_20M_40_VOL_S3M2"
VOLUME_SCENE_NAME = "默认场景"


def _service_url(base_url: str, name: str, rest: str = "rest") -> str:
    return f"{base_url}/services/{name}/{rest}"


def probe_iserver(client: IServerClient, service_names: list[str] | None = None) -> IServerStatus:
    """Check iServer reachability, services list, and per-service metadata."""

    status = IServerStatus(base_url=client.base_url)
    root = client.get_json("services.rjson")
    status.reachable = root.ok
    status.http_status = root.status_code
    if not root.ok:
        status.error = root.error or "iServer services list unavailable"
        return status

    raw_services: list[dict[str, Any]] = root.data if isinstance(root.data, list) else []
    by_name = {str(s.get("name", "")): s for s in raw_services}
    wanted = service_names or [DATA_SERVICE_NAME, MAP_SERVICE_NAME, REALSPACE_SERVICE_NAME]

    for name in wanted:
        key = f"{name}/rest"
        entry = by_name.get(key)
        url = entry.get("url") if entry else _service_url(client.base_url, name)
        check = ServiceCheck(
            name=name,
            service_type=(entry or {}).get("componentType", "") or "unknown",
            url=str(url),
        )
        if entry is None:
            check.error = "service not published"
            status.services.append(check)
            continue
        check.reachable = True
        status.services.append(check)
    return status


def verify_data_service(
    client: IServerClient,
    *,
    datasource: str = RHO_DATASOURCE,
    dataset: str = RHO_FORMAL_DATASET,
    service_name: str = DATA_SERVICE_NAME,
    expected: dict[str, Any] | None = None,
) -> ServiceCheck:
    """Verify that the data service exposes the formal voxel dataset.

    ``expected`` may carry ``type``, ``value_min``, ``value_max``, ``width``
    and ``height`` from the platform registry; mismatches are reported in
    ``detail.mismatches`` without raising.
    """

    from .client import encode_segment

    base = f"services/{service_name}/rest/data"
    url = f"{client.base_url}/{base}"
    check = ServiceCheck(name=service_name, service_type="RESTDATA", url=url)

    ds_resp = client.get_json(f"{base}/datasources.rjson")
    check.http_status = ds_resp.status_code
    if not ds_resp.ok:
        check.error = ds_resp.error
        return check
    names = (ds_resp.data or {}).get("datasourceNames", [])
    check.detail["datasource_names"] = names
    if datasource not in names:
        check.error = f"datasource {datasource} missing"
        return check

    dt_resp = client.get_json(f"{base}/datasources/{encode_segment(datasource)}/datasets.rjson")
    if not dt_resp.ok:
        check.error = dt_resp.error
        return check
    dt_names = (dt_resp.data or {}).get("datasetNames", [])
    check.detail["dataset_count"] = len(dt_names)
    if dataset not in dt_names:
        check.error = f"dataset {dataset} missing"
        return check

    meta_resp = client.get_json(
        f"{base}/datasources/{encode_segment(datasource)}/datasets/{encode_segment(dataset)}.rjson"
    )
    if not meta_resp.ok:
        check.error = meta_resp.error
        return check
    info = (meta_resp.data or {}).get("datasetInfo", {})
    check.detail["dataset_info"] = {
        "type": info.get("type"),
        "width": info.get("width"),
        "height": info.get("height"),
        "minValue": info.get("minValue"),
        "maxValue": info.get("maxValue"),
        "bounds": info.get("bounds"),
        "prjCoordSys": (info.get("prjCoordSys") or {}).get("type"),
    }

    mismatches: list[str] = []
    if expected:
        comparisons = [
            ("type", info.get("type"), expected.get("type")),
            ("width", info.get("width"), expected.get("width")),
            ("height", info.get("height"), expected.get("height")),
        ]
        for field, actual, wanted in comparisons:
            if wanted is not None and actual != wanted:
                mismatches.append(f"{field}: registry={wanted!r} iserver={actual!r}")
        for field, key in [("value_min", "minValue"), ("value_max", "maxValue")]:
            wanted = expected.get(field)
            actual = info.get(key)
            if wanted is not None and actual is not None and abs(float(actual) - float(wanted)) > 1e-4:
                mismatches.append(f"{field}: registry={wanted!r} iserver={actual!r}")
    check.detail["mismatches"] = mismatches
    check.reachable = True
    if mismatches:
        check.error = "metadata mismatch: " + "; ".join(mismatches)
    return check


def verify_realspace_service(
    client: IServerClient,
    *,
    scene_name: str = RHO_SCENE_NAME,
    service_name: str = REALSPACE_SERVICE_NAME,
) -> ServiceCheck:
    """Verify that the 3D service exposes the resistivity scene."""

    from .client import encode_segment

    url = f"{client.base_url}/services/{service_name}/rest/realspace"
    check = ServiceCheck(name=service_name, service_type="RESTREALSPACE", url=url)
    scenes = client.get_json(f"services/{service_name}/rest/realspace/scenes.rjson")
    check.http_status = scenes.status_code
    if not scenes.ok:
        check.error = scenes.error
        return check
    names = [s.get("name") for s in scenes.data or []]
    check.detail["scene_names"] = names
    if scene_name not in names:
        check.error = f"scene {scene_name} missing"
        return check
    layers = client.get_json(
        f"services/{service_name}/rest/realspace/scenes/{encode_segment(scene_name)}/layers.rjson"
    )
    if layers.ok:
        check.detail["layers"] = [
            {
                "name": layer.get("name"),
                "layer3DType": layer.get("layer3DType"),
                "visible": layer.get("visible"),
            }
            for layer in layers.data or []
        ]
    check.reachable = True
    return check


def build_publish_evidence_chain(
    *,
    result_id: str,
    registry_states: dict[str, tuple[bool, str]],
    live_states: dict[str, tuple[bool, str]] | None = None,
    browser_record: "BrowserLoadEvidenceRecord | None" = None,
) -> EvidenceChain:
    """Merge registry/config evidence with live probe evidence.

    ``registry_states`` maps state name -> (ok, detail) from platform
    registries (e.g. model_succeeded). ``live_states`` maps state name ->
    (ok, detail) from the live iServer probe. ``browser_record`` is the
    newest identity-validated browser render report; anything without one
    keeps ``browser_loaded`` grey (diagnostics never turn it green).
    """

    live_states = live_states or {}
    chain = EvidenceChain(result_id=result_id)
    now = datetime.now(timezone.utc)

    for state_name in [
        EvidenceStateName.MODEL_SUCCEEDED,
        EvidenceStateName.ARTIFACT_EXPORTED,
        EvidenceStateName.ISERVER_PUBLISHED,
        EvidenceStateName.SERVICE_METADATA_VERIFIED,
    ]:
        key = state_name.value
        if key in live_states:
            ok, detail = live_states[key]
            source = EvidenceSource.LIVE_PROBE
        elif key in registry_states:
            ok, detail = registry_states[key]
            source = EvidenceSource.REGISTRY
        else:
            ok, detail = False, "no evidence"
            source = EvidenceSource.NONE
        chain.states.append(
            EvidenceState(state=state_name, ok=ok, source=source, checked_at=now, detail=detail)
        )

    if browser_record is not None:
        browser_detail = (
            f"{browser_record.render_kind.value} 渲染回执：{browser_record.validated_count} 个有效单元，"
            f"服务器接收于 {browser_record.received_at.isoformat()}"
        )
        chain.states.append(
            EvidenceState(
                state=EvidenceStateName.BROWSER_LOADED,
                ok=True,
                source=EvidenceSource.BROWSER_REPORT,
                checked_at=browser_record.received_at,
                detail=browser_detail,
            )
        )
    else:
        chain.states.append(
            EvidenceState(
                state=EvidenceStateName.BROWSER_LOADED,
                ok=False,
                source=EvidenceSource.NONE,
                checked_at=None,
                detail="no valid browser render report (diagnostics do not count)",
            )
        )
    manual_ok, manual_detail = registry_states.get(
        EvidenceStateName.MANUAL_VISUAL_CHECKED.value, (False, "no manual evidence")
    )
    chain.states.append(
        EvidenceState(
            state=EvidenceStateName.MANUAL_VISUAL_CHECKED,
            ok=manual_ok,
            source=EvidenceSource.MANUAL if manual_ok else EvidenceSource.NONE,
            checked_at=now if manual_ok else None,
            detail=manual_detail,
        )
    )
    return chain
