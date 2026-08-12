"""Dataset suitability contract for machine-learning spatial prediction."""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from geomodeling.modeling import splits
from geomodeling.platform.schemas import Dimension


class MLCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Literal["supported", "experimental", "not_recommended"]
    valid_sample_count: int
    spatial_group_count: int
    available_algorithms: list[str]
    confirmation_required: bool
    reason_code: str | None
    message: str


def _valid_points(frame: pd.DataFrame, dimension: Dimension) -> np.ndarray:
    required = ["x", "y"] + (["z"] if dimension == Dimension.THREE_D else [])
    values = frame["value"].to_numpy(dtype="float64")
    declared = frame["is_numeric_valid"].to_numpy(dtype=bool)
    coordinates = frame[required].to_numpy(dtype="float64")
    finite = np.isfinite(values) & np.isfinite(coordinates).all(axis=1)
    return coordinates[declared & finite]


def assess_ml_capability(frame: pd.DataFrame, dimension: str | Dimension) -> MLCapability:
    """Assess a dataset using the same spatial grouping semantics as validation."""

    dim = Dimension(dimension)
    points = _valid_points(frame, dim)
    if len(points):
        groups = (
            splits._groups_3d(points)
            if dim == Dimension.THREE_D
            else splits._groups_2d(points, 5)
        )
        group_count = int(len(np.unique(groups)))
    else:
        group_count = 0
    sample_count = int(len(points))

    if sample_count >= 200 and group_count >= 30:
        return MLCapability(
            level="supported",
            valid_sample_count=sample_count,
            spatial_group_count=group_count,
            available_algorithms=["random_forest_spatial", "kriging_rf_residual"],
            confirmation_required=False,
            reason_code=None,
            message="样本量和独立空间分组满足机器学习空间验证要求。",
        )
    if sample_count >= 80 and group_count >= 15:
        return MLCapability(
            level="experimental",
            valid_sample_count=sample_count,
            spatial_group_count=group_count,
            available_algorithms=["random_forest_spatial"],
            confirmation_required=True,
            reason_code="ML_EXPERIMENTAL_DATASET",
            message="样本规模有限，仅建议将随机森林作为实验性对照。",
        )
    reason = "ML_DATASET_TOO_SMALL" if sample_count < 80 else "ML_SPATIAL_GROUPS_INSUFFICIENT"
    return MLCapability(
        level="not_recommended",
        valid_sample_count=sample_count,
        spatial_group_count=group_count,
        available_algorithms=[],
        confirmation_required=False,
        reason_code=reason,
        message="样本量或独立空间分组不足，不建议运行机器学习空间预测。",
    )

