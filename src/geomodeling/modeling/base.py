"""Shared interpolator protocol for the generic modeling engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

import numpy as np
from pydantic import BaseModel

from geomodeling.platform.schemas import Algorithm, Dimension

CancelFn = Callable[[], bool]


@dataclass(frozen=True)
class PredictionBatch:
    """一块预测输出：数值、NoData 掩膜与诊断信息。"""

    values: np.ndarray
    is_nodata: np.ndarray
    diagnostics: dict[str, Any] = field(default_factory=dict)


class FittedInterpolator(Protocol):
    def predict(self, query: np.ndarray, *, cancel: CancelFn) -> PredictionBatch: ...


class Interpolator(Protocol):
    algorithm: Algorithm

    def validate_parameters(self, parameters: dict[str, Any], dimension: Dimension | str) -> BaseModel: ...

    def fit(
        self,
        coordinates: np.ndarray,
        values: np.ndarray,
        parameters: BaseModel,
    ) -> FittedInterpolator: ...
