from __future__ import annotations

from pathlib import Path
from typing import Any

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


class MicroseismicConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: dict[str, Any]
    source: dict[str, Any]
    lines: list[LineSpec]
    intervals_m: dict[str, list[IntervalSpec]]
    excluded_points: list[ExcludedPointSpec] = Field(default_factory=list)
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
