from __future__ import annotations

import numpy as np
import pandas as pd

from geomodeling.platform.ml_capability import assess_ml_capability
from geomodeling.platform.schemas import Algorithm, ExperimentCreateRequest


def _frame(*, rows: int, xy_groups: int) -> pd.DataFrame:
    group = np.arange(rows, dtype="int64") % xy_groups
    return pd.DataFrame(
        {
            "source_row": np.arange(rows, dtype="int64"),
            "x": group.astype("float64"),
            "y": (group * 3).astype("float64"),
            "z": (np.arange(rows, dtype="int64") // xy_groups).astype("float64"),
            "value": np.linspace(1.0, 2.0, rows),
            "is_numeric_valid": np.ones(rows, dtype=bool),
        }
    )


def test_ml_capability_supported_for_sufficient_samples_and_spatial_groups():
    capability = assess_ml_capability(_frame(rows=200, xy_groups=40), "3d")

    assert capability.level == "supported"
    assert capability.valid_sample_count == 200
    assert capability.spatial_group_count == 40
    assert capability.available_algorithms == [
        "random_forest_spatial",
        "kriging_rf_residual",
    ]


def test_ml_capability_experimental_for_mid_sized_dataset():
    capability = assess_ml_capability(_frame(rows=100, xy_groups=20), "3d")

    assert capability.level == "experimental"
    assert capability.available_algorithms == ["random_forest_spatial"]
    assert capability.confirmation_required is True


def test_ml_capability_not_recommended_for_58_point_gas_dataset():
    capability = assess_ml_capability(_frame(rows=58, xy_groups=58), "3d")

    assert capability.level == "not_recommended"
    assert capability.available_algorithms == []
    assert capability.reason_code == "ML_DATASET_TOO_SMALL"


def test_experiment_contract_accepts_machine_learning_algorithms():
    for algorithm in (
        Algorithm.RANDOM_FOREST_SPATIAL,
        Algorithm.KRIGING_RF_RESIDUAL,
    ):
        request = ExperimentCreateRequest(
            case_id="case-1",
            name="机器学习空间预测",
            algorithm=algorithm,
            dataset_version_id="dataset-1",
        )
        assert request.algorithm == algorithm.value

