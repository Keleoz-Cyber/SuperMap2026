"""Shared dataclasses for the generic modeling engine (v0.4 M2)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class GridDefinition:
    """规则网格定义：节点坐标轴、形状与单元数（2D/3D 共用）。"""

    dimension: str
    axes: tuple[np.ndarray, ...]
    bounds: tuple[tuple[float, float], ...]
    resolution: tuple[float, ...]

    @property
    def shape(self) -> tuple[int, ...]:
        return tuple(len(axis) for axis in self.axes)

    @property
    def cell_count(self) -> int:
        count = 1
        for axis in self.axes:
            count *= len(axis)
        return count


@dataclass(frozen=True)
class Fold:
    """空间折分的一折：训练/验证索引（行号，0 基）。"""

    index: int
    training_indices: np.ndarray
    validation_indices: np.ndarray


@dataclass(frozen=True)
class MetricSummary:
    """公共有效集合上的指标复算结果。"""

    n_total: int
    n_valid: int
    n_nodata: int
    coverage: float
    mae: float
    rmse: float
    r2: float
    bias: float
