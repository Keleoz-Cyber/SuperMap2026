"""Generic 2D/3D modeling engine (v0.4 M2): grids, splits, interpolators, metrics."""

from geomodeling.modeling.contracts import Fold, GridDefinition, MetricSummary
from geomodeling.modeling.grid import derive_grid
from geomodeling.modeling.metrics import common_valid_mask, compute_metrics
from geomodeling.modeling.splits import build_spatial_splits

__all__ = [
    "Fold",
    "GridDefinition",
    "MetricSummary",
    "build_spatial_splits",
    "common_valid_mask",
    "compute_metrics",
    "derive_grid",
]
