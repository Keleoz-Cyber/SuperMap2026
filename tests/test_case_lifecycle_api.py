"""HTTP contract tests for case lifecycle APIs (v0.7.0 batch 3 §5)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from geomodeling.api.app import create_app
from geomodeling.platform import PlatformRuntime
from geomodeling.platform.repositories import (
    CaseRepository,
    DatasetRepository,
    ExperimentRepository,
    RunRepository,
)
from geomodeling.platform.schemas import (
    Algorithm,
    CaseCreateRequest,
    DatasetStatus,
    ExperimentCreateRequest,
)


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOMODELING_DATA_DIR", str(tmp_path / "data"))
    app = create_app()
    return app


@pytest.fixture()
def client(app):
    with TestClient(app) as client:
        yield client


def create_case_via_api(client, name="API测试案例") -> str:
    resp = client.post("/api/cases", json={"name": name, "case_type": "generic"})
    assert resp.status_code == 201
    return resp.json()["id"]


class TestTrashRoute:
    def test_delete_case_trashes_it(self, client):
        case_id = create_case_via_api(client, name="删除测试")
        resp = client.delete(f"/api/cases/{case_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["lifecycle_state"] == "trashed"
        assert data["trashed_at"] is not None

    def test_delete_builtin_raises_409(self, client):
        resp = client.delete("/api/cases/resistivity")
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "CASE_DELETE_FORBIDDEN"

    def test_delete_unknown_raises_404(self, client):
        resp = client.delete("/api/cases/no-such-case")
        assert resp.status_code == 404


class TestTrashList:
    def test_trash_list_returns_trashed_only(self, client):
        case1 = create_case_via_api(client, name="案例A")
        case2 = create_case_via_api(client, name="案例B")
        client.delete(f"/api/cases/{case1}")

        resp = client.get("/api/trash/cases")
        assert resp.status_code == 200
        items = resp.json()["cases"]
        assert len(items) == 1
        assert items[0]["case_id"] == case1
        assert items[0]["name"] == "案例A"
        assert "trashed_at" in items[0]
        assert "counts" in items[0]
        assert items[0]["can_restore"] is True
        assert items[0]["can_purge"] is True


class TestRestoreRoute:
    def test_restore_trashed_case(self, client):
        case_id = create_case_via_api(client, name="恢复测试")
        client.delete(f"/api/cases/{case_id}")
        resp = client.post(f"/api/cases/{case_id}/restore")
        assert resp.status_code == 200
        assert resp.json()["lifecycle_state"] == "active"
        assert resp.json()["trashed_at"] is None


class TestPurgeRoute:
    def test_purge_with_correct_name(self, client):
        case_id = create_case_via_api(client, name="永久删除测试")
        client.delete(f"/api/cases/{case_id}")
        resp = client.post(
            f"/api/cases/{case_id}/purge",
            json={"confirmation_name": "永久删除测试"},
        )
        assert resp.status_code == 200
        assert resp.json()["state"] == "cleaned"

    def test_purge_with_wrong_name_raises_422(self, client):
        case_id = create_case_via_api(client, name="正确名称")
        client.delete(f"/api/cases/{case_id}")
        resp = client.post(
            f"/api/cases/{case_id}/purge",
            json={"confirmation_name": "错误名称"},
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "CASE_PURGE_CONFIRMATION_MISMATCH"

    def test_purge_active_case_raises_409(self, client):
        case_id = create_case_via_api(client, name="未回收")
        resp = client.post(
            f"/api/cases/{case_id}/purge",
            json={"confirmation_name": "未回收"},
        )
        assert resp.status_code == 409
