from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from geomodeling.api.app import create_app
from geomodeling.platform import tables
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.experiments import expand_candidates, validate_ml_experiment
from geomodeling.platform.schemas import ExperimentCreateRequest


def _frame(rows: int, groups: int) -> pd.DataFrame:
    group = np.arange(rows) % groups
    return pd.DataFrame(
        {
            "source_row": np.arange(rows),
            "x": group.astype(float),
            "y": (group * 2).astype(float),
            "z": (np.arange(rows) // groups).astype(float),
            "value": np.sin(np.arange(rows) / 5),
            "is_numeric_valid": True,
        }
    )


def test_experimental_random_forest_requires_explicit_confirmation():
    request = ExperimentCreateRequest(
        case_id="c1",
        name="RF",
        algorithm="random_forest_spatial",
        dataset_version_id="d1",
    )
    with pytest.raises(PlatformError) as caught:
        validate_ml_experiment(request, _frame(100, 20), "3d")
    assert caught.value.code == "ML_EXPERIMENTAL_CONFIRMATION_REQUIRED"

    confirmed = request.model_copy(update={"ml_experimental_confirmed": True})
    capability = validate_ml_experiment(confirmed, _frame(100, 20), "3d")
    assert capability.level == "experimental"


def test_residual_correction_requires_supported_dataset():
    request = ExperimentCreateRequest(
        case_id="c1",
        name="Residual",
        algorithm="kriging_rf_residual",
        dataset_version_id="d1",
        ml_experimental_confirmed=True,
    )
    with pytest.raises(PlatformError) as caught:
        validate_ml_experiment(request, _frame(100, 20), "3d")
    assert caught.value.code == "ML_DATASET_TOO_SMALL"


def test_machine_learning_candidate_fingerprint_includes_feature_version():
    search = {
        "algorithm": "random_forest_spatial",
        "search_mode": "manual",
        "parameters": {"n_estimators": 40},
        "validation": {"method": "spatial_kfold", "folds": 5, "seed": 7},
        "grid": None,
    }
    candidate = expand_candidates(search)[0]
    assert candidate.parameters["feature_version"] == "spatial_features.v1"

    changed = expand_candidates({**search, "parameters": {"n_estimators": 40, "random_state": 8}})[0]
    assert candidate.fingerprint != changed.fingerprint


def _insert_dataset(runtime, *, rows: int, groups: int) -> tuple[str, str]:
    case_id = "case-ml"
    dataset_id = "dataset-ml"
    frame = _frame(rows, groups)
    path = runtime.settings.standardized_dataset(case_id, dataset_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    with runtime.session() as session:
        session.add(tables.Case(id=case_id, name="ML", case_type="generic", config_json="{}"))
        session.add(
            tables.DatasetVersion(
                id=dataset_id,
                case_id=case_id,
                version=1,
                status="validated",
                source_path="source.csv",
                standardized_path=str(path),
                profile_json=tables.dumps_canonical(
                    {
                        "mapping": {"dimension": "3d", "x": "x", "y": "y", "z": "z", "value": "value"},
                        "quality": {"status": "passed", "confirmed": True},
                    }
                ),
            )
        )
        session.commit()
    return case_id, dataset_id


def test_experiment_api_enforces_capability_before_persisting(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GEOMODELING_DATA_DIR", str(tmp_path / "runtime"))
    app = create_app()
    with TestClient(app) as client:
        case_id, dataset_id = _insert_dataset(app.state.platform_runtime, rows=58, groups=58)
        response = client.post(
            "/api/experiments",
            json={
                "case_id": case_id,
                "name": "瓦斯 RF",
                "algorithm": "random_forest_spatial",
                "dataset_version_id": dataset_id,
            },
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ML_DATASET_TOO_SMALL"
        with app.state.platform_runtime.session() as session:
            assert session.query(tables.Experiment).count() == 0
