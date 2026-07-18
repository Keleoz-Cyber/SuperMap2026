from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: dict[str, Any]
    paths: dict[str, Any]
    expected: dict[str, int | float]
    nodata_value: float
    metric_tolerance: float
    models: list[dict[str, Any]]
    supermap: dict[str, Any]
    outputs: dict[str, str]

    def resolve_path(self, value: str | None) -> Path | None:
        if value is None:
            return None
        path = Path(value)
        if path.is_absolute():
            return path
        return (PROJECT_ROOT / path).resolve()

    def prediction_files(self) -> dict[str, Path]:
        files = self.paths.get("prediction_files", {})
        return {name: self.resolve_path(path) for name, path in files.items()}

    def output_dir(self, key: str) -> Path:
        value = self.outputs[key]
        path = Path(value)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        path.mkdir(parents=True, exist_ok=True)
        return path.resolve()


def load_config(config_path: str | Path | None = None) -> AppConfig:
    if config_path is None:
        path = PROJECT_ROOT / "config" / "default.yaml"
    else:
        path = Path(config_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return AppConfig.model_validate(data)
