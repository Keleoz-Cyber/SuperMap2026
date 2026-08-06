"""Tests for resumable data preparation (v0.7.0 batch 3 §6)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from geomodeling.api.app import create_app
from geomodeling.platform import PlatformRuntime
from geomodeling.platform.data_preparation import (
    DataPreparationSummary,
    resolve_data_preparation,
)
from geomodeling.platform.repositories import (
    DatasetRepository,
    CaseRepository,
)
from geomodeling.platform.schemas import (
    CaseCreateRequest,
    DatasetStatus,
)
from geomodeling.platform import tables as tbl


@pytest.fixture()
def runtime(tmp_path):
    rt = PlatformRuntime(tmp_path / "runtime")
    rt.initialize()
    yield rt
    rt.close()


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOMODELING_DATA_DIR", str(tmp_path / "data"))
    return create_app()


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


def create_case(runtime, name="测试", config=None):
    with runtime.session() as session:
        return CaseRepository(session).create(
            CaseCreateRequest(name=name, case_type="generic", config=config or {})
        ).id


def create_dataset(runtime, case_id, source_path=None):
    """Create a dataset with an actual source file."""
    with runtime.session() as session:
        record = DatasetRepository(session).create_version(
            case_id, source_path="placeholder"
        )
    # Create actual source file
    if source_path is None:
        source_path = runtime.settings.upload_source(case_id, record.id, "csv")
    source_path = Path(source_path)
    source_path.parent.mkdir(parents=True, exist_ok=True)
    content = b"x,y,value\n1,2,3\n"
    source_path.write_bytes(content)
    sha = hashlib.sha256(content).hexdigest()
    with runtime.session() as session:
        row = session.get(tbl.DatasetVersion, record.id)
        row.source_path = str(source_path)
        profile = tbl.loads_canonical(row.profile_json)
        profile["source_sha256"] = sha
        row.profile_json = tbl.dumps_canonical(profile)
        session.commit()
    return record.id


class TestDataPreparationResolver:
    def test_no_dataset_needs_upload(self, runtime):
        case_id = create_case(runtime)
        with runtime.session() as session:
            datasets = DatasetRepository(session).list_for_case(case_id)
        prep = resolve_data_preparation(runtime, case_id, datasets)
        assert prep.state == "needs_upload"
        assert prep.next_action.step == "upload"

    def test_uploaded_needs_mapping(self, runtime):
        case_id = create_case(runtime)
        did = create_dataset(runtime, case_id)
        with runtime.session() as session:
            datasets = DatasetRepository(session).list_for_case(case_id)
        prep = resolve_data_preparation(runtime, case_id, datasets)
        assert prep.state == "needs_mapping"
        assert prep.dataset_id == did

    def test_mapped_needs_quality_review(self, runtime):
        case_id = create_case(runtime)
        did = create_dataset(runtime, case_id)
        with runtime.session() as session:
            repo = DatasetRepository(session)
            repo.transition_status(did, DatasetStatus.MAPPED)
            datasets = repo.list_for_case(case_id)
        prep = resolve_data_preparation(runtime, case_id, datasets)
        assert prep.state == "needs_quality_review"

    def test_validated_is_ready(self, runtime):
        case_id = create_case(runtime)
        did = create_dataset(runtime, case_id)
        with runtime.session() as session:
            repo = DatasetRepository(session)
            repo.transition_status(did, DatasetStatus.MAPPED)
            repo.transition_status(did, DatasetStatus.VALIDATED)
            datasets = repo.list_for_case(case_id)
        prep = resolve_data_preparation(runtime, case_id, datasets)
        assert prep.state == "ready"
        assert prep.next_action.step == "experiment"

    def test_validated_v1_plus_uploaded_v2_targets_v2(self, runtime):
        case_id = create_case(runtime)
        v1 = create_dataset(runtime, case_id)
        with runtime.session() as session:
            repo = DatasetRepository(session)
            repo.transition_status(v1, DatasetStatus.MAPPED)
            repo.transition_status(v1, DatasetStatus.VALIDATED)
        v2 = create_dataset(runtime, case_id)
        with runtime.session() as session:
            datasets = DatasetRepository(session).list_for_case(case_id)
        prep = resolve_data_preparation(runtime, case_id, datasets)
        assert prep.state == "needs_mapping"
        assert prep.dataset_id == v2
        assert prep.latest_validated_dataset_id == v1

    def test_abandoned_v2_returns_to_ready_with_v1(self, runtime):
        case_id = create_case(runtime)
        v1 = create_dataset(runtime, case_id)
        with runtime.session() as session:
            repo = DatasetRepository(session)
            repo.transition_status(v1, DatasetStatus.MAPPED)
            repo.transition_status(v1, DatasetStatus.VALIDATED)
        v2 = create_dataset(runtime, case_id)
        # v2 stays as uploaded (incomplete), then abandon it
        with runtime.session() as session:
            repo = DatasetRepository(session)
            repo.transition_status(v2, DatasetStatus.ABANDONED)
            datasets = repo.list_for_case(case_id)
        prep = resolve_data_preparation(runtime, case_id, datasets)
        assert prep.state == "ready"
        assert prep.latest_validated_dataset_id == v1


class TestAbandonRoute:
    def test_abandon_uploaded_dataset(self, client):
        resp = client.post("/api/cases", json={"name": "test", "case_type": "generic"})
        case_id = resp.json()["id"]
        resp = client.post(
            f"/api/cases/{case_id}/datasets/uploads",
            files={"file": ("test.csv", b"x,y,v\n1,2,3\n", "text/csv")},
        )
        dataset_id = resp.json()["id"]

        resp = client.post(f"/api/datasets/{dataset_id}/abandon")
        assert resp.status_code == 200
        assert resp.json()["status"] == "abandoned"

    def test_abandon_validated_raises_409(self, tmp_path, monkeypatch):
        """Validated datasets cannot be abandoned."""
        monkeypatch.setenv("GEOMODELING_DATA_DIR", str(tmp_path / "data"))
        app = create_app()
        with TestClient(app) as client:
            resp = client.post("/api/cases", json={"name": "test", "case_type": "generic"})
            case_id = resp.json()["id"]
            resp = client.post(
                f"/api/cases/{case_id}/datasets/uploads",
                files={"file": ("test.csv", b"x,y,v\n1,2,3\n", "text/csv")},
            )
            dataset_id = resp.json()["id"]

            # Transition to validated through the runtime
            runtime = app.state.platform_runtime
            with runtime.session() as session:
                from geomodeling.platform.repositories import DatasetRepository
                from geomodeling.platform.schemas import DatasetStatus
                repo = DatasetRepository(session)
                repo.transition_status(dataset_id, DatasetStatus.MAPPED)
                repo.transition_status(dataset_id, DatasetStatus.VALIDATED)

            resp = client.post(f"/api/datasets/{dataset_id}/abandon")
            assert resp.status_code == 409
            assert resp.json()["error"]["code"] == "DATASET_ABANDON_FORBIDDEN"


class TestWorkspaceDataPreparation:
    def test_workspace_includes_data_preparation(self, client):
        resp = client.post("/api/cases", json={"name": "test", "case_type": "generic"})
        case_id = resp.json()["id"]

        resp = client.get(f"/api/cases/{case_id}/workspace")
        assert resp.status_code == 200
        data = resp.json()
        assert "data_preparation" in data
        assert data["data_preparation"]["state"] == "needs_upload"
