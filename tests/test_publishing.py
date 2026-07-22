"""Portable tests for the iServer publishing adapter (no live iServer)."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from geomodeling.publishing import (
    IServerClient,
    build_publish_evidence_chain,
    latest_browser_load,
    latest_valid_browser_load,
    probe_iserver,
    record_browser_load,
    verify_data_service,
    verify_realspace_service,
)
from geomodeling.publishing.evidence import BROWSER_LOADS_FILENAME
from geomodeling.publishing.schemas import (
    BrowserLoadEvidenceRecord,
    BrowserLoadReport,
    EvidenceStateName,
    RenderKind,
)


class FakeClient:
    """Scripted stand-in for IServerClient.get_json."""

    def __init__(self, responses: dict[str, object], base_url: str = "http://iserver.test/iserver"):
        self.responses = responses
        self.base_url = base_url

    class _Resp:
        def __init__(self, ok, data=None, error=None, status=200):
            self.ok = ok
            self.data = data
            self.error = error
            self.status_code = status

    def get_json(self, path: str, *, use_token: bool = False):
        key = path.lstrip("/")
        value = self.responses.get(key)
        if value is None:
            return self._Resp(False, error="not scripted", status=None)
        if isinstance(value, Exception):
            return self._Resp(False, error=str(value), status=None)
        return self._Resp(True, data=value)


SERVICES_LIST = [
    {"name": "data-WorkSpace/rest", "url": "http://iserver.test/iserver/services/data-WorkSpace/rest"},
    {"name": "map-WorkSpace/rest", "url": "http://iserver.test/iserver/services/map-WorkSpace/rest"},
    {"name": "3D-WorkSpace/rest", "url": "http://iserver.test/iserver/services/3D-WorkSpace/rest"},
]

DATASET_INFO = {
    "datasetInfo": {
        "type": "VOLUME",
        "width": 7,
        "height": 23,
        "minValue": 1.4182828664779663,
        "maxValue": 133.1461944580078,
        "bounds": {"left": -160, "right": -40, "top": 660, "bottom": 220},
        "prjCoordSys": {"type": "PCS_NON_EARTH"},
    }
}


def scripted_client() -> FakeClient:
    return FakeClient(
        {
            "services.rjson": SERVICES_LIST,
            "services/data-WorkSpace/rest/data/datasources.rjson": {"datasourceNames": ["expore1"]},
            "services/data-WorkSpace/rest/data/datasources/expore1/datasets.rjson": {
                "datasetNames": ["RHO_KRIG_FINAL_20M_40", "RHO_ISO_77_K40"]
            },
            "services/data-WorkSpace/rest/data/datasources/expore1/datasets/RHO_KRIG_FINAL_20M_40.rjson": DATASET_INFO,
            "services/3D-WorkSpace/rest/realspace/scenes.rjson": [{"name": "RHO_三维全值域"}],
            "services/3D-WorkSpace/rest/realspace/scenes/RHO_%E4%B8%89%E7%BB%B4%E5%85%A8%E5%80%BC%E5%9F%9F/layers.rjson": [
                {"name": "RHO_KRIG_FINAL_20M_40@expore1", "layer3DType": "ImageFileLayer", "visible": True}
            ],
        }
    )


def test_probe_iserver_lists_platform_services():
    status = probe_iserver(scripted_client())
    assert status.reachable is True
    names = {s.name: s for s in status.services}
    assert set(names) == {"data-WorkSpace", "map-WorkSpace", "3D-WorkSpace"}
    assert all(s.reachable for s in names.values())


def test_probe_iserver_marks_missing_service():
    client = FakeClient({"services.rjson": SERVICES_LIST[:1]})
    status = probe_iserver(client)
    by_name = {s.name: s for s in status.services}
    assert by_name["data-WorkSpace"].reachable is True
    assert by_name["3D-WorkSpace"].reachable is False
    assert by_name["3D-WorkSpace"].error == "service not published"


def test_probe_iserver_down_is_graceful():
    client = FakeClient({"services.rjson": ConnectionError("connection refused")})
    status = probe_iserver(client)
    assert status.reachable is False
    assert "connection refused" in (status.error or "")


def test_verify_data_service_matches_registry_metadata():
    check = verify_data_service(
        scripted_client(),
        expected={"type": "VOLUME", "width": 7, "height": 23, "value_min": 1.418283, "value_max": 133.146194},
    )
    assert check.reachable is True
    assert check.detail["mismatches"] == []
    assert check.detail["dataset_info"]["type"] == "VOLUME"


def test_verify_data_service_reports_mismatch_without_raising():
    check = verify_data_service(scripted_client(), expected={"type": "VOLUME", "width": 8})
    assert check.reachable is True
    assert any("width" in m for m in check.detail["mismatches"])
    assert check.error is not None


def test_verify_realspace_service_finds_scene_and_layers():
    check = verify_realspace_service(scripted_client())
    assert check.reachable is True
    assert check.detail["scene_names"] == ["RHO_三维全值域"]
    assert check.detail["layers"][0]["layer3DType"] == "ImageFileLayer"


def test_evidence_chain_merges_registry_live_and_browser_states():
    now = datetime(2026, 7, 22, tzinfo=timezone.utc)
    record = BrowserLoadEvidenceRecord(
        case_id="resistivity",
        result_id="RHO_KRIG_FINAL_20M_40",
        service_url="http://iserver.test/iserver/services/3D-WorkSpace/rest/realspace",
        success=True,
        render_kind=RenderKind.ISERVER_SCENE,
        validated_count=4388,
        reported_at=now,
    )
    chain = build_publish_evidence_chain(
        result_id="RHO_KRIG_FINAL_20M_40",
        registry_states={
            "model_succeeded": (True, "status=succeeded"),
            "artifact_exported": (True, "udbx file verified"),
            "manual_visual_checked": (True, "iDesktopX manual check"),
        },
        live_states={
            "iserver_published": (True, "services reachable"),
            "service_metadata_verified": (True, "metadata matches"),
        },
        browser_record=record,
    )
    states = chain.state_map()
    assert states[EvidenceStateName.MODEL_SUCCEEDED].ok is True
    assert states[EvidenceStateName.ISERVER_PUBLISHED].source.value == "live_probe"
    browser_state = states[EvidenceStateName.BROWSER_LOADED]
    assert browser_state.ok is True
    assert browser_state.checked_at == record.received_at
    assert "iserver_scene" in browser_state.detail


def test_evidence_chain_without_valid_browser_record_stays_grey():
    chain = build_publish_evidence_chain(
        result_id="RHO_KRIG_FINAL_20M_40",
        registry_states={"model_succeeded": (True, "status=succeeded")},
        live_states={
            "iserver_published": (True, "reachable"),
            "service_metadata_verified": (True, "matches"),
        },
        browser_record=None,
    )
    browser_state = chain.state_map()[EvidenceStateName.BROWSER_LOADED]
    assert browser_state.ok is False
    assert "do not count" in browser_state.detail


def test_evidence_chain_iserver_down_keeps_model_state():
    chain = build_publish_evidence_chain(
        result_id="RHO_KRIG_FINAL_20M_40",
        registry_states={"model_succeeded": (True, "status=succeeded")},
        live_states={
            "iserver_published": (False, "iServer unreachable"),
            "service_metadata_verified": (False, "iServer unreachable"),
        },
    )
    states = chain.state_map()
    assert states[EvidenceStateName.MODEL_SUCCEEDED].ok is True
    assert states[EvidenceStateName.ISERVER_PUBLISHED].ok is False
    assert states[EvidenceStateName.BROWSER_LOADED].ok is False


def test_browser_load_store_roundtrip(tmp_path):
    report = BrowserLoadReport(
        case_id="resistivity",
        result_id="RHO_KRIG_FINAL_20M_40",
        service_url="http://iserver.test/iserver/services/3D-WorkSpace/rest",
        scene_name="RHO_三维全值域",
        layer_count=1,
        success=True,
        render_kind=RenderKind.ISERVER_SCENE,
        validated_count=4388,
    )
    record_browser_load(report, tmp_path)
    record_browser_load(report, tmp_path)
    latest = latest_browser_load("resistivity", "RHO_KRIG_FINAL_20M_40", tmp_path)
    assert latest is not None
    lines = (tmp_path / BROWSER_LOADS_FILENAME).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert latest_browser_load("resistivity", "OTHER", tmp_path) is None


VALID_KINDS = {RenderKind.ISERVER_SCENE.value, RenderKind.S3M_VOXEL_CACHE.value}
VALID_PREFIXES = ("http://iserver.test/iserver/services/3D-WorkSpace/",)


def _write_report(tmp_path, **overrides):
    payload = {
        "case_id": "resistivity",
        "result_id": "RHO_KRIG_FINAL_20M_40",
        "service_url": "http://iserver.test/iserver/services/3D-WorkSpace/rest/realspace",
        "success": True,
        "render_kind": "iserver_scene",
        "validated_count": 4388,
    }
    payload.update(overrides)
    record_browser_load(BrowserLoadReport(**payload), tmp_path)


def test_latest_valid_browser_load_accepts_valid_report(tmp_path):
    _write_report(tmp_path)
    record = latest_valid_browser_load(
        "resistivity", "RHO_KRIG_FINAL_20M_40", tmp_path,
        allowed_kinds=VALID_KINDS, allowed_service_prefixes=VALID_PREFIXES,
    )
    assert record is not None
    assert record.validated_count == 4388


def test_latest_valid_browser_load_rejects_failed_scene(tmp_path):
    _write_report(tmp_path, success=False)
    record = latest_valid_browser_load(
        "resistivity", "RHO_KRIG_FINAL_20M_40", tmp_path,
        allowed_kinds=VALID_KINDS, allowed_service_prefixes=VALID_PREFIXES,
    )
    assert record is None


def test_latest_valid_browser_load_rejects_fallback_points(tmp_path):
    _write_report(tmp_path, render_kind="fallback_points")
    record = latest_valid_browser_load(
        "resistivity", "RHO_KRIG_FINAL_20M_40", tmp_path,
        allowed_kinds=VALID_KINDS, allowed_service_prefixes=VALID_PREFIXES,
    )
    assert record is None


def test_latest_valid_browser_load_rejects_wrong_result_or_service(tmp_path):
    _write_report(tmp_path, result_id="OTHER_DATASET")
    _write_report(tmp_path, service_url="http://evil.example/fake/rest")
    record = latest_valid_browser_load(
        "resistivity", "RHO_KRIG_FINAL_20M_40", tmp_path,
        allowed_kinds=VALID_KINDS, allowed_service_prefixes=VALID_PREFIXES,
    )
    assert record is None


def test_latest_valid_browser_load_rejects_zero_count(tmp_path):
    _write_report(tmp_path, validated_count=0)
    record = latest_valid_browser_load(
        "resistivity", "RHO_KRIG_FINAL_20M_40", tmp_path,
        allowed_kinds=VALID_KINDS, allowed_service_prefixes=VALID_PREFIXES,
    )
    assert record is None


# ------------------------------------------------------------------ client


def test_client_acquire_token_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/iserver/services/security/tokens.rjson"
        return httpx.Response(200, text="TOKEN123")

    client = IServerClient(base_url="http://iserver.test/iserver", admin_user="u", admin_password="p")
    client._http = httpx.Client(transport=httpx.MockTransport(handler))
    result = client.acquire_token()
    assert result.ok is True
    assert result.data == "TOKEN123"
    assert client._token == "TOKEN123"


def test_client_token_requires_credentials():
    client = IServerClient(base_url="http://iserver.test/iserver")
    result = client.acquire_token()
    assert result.ok is False
    assert "credentials" in (result.error or "")


def test_client_get_json_connection_error_is_graceful():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = IServerClient(base_url="http://iserver.test/iserver")
    client._http = httpx.Client(transport=httpx.MockTransport(handler))
    result = client.get_json("services.rjson")
    assert result.ok is False
    assert result.status_code is None
    assert "ConnectError" in (result.error or "")


def test_client_get_json_invalid_json_reported():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    client = IServerClient(base_url="http://iserver.test/iserver")
    client._http = httpx.Client(transport=httpx.MockTransport(handler))
    result = client.get_json("services.rjson")
    assert result.ok is False
    assert "invalid JSON" in (result.error or "")
