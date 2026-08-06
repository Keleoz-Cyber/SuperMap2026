"""Tests for active-case access guards (v0.7.0 batch 3 Task 5)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from geomodeling.api.app import create_app
from geomodeling.platform import PlatformRuntime


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOMODELING_DATA_DIR", str(tmp_path / "data"))
    return create_app()


@pytest.fixture()
def client(app):
    with TestClient(app) as client:
        yield client


def create_case(client, name="测试案例") -> str:
    resp = client.post("/api/cases", json={"name": name, "case_type": "generic"})
    return resp.json()["id"]


def create_dataset(client, case_id: str) -> str:
    resp = client.post(
        f"/api/cases/{case_id}/datasets/uploads",
        files={"file": ("test.csv", b"x,y,value\n1,2,3\n", "text/csv")},
    )
    return resp.json()["id"]


class TestActiveCaseGuards:
    def test_trashed_case_omitted_from_home(self, client):
        case_id = create_case(client, name="案例A")
        create_case(client, name="案例B")
        client.delete(f"/api/cases/{case_id}")

        resp = client.get("/api/cases")
        case_ids = [c["case_id"] for c in resp.json()["cases"]
                    if c.get("workspace_kind") == "user_upload"]
        assert case_id not in case_ids

    def test_trashed_case_workspace_returns_410(self, client):
        case_id = create_case(client, name="工作台测试")
        client.delete(f"/api/cases/{case_id}")

        resp = client.get(f"/api/cases/{case_id}/workspace")
        assert resp.status_code == 410
        assert resp.json()["error"]["code"] == "CASE_TRASHED"

    def test_trashed_case_get_returns_410(self, client):
        case_id = create_case(client)
        client.delete(f"/api/cases/{case_id}")

        resp = client.get(f"/api/cases/{case_id}")
        assert resp.status_code == 410
        assert resp.json()["error"]["code"] == "CASE_TRASHED"

    def test_restore_reactivates_case(self, client):
        case_id = create_case(client, name="恢复测试")
        client.delete(f"/api/cases/{case_id}")

        resp = client.post(f"/api/cases/{case_id}/restore")
        assert resp.status_code == 200

        # Case should be visible again
        resp = client.get(f"/api/cases/{case_id}/workspace")
        assert resp.status_code == 200

    def test_unknown_case_returns_404(self, client):
        resp = client.get("/api/cases/no-such-case/workspace")
        assert resp.status_code == 404

    def test_builtin_cards_remain_visible(self, client):
        resp = client.get("/api/cases")
        case_ids = [c["case_id"] for c in resp.json()["cases"]]
        assert "resistivity" in case_ids
