"""Resumable data preparation state resolver (v0.7.0 batch 3 §6).

Determines the authoritative resume state from persisted DatasetVersion rows
and file integrity checks. The resolver never trusts browser data; all file
paths and hashes are validated server-side.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Literal

from geomodeling.platform.errors import (
    DATA_PREPARATION_CORRUPT,
    DATASET_ABANDON_FORBIDDEN,
    PlatformError,
)
from geomodeling.platform.schemas import (
    ContractModel,
    DatasetStatus,
    DatasetVersionRecord,
)
from geomodeling.platform.tables import loads_canonical


class DataPreparationNextAction(ContractModel):
    step: Literal["upload", "mapping", "quality_review", "experiment", "repair"]
    label: str
    url: str | None = None


class DataPreparationSummary(ContractModel):
    state: Literal[
        "needs_upload", "needs_mapping", "needs_quality_review", "ready", "blocked"
    ]
    dataset_id: str | None = None
    latest_validated_dataset_id: str | None = None
    next_action: DataPreparationNextAction
    error: dict[str, str] | None = None


def _validate_file_hash(path: Path, expected_sha256: str) -> bool:
    """Check if file exists and matches expected SHA-256."""
    if not path.exists() or not path.is_file():
        return False
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest() == expected_sha256


def resolve_data_preparation(
    runtime: Any, case_id: str, datasets: list[DatasetVersionRecord],
) -> DataPreparationSummary:
    """Resolve the authoritative resume state from persisted datasets.

    State logic:
    - No datasets -> needs_upload / upload
    - Latest incomplete uploaded -> needs_mapping / mapping
    - Latest incomplete mapped -> needs_quality_review / quality_review
    - Latest incomplete quality-blocked -> needs_mapping / mapping
    - Only validated -> ready / experiment
    - Missing/hash-mismatched file -> blocked / repair
    - Unknown status -> blocked / repair
    """

    non_abandoned = [d for d in datasets if d.status != DatasetStatus.ABANDONED.value]
    validated = [d for d in non_abandoned if d.status == DatasetStatus.VALIDATED.value]
    incomplete = [d for d in non_abandoned if d.status != DatasetStatus.VALIDATED.value]

    latest_validated = validated[-1] if validated else None

    if not non_abandoned:
        return DataPreparationSummary(
            state="needs_upload",
            dataset_id=None,
            latest_validated_dataset_id=None,
            next_action=DataPreparationNextAction(
                step="upload",
                label="上传数据",
                url=f"/#/cases/{case_id}/datasets/new",
            ),
        )

    if not incomplete:
        return DataPreparationSummary(
            state="ready",
            dataset_id=None,
            latest_validated_dataset_id=latest_validated.id if latest_validated else None,
            next_action=DataPreparationNextAction(
                step="experiment",
                label="新建实验",
                url=f"/#/cases/{case_id}/experiments/new"
                if latest_validated
                else None,
            ),
        )

    latest_incomplete = incomplete[-1]

    if latest_incomplete.status == DatasetStatus.UPLOADED.value:
        if not _validate_dataset_file(runtime, latest_incomplete, source_only=True):
            return _blocked_summary(case_id, latest_incomplete.id, latest_validated)
        return DataPreparationSummary(
            state="needs_mapping",
            dataset_id=latest_incomplete.id,
            latest_validated_dataset_id=latest_validated.id if latest_validated else None,
            next_action=DataPreparationNextAction(
                step="mapping",
                label="继续字段映射",
                url=f"/#/cases/{case_id}/datasets/{latest_incomplete.id}/prepare",
            ),
        )

    if latest_incomplete.status == DatasetStatus.MAPPED.value:
        if not _validate_dataset_file(runtime, latest_incomplete, source_only=False):
            return _blocked_summary(case_id, latest_incomplete.id, latest_validated)
        return DataPreparationSummary(
            state="needs_quality_review",
            dataset_id=latest_incomplete.id,
            latest_validated_dataset_id=latest_validated.id if latest_validated else None,
            next_action=DataPreparationNextAction(
                step="quality_review",
                label="继续质量检查",
                url=f"/#/cases/{case_id}/datasets/{latest_incomplete.id}/prepare",
            ),
        )

    if latest_incomplete.status == DatasetStatus.BLOCKED.value:
        if not _validate_dataset_file(runtime, latest_incomplete, source_only=False):
            return _blocked_summary(case_id, latest_incomplete.id, latest_validated)
        return DataPreparationSummary(
            state="needs_mapping",
            dataset_id=latest_incomplete.id,
            latest_validated_dataset_id=latest_validated.id if latest_validated else None,
            next_action=DataPreparationNextAction(
                step="mapping",
                label="修正字段映射",
                url=f"/#/cases/{case_id}/datasets/{latest_incomplete.id}/prepare",
            ),
        )

    return _blocked_summary(case_id, latest_incomplete.id, latest_validated)


def _validate_dataset_file(
    runtime: Any, dataset: DatasetVersionRecord, *, source_only: bool,
) -> bool:
    """Validate source file ownership/root and SHA-256."""
    profile = dataset.profile or {}
    source_sha = profile.get("source_sha256", "")
    source_path = Path(dataset.source_path)

    try:
        resolved = source_path.resolve(strict=True)
        uploads_root = runtime.settings.uploads_dir.resolve()
        if not str(resolved).startswith(str(uploads_root)):
            return False
    except (OSError, RuntimeError):
        return False

    if source_sha and not _validate_file_hash(source_path, source_sha):
        return False

    if not source_only and dataset.standardized_path:
        std_sha = profile.get("standardized_sha256", "")
        std_path = Path(dataset.standardized_path)
        try:
            resolved = std_path.resolve(strict=True)
            datasets_root = runtime.settings.datasets_dir.resolve()
            if not str(resolved).startswith(str(datasets_root)):
                return False
        except (OSError, RuntimeError):
            return False
        if std_sha and not _validate_file_hash(std_path, std_sha):
            return False

    return True


def _blocked_summary(
    case_id: str, dataset_id: str, latest_validated: Any,
) -> DataPreparationSummary:
    return DataPreparationSummary(
        state="blocked",
        dataset_id=dataset_id,
        latest_validated_dataset_id=latest_validated.id if latest_validated else None,
        next_action=DataPreparationNextAction(
            step="repair",
            label="数据文件异常，需修复",
            url=None,
        ),
        error={"code": DATA_PREPARATION_CORRUPT, "dataset_id": dataset_id},
    )
