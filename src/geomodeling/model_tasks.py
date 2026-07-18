from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AppConfig
from .io import read_json, write_json
from .schemas import MetricSummary, ModelSelection, ModelStatus, ModelTask, SuperMapResultRegistration
from .supermap import select_supermap_result_for_model


SAFE_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _enum_value(value):
    return getattr(value, "value", value)


def task_fingerprint(
    model_id: str,
    display_name: str,
    method: str,
    input_dataset_id: str,
    input_sha256: str,
    parameters: dict[str, Any],
    config_snapshot: dict[str, Any],
) -> str:
    payload = {
        "model_id": model_id,
        "display_name": display_name,
        "method": method,
        "input_dataset_id": input_dataset_id,
        "input_sha256": input_sha256,
        "parameters": parameters,
        "config_snapshot": config_snapshot,
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ModelTaskRegistry:
    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, model_id: str) -> Path:
        if not SAFE_MODEL_ID_RE.fullmatch(model_id):
            raise ValueError(f"unsafe model_id: {model_id}")
        base = self.base_dir.resolve()
        path = (base / f"{model_id}.json").resolve()
        if path.parent != base:
            raise ValueError(f"unsafe model_id path: {model_id}")
        return path

    def get(self, model_id: str) -> ModelTask | None:
        path = self.path_for(model_id)
        if not path.exists():
            return None
        return ModelTask.model_validate(read_json(path))

    def create(self, task: ModelTask) -> ModelTask:
        if self.path_for(task.model_id).exists():
            raise ValueError(f"duplicate model_id: {task.model_id}")
        write_json(self.path_for(task.model_id), task)
        return task

    def ensure(self, task: ModelTask) -> tuple[ModelTask, bool]:
        existing = self.get(task.model_id)
        if existing is None:
            write_json(self.path_for(task.model_id), task)
            return task, True
        if existing.fingerprint != task.fingerprint:
            raise ValueError(f"model_id already exists with different configuration: {task.model_id}")
        if _enum_value(existing.status) != _enum_value(task.status):
            updated = existing.model_copy(update={"status": task.status, "updated_at": datetime.now(timezone.utc)})
            write_json(self.path_for(task.model_id), updated)
            return updated, False
        return existing, False

    def list(self) -> list[ModelTask]:
        return [
            ModelTask.model_validate(read_json(path))
            for path in sorted(self.base_dir.glob("*.json"))
            if not path.name.startswith("_")
        ]

    def save_selection(self, selection: ModelSelection) -> Path:
        return write_json(self.base_dir / "_selection.json", selection)


def build_model_task(
    model_id: str,
    display_name: str,
    method: str,
    input_dataset_id: str,
    input_sha256: str,
    parameters: dict[str, Any],
    config_snapshot: dict[str, Any],
    role: str = "candidate",
    status: ModelStatus = ModelStatus.CREATED,
) -> ModelTask:
    fingerprint = task_fingerprint(model_id, display_name, method, input_dataset_id, input_sha256, parameters, config_snapshot)
    return ModelTask(
        model_id=model_id,
        display_name=display_name,
        method=method,
        input_dataset_id=input_dataset_id,
        input_sha256=input_sha256,
        parameters=parameters,
        config_snapshot=config_snapshot,
        status=status,
        role=role,
        fingerprint=fingerprint,
    )


def task_from_config_model(
    model: dict[str, Any],
    input_dataset_id: str,
    input_sha256: str,
    supermap_records: list[SuperMapResultRegistration] | None = None,
) -> ModelTask:
    parameters = dict(model.get("parameters", {}))
    parameters.update(
        {
            "resolution_xy_m": model.get("resolution_xy_m"),
            "neighbor_count": model.get("neighbor_count"),
        }
    )
    status = ModelStatus.CREATED
    if supermap_records is not None:
        selected = select_supermap_result_for_model(supermap_records, model["model_id"])
        if selected is not None and _enum_value(selected.status) == ModelStatus.SUCCEEDED.value:
            status = ModelStatus.SUCCEEDED
    return build_model_task(
        model_id=model["model_id"],
        display_name=model["display_name"],
        method=model["method"],
        input_dataset_id=input_dataset_id,
        input_sha256=input_sha256,
        parameters=parameters,
        config_snapshot=model,
        role=model.get("role", "candidate"),
        status=status,
    )


def ensure_config_model_tasks(
    config: AppConfig,
    registry: ModelTaskRegistry,
    input_dataset_id: str,
    input_sha256: str,
    supermap_records: list[SuperMapResultRegistration] | None = None,
) -> list[ModelTask]:
    tasks = []
    for model in config.models:
        task = task_from_config_model(model, input_dataset_id, input_sha256, supermap_records)
        ensured, _ = registry.ensure(task)
        tasks.append(ensured)
    return tasks


def select_models(
    tasks: list[ModelTask],
    summaries: dict[str, MetricSummary] | None = None,
    default_model_id: str | None = None,
    comparison_model_id: str | None = None,
) -> ModelSelection:
    if not tasks:
        raise ValueError("no model tasks available for selection")
    by_id = {task.model_id: task for task in tasks}
    default = by_id.get(default_model_id) if default_model_id else next((task for task in tasks if task.role == "default"), None)
    comparison = by_id.get(comparison_model_id) if comparison_model_id else next((task for task in tasks if task.role == "comparison"), None)
    if default_model_id and default is None:
        raise ValueError(f"unknown default_model_id: {default_model_id}")
    if comparison_model_id and comparison is None:
        raise ValueError(f"unknown comparison_model_id: {comparison_model_id}")
    best_mae = None
    best_rmse = None
    if summaries:
        best_mae = min(summaries.values(), key=lambda item: item.mae).model
        best_rmse = min(summaries.values(), key=lambda item: item.rmse).model
    if default is None and summaries:
        default = next(task for task in tasks if task.display_name == best_mae)
    if comparison is None and summaries:
        comparison = next(task for task in tasks if task.display_name == best_rmse)
    if default is None or comparison is None:
        raise ValueError("default and comparison models must be configured or derivable from metric summaries")
    rationale = (
        f"default={default.display_name} (role={default.role}); comparison={comparison.display_name} (role={comparison.role}); "
        f"best_mae={best_mae}; best_rmse={best_rmse}; single_overall_winner={best_mae == best_rmse if best_mae and best_rmse else 'unknown'}; "
        f"user_default_override={default_model_id is not None}; user_comparison_override={comparison_model_id is not None}"
    )
    return ModelSelection(default_model_id=default.model_id, comparison_model_id=comparison.model_id, rationale=rationale)
