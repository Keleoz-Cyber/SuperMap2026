"""Tests for active-case access guards (v0.7.0 batch 3 Task 5)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from geomodeling.api.app import create_app
from geomodeling.platform import tables as tbl
from geomodeling.platform.repositories import (
    CandidateRepository,
    ExperimentRepository,
    RunRepository,
)
from geomodeling.platform.schemas import Algorithm, ExperimentCreateRequest


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
    csv_bytes = (
        b"x,y,value\n"
        + b"\n".join(f"{i * 15},{i * 20},{10 + i}".encode() for i in range(12))
        + b"\n"
    )
    resp = client.post(
        f"/api/cases/{case_id}/datasets/uploads",
        files={"file": ("test.csv", csv_bytes, "text/csv")},
    )
    return resp.json()["id"]


MAPPING = {
    "dimension": "2d",
    "x": "x",
    "y": "y",
    "value": "value",
    "value_name": "value",
    "coordinate_kind": "local_linear",
}


def _make_pipeline(app, client):
    """Create case -> dataset -> experiment -> run -> candidate."""
    runtime = app.state.platform_runtime
    case_id = create_case(client, name="深度链接保护测试")
    dataset_id = create_dataset(client, case_id)

    with runtime.session() as session:
        request = ExperimentCreateRequest(
            case_id=case_id,
            name="exp",
            algorithm=Algorithm.IDW,
            dataset_version_id=dataset_id,
            parameters={"power": 2.0},
        )
        experiment_id = ExperimentRepository(session).create(case_id, request).id

    with runtime.session() as session:
        run_id = RunRepository(session).create(experiment_id).id

    with runtime.session() as session:
        repo = RunRepository(session)
        repo.mark_running(run_id)
        repo.mark_succeeded(run_id, metrics={"rmse": 1.0})

    with runtime.session() as session:
        candidate_id = CandidateRepository(session).create(run_id, metrics={"rmse": 0.5}).id
    with runtime.session() as session:
        row = session.get(tbl.CandidateResult, candidate_id)
        row.status = "succeeded"
        session.commit()

    return case_id, dataset_id, experiment_id, run_id, candidate_id


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

        resp = client.get(f"/api/cases/{case_id}/workspace")
        assert resp.status_code == 200

    def test_unknown_case_returns_404(self, client):
        resp = client.get("/api/cases/no-such-case/workspace")
        assert resp.status_code == 404

    def test_builtin_cards_remain_visible(self, client):
        resp = client.get("/api/cases")
        case_ids = [c["case_id"] for c in resp.json()["cases"]]
        assert "resistivity" in case_ids

    def test_trashed_case_all_related_endpoints_return_410(self, client, app):
        """Trashed case: every related endpoint returns 410 CASE_TRASHED."""
        case_id, dataset_id, experiment_id, run_id, candidate_id = _make_pipeline(app, client)

        resp = client.delete(f"/api/cases/{case_id}")
        assert resp.status_code == 200

        checks = [
            ("GET", f"/api/datasets/{dataset_id}", None),
            ("GET", f"/api/datasets/{dataset_id}/points", None),
            ("POST", f"/api/datasets/{dataset_id}/mapping", MAPPING),
            ("GET", f"/api/datasets/{dataset_id}/quality", None),
            ("POST", f"/api/datasets/{dataset_id}/quality/confirm-warnings",
             {"issue_codes": []}),
            ("GET", f"/api/experiments/{experiment_id}", None),
            ("POST", f"/api/experiments/{experiment_id}/runs", None),
            ("GET", f"/api/experiments/{experiment_id}/candidates", None),
            ("GET", f"/api/runs/{run_id}", None),
            ("POST", f"/api/runs/{run_id}/cancel", None),
            ("POST", f"/api/runs/{run_id}/retry", None),
            ("GET", f"/api/results/{candidate_id}", None),
            ("GET", f"/api/results/{candidate_id}/preview", None),
            ("POST", f"/api/results/{candidate_id}/materialize", None),
            ("POST", f"/api/results/{candidate_id}/select-formal",
             {"note": "test", "selected_by": "tester"}),
            ("POST", f"/api/results/{candidate_id}/exports", None),
            ("GET", f"/api/datasets/{dataset_id}/professional-diagnostics", None),
            ("GET", f"/api/datasets/{dataset_id}/comparison-candidates", None),
            ("GET", f"/api/results/{candidate_id}/render-capability", None),
        ]

        for method, path, body in checks:
            if method == "GET":
                resp = client.get(path)
            else:
                resp = client.post(path, json=body)
            assert resp.status_code == 410, (
                f"{method} {path} -> {resp.status_code} (expected 410)"
            )
            assert resp.json()["error"]["code"] == "CASE_TRASHED", (
                f"{method} {path} -> {resp.json()}"
            )

    def test_restore_reactivates_all_related_endpoints(self, client, app):
        """After restore, endpoints return their original (non-410) status."""
        case_id, dataset_id, experiment_id, run_id, candidate_id = _make_pipeline(app, client)

        client.delete(f"/api/cases/{case_id}")
        resp = client.post(f"/api/cases/{case_id}/restore")
        assert resp.status_code == 200

        checks = [
            ("GET", f"/api/datasets/{dataset_id}"),
            ("GET", f"/api/datasets/{dataset_id}/points"),
            ("GET", f"/api/datasets/{dataset_id}/quality"),
            ("GET", f"/api/experiments/{experiment_id}"),
            ("GET", f"/api/experiments/{experiment_id}/candidates"),
            ("GET", f"/api/runs/{run_id}"),
            ("GET", f"/api/results/{candidate_id}"),
            ("GET", f"/api/datasets/{dataset_id}/professional-diagnostics"),
            ("GET", f"/api/datasets/{dataset_id}/comparison-candidates"),
            ("GET", f"/api/results/{candidate_id}/render-capability"),
        ]

        for method, path in checks:
            resp = client.get(path)
            assert resp.status_code != 410, (
                f"{method} {path} -> 410 after restore"
            )
