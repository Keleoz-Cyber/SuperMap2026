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
    """公共有效集合上的指标复算结果。

    计数口径自洽分离：``common_valid_count`` 是公共掩膜内 truth 与
    prediction 均为有限值的点数（所有候选指标的计算口径）；
    ``candidate_valid_count``/``candidate_nodata_count`` 是候选自身
    有效/NoData 点数（覆盖率口径），二者之和恒等于 ``total_count``；
    ``coverage = candidate_valid_count / total_count``。
    ``truth_excluded_count``/``prediction_excluded_count`` 披露公共掩膜内
    因 truth/prediction 非有限（NaN/inf）而被排除的点数——非有限值绝不
    进入指标，排除数量显式可见；全有限输入时两计数恒为零。
    """

    common_valid_count: int
    candidate_valid_count: int
    candidate_nodata_count: int
    total_count: int
    coverage: float
    mae: float
    rmse: float
    r2: float
    bias: float
    truth_excluded_count: int = 0
    prediction_excluded_count: int = 0
