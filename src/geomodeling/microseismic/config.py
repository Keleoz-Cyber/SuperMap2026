from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class PointSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    point_id: str
    source_file: str


class LineSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_id: str
    point_start: str
    point_end: str
    points: list[PointSpec]


class IntervalSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_point: str = Field(alias="from")
    to_point: str = Field(alias="to")
    distance_m: float = Field(gt=0)


class ExcludedPointSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    point_id: str
    line_id: str
    conflict_interval_m: float | None = None
    interval_from: str | None = None
    reason: str
    issue_code: str


class LocalCoordinateSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    point_id: str
    x_local_m: float
    y_local_m: float


class GoldenSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rejected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DerivationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_version: str
    adapter_version: str
    depth_multiplier: float = 1000.0
    z_multiplier: float = -1.0
    vx_unit: str = "km/s"
    sigma_threshold: float = 3.0
    sigma_ddof: int = 1
    aggregation_method: Literal["arithmetic_mean_exact_xyz"]
    expected_rejected: int
    expected_accepted: int
    expected_conflict_groups: int
    expected_conflict_rows: int
    expected_modeling_nodes: int
    golden: GoldenSpec


class MicroseismicConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: dict[str, Any]
    source: dict[str, Any]
    lines: list[LineSpec]
    intervals_m: dict[str, list[IntervalSpec]]
    excluded_points: list[ExcludedPointSpec] = Field(default_factory=list)
    local_coordinates: list[LocalCoordinateSpec]
    derivation: DerivationSpec
    expected: dict[str, Any]
    cleaning_conflicts: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, str] = Field(default_factory=dict)

    def resolve_path(self, value: str | None) -> Path | None:
        if value is None:
            return None
        path = Path(value)
        if path.is_absolute():
            return path
        return (PROJECT_ROOT / path).resolve()

    @property
    def data_dir(self) -> Path:
        return self.resolve_path(self.source["data_dir"])

    def default_output_dir(self) -> Path:
        value = self.outputs.get("default_dir", "outputs/microseismic_v0.2a")
        path = Path(value)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path.resolve()

    def formal_points(self) -> list[tuple[LineSpec, PointSpec]]:
        return [(line, point) for line in self.lines for point in line.points]

    def formal_point_ids(self) -> list[str]:
        return [point.point_id for _, point in self.formal_points()]

    def expected_file_names(self) -> list[str]:
        return [point.source_file for _, point in self.formal_points()]

    def interval_lookup(self) -> dict[tuple[str, str], IntervalSpec]:
        lookup: dict[tuple[str, str], IntervalSpec] = {}
        for intervals in self.intervals_m.values():
            for interval in intervals:
                lookup[(interval.from_point, interval.to_point)] = interval
        return lookup

    def coordinate_lookup(self) -> dict[str, tuple[float, float]]:
        return {
            item.point_id: (item.x_local_m, item.y_local_m)
            for item in self.local_coordinates
        }

    def with_data_dir(self, data_dir: Path) -> "MicroseismicConfig":
        source = dict(self.source)
        source["data_dir"] = str(data_dir.resolve())
        return self.model_copy(update={"source": source})


def load_microseismic_config(config_path: str | Path | None = None) -> MicroseismicConfig:
    if config_path is None:
        path = PROJECT_ROOT / "config" / "microseismic.yaml"
    else:
        path = Path(config_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return MicroseismicConfig.model_validate(data)
