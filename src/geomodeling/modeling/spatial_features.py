"""Deterministic coordinate-only features for spatial machine learning."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

FEATURE_VERSION = "spatial_features.v1"


def _coordinates(value: np.ndarray) -> np.ndarray:
    coordinates = np.asarray(value, dtype="float64")
    if coordinates.ndim != 2 or coordinates.shape[1] not in (2, 3):
        raise ValueError("空间坐标必须是 (n, 2) 或 (n, 3) 数组")
    if coordinates.shape[0] == 0:
        raise ValueError("空间坐标不能为空")
    if not np.isfinite(coordinates).all():
        raise ValueError("空间坐标必须全部为有限数值")
    return coordinates


@dataclass(frozen=True)
class SpatialFeatureTransform:
    center: np.ndarray
    scale: np.ndarray
    feature_names: tuple[str, ...]
    version: str = FEATURE_VERSION

    @classmethod
    def fit(cls, coordinates: np.ndarray) -> "SpatialFeatureTransform":
        points = _coordinates(coordinates)
        center = points.mean(axis=0)
        scale = points.max(axis=0) - points.min(axis=0)
        scale = np.where(scale > 0, scale, 1.0)
        names = (
            ("x", "y", "radius", "xy", "x2", "y2")
            if points.shape[1] == 2
            else ("x", "y", "z", "radius", "xy", "xz", "yz", "x2", "y2", "z2")
        )
        return cls(center=center, scale=scale, feature_names=names)

    def transform(self, coordinates: np.ndarray) -> np.ndarray:
        points = _coordinates(coordinates)
        if points.shape[1] != len(self.center):
            raise ValueError("查询坐标维度与训练坐标不一致")
        normalized = (points - self.center) / self.scale
        radius = np.linalg.norm(normalized, axis=1, keepdims=True)
        x = normalized[:, 0:1]
        y = normalized[:, 1:2]
        if normalized.shape[1] == 2:
            features = np.hstack((x, y, radius, x * y, x * x, y * y))
        else:
            z = normalized[:, 2:3]
            features = np.hstack(
                (x, y, z, radius, x * y, x * z, y * z, x * x, y * y, z * z)
            )
        if not np.isfinite(features).all():
            raise ValueError("空间特征包含非有限值")
        return features

