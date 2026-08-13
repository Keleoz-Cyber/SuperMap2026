from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from geomodeling.runtime_paths import resource_root

PROJECT_ROOT = resource_root()

logger = logging.getLogger(__name__)


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: dict[str, Any]
    paths: dict[str, Any]
    expected: dict[str, int | float]
    nodata_value: float
    metric_tolerance: float
    models: list[dict[str, Any]]
    supermap: dict[str, Any]
    views: list[dict[str, Any]] = Field(default_factory=list)
    outputs: dict[str, str]

    def resolve_path(self, value: str | None) -> Path | None:
        if value is None:
            return None
        path = Path(value)
        if path.is_absolute():
            return path
        candidate = (PROJECT_ROOT / path).resolve()
        if candidate.exists():
            return candidate
        # Worktrees are nested below the real project root. Resolve legacy
        # "../超图杯资料" paths by searching ancestor roots as well.
        parts = list(path.parts)
        while parts and parts[0] == "..":
            parts.pop(0)
        if parts:
            relative = Path(*parts)
            for root in (PROJECT_ROOT, *PROJECT_ROOT.parents):
                fallback = (root / relative).resolve()
                if fallback.exists():
                    logger.info(
                        "配置路径 %s 经上级目录解析为 %s（项目根下不存在）",
                        value,
                        fallback,
                    )
                    return fallback
        logger.warning(
            "配置路径不存在：%s（已尝试 %s 及以下上级目录：%s）",
            candidate,
            PROJECT_ROOT,
            [str(root) for root in PROJECT_ROOT.parents],
        )
        return candidate

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
