"""Atomic import of microseismic DAT bundles into the generic platform.

The full v0.5 derivation (audit contract + 3σ + golden gate + aggregation)
runs in a per-import staging directory first. Only when every gate passes do
we create the dataset row (``pending://microseismic``), build the immutable
``datasets/<case>/<dataset>`` tree beside a temporary sibling, and atomically
rename it into place before registering source/profile and transitioning
``uploaded → mapped``.

Compensation removes the database row, the formal directory and the staging
directory independently; each cleanup step logs its own failure and the
original business exception is always the one that propagates.
"""

from __future__ import annotations

import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from geomodeling.platform import tables
from geomodeling.platform.db import PlatformRuntime
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.ingest import STANDARDIZED_SCHEMA, write_standardized_frame
from geomodeling.platform.repositories import CaseRepository, DatasetRepository
from geomodeling.platform.schemas import (
    CaseCreateRequest,
    CaseRecord,
    DatasetStatus,
    DatasetVersionRecord,
    Dimension,
    FieldMapping,
)

from .config import MicroseismicConfig
from .reports import export_manifest
from .service import MicroseismicDerivationResult, derive_from_directory

logger = logging.getLogger("geomodeling.microseismic.platform_adapter")

MICROSEISMIC_DERIVATION_FAILED = "MICROSEISMIC_DERIVATION_FAILED"
MICROSEISMIC_DUPLICATE_COORDINATES = "MICROSEISMIC_DUPLICATE_COORDINATES"

PENDING_SOURCE_PATH = "pending://microseismic"
SOURCE_KIND = "microseismic_dat_bundle"
DEFAULT_CASE_NAME = "微震速度建模"

# 微震导入的字段映射由派生合同固定，不经用户选择。
MAPPING = FieldMapping(
    dimension=Dimension.THREE_D,
    x="X_LOCAL_M",
    y="Y_LOCAL_M",
    z="Z_LOCAL_M",
    value="VX_KM_S",
    value_name="Vx",
    value_unit="km/s",
    coordinate_kind="local_linear",
)


@dataclass(frozen=True)
class MicroseismicImportBundle:
    """One DAT directory plus the confirmed microseismic contract config."""

    config: MicroseismicConfig
    source_dir: Path


def create_microseismic_case(runtime: PlatformRuntime, name: str = DEFAULT_CASE_NAME) -> CaseRecord:
    with runtime.session() as session:
        return CaseRepository(session).create(CaseCreateRequest(name=name, case_type="microseismic"))


def _standardized_frame(result: MicroseismicDerivationResult) -> pd.DataFrame:
    """Map the unique modeling nodes onto the generic STANDARDIZED_SCHEMA.

    ``source_row`` is the 1-based first-appearance order of each node in the
    accepted golden table — identical to modeling_provenance.parquet.
    """

    nodes = result.aggregated.nodes
    frame = pd.DataFrame(
        {
            "source_row": pd.RangeIndex(start=1, stop=len(nodes) + 1, step=1),
            "x": [node.x_local_m for node in nodes],
            "y": [node.y_local_m for node in nodes],
            "z": [node.z_local_m for node in nodes],
            "value": [node.vx_km_s for node in nodes],
        }
    )
    numeric_block = frame[["x", "y", "z", "value"]].to_numpy(dtype="float64", na_value=np.nan)
    frame["is_numeric_valid"] = np.isfinite(numeric_block).all(axis=1)
    frame = frame[STANDARDIZED_SCHEMA]
    if frame.duplicated(["x", "y", "z"]).any():
        raise PlatformError(
            MICROSEISMIC_DUPLICATE_COORDINATES,
            "聚合后的建模节点仍存在同坐标不同属性，禁止入库",
            {"node_count": len(nodes)},
            http_status=422,
        )
    return frame


def _replace_directory(tmp_dir: Path, final_dir: Path) -> None:
    """Atomically move the fully built sibling tree into the final location."""

    os.replace(tmp_dir, final_dir)


def _rmtree_missing_ok(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        pass


def _prune_empty_parents(path: Path, stop: Path) -> None:
    """Remove now-empty parent directories up to (excluding) ``stop``."""

    current = path
    while current != stop and stop in current.parents:
        try:
            current.rmdir()  # 仅在空目录时成功
        except OSError:
            return
        current = current.parent


def _build_dataset_tree(
    tmp_dir: Path,
    bundle: MicroseismicImportBundle,
    result: MicroseismicDerivationResult,
    outputs: dict[str, Path],
    frame: pd.DataFrame,
) -> dict[str, Any]:
    """Populate source/ + derived/ + standardized.parquet under ``tmp_dir``."""

    source_dir = tmp_dir / "source"
    source_dir.mkdir(parents=True)
    for entry in result.audit.manifest:
        shutil.copy2(bundle.source_dir / entry.file_name, source_dir / entry.file_name)
    export_manifest(result.audit.manifest, source_dir / "source_manifest.json")

    derived_dir = tmp_dir / "derived"
    derived_dir.mkdir()
    for artifact in outputs.values():
        shutil.copy2(artifact, derived_dir / artifact.name)

    return write_standardized_frame(tmp_dir / "standardized.parquet", frame)


def _build_profile(result: MicroseismicDerivationResult, summary: dict[str, Any]) -> dict[str, Any]:
    filtered = result.filtered
    aggregated = result.aggregated
    return {
        "source_kind": SOURCE_KIND,
        "dimension": MAPPING.dimension,
        "mapping": MAPPING.model_dump(mode="json"),
        "rule_version": result.rule_version,
        "adapter_version": result.adapter_version,
        "aggregation_method": result.aggregation_method,
        "golden": {
            "passed": result.golden.passed,
            "checks": [check.model_dump(mode="json") for check in result.golden.checks],
        },
        "layer_counts": {
            "source_records": len(result.audit.samples),
            "finite_records": len(result.finite),
            "invalid_records": len(result.invalid),
            "rejected_3sigma": len(filtered.rejected),
            "accepted_modeling": len(filtered.accepted),
            "aggregated_nodes": len(aggregated.nodes),
        },
        "aggregation": {
            "conflict_group_count": aggregated.conflict_group_count,
            "conflict_row_count": aggregated.conflict_row_count,
            "collapsed_row_count": aggregated.collapsed_row_count,
            "max_value_range": aggregated.max_value_range,
        },
        "source_files": [
            {
                "file_name": entry.file_name,
                "sha256": entry.sha256,
                "point_id": entry.point_id,
                "line_id": entry.line_id,
                "source_record_count": entry.source_record_count,
            }
            for entry in result.audit.manifest
        ],
        "derivation_report": "derived/derivation_report.json",
        "modeling_provenance": "derived/modeling_provenance.parquet",
        "row_count": summary["row_count"],
        "valid_row_count": summary["valid_row_count"],
        "invalid_row_count": summary["invalid_row_count"],
        "standardized_path": summary["standardized_path"],
        "standardized_sha256": summary["standardized_sha256"],
    }


def _update_dataset_record(
    runtime: PlatformRuntime,
    dataset_id: str,
    *,
    source_path: Path,
    standardized_path: Path,
    profile: dict[str, Any],
) -> DatasetVersionRecord:
    """Register the finalized artifacts and transition ``uploaded → mapped``."""

    with runtime.session() as session:
        row = session.get(tables.DatasetVersion, dataset_id)
        row.source_path = str(source_path)
        row.standardized_path = str(standardized_path)
        row.profile_json = tables.dumps_canonical(profile)
        session.commit()
        return DatasetRepository(session).transition_status(dataset_id, DatasetStatus.MAPPED)


def import_microseismic_dataset(
    runtime: PlatformRuntime,
    case_id: str,
    bundle: MicroseismicImportBundle,
) -> DatasetVersionRecord:
    """Import one DAT bundle as a mapped platform dataset version.

    A failed gate never creates a dataset row; a failure after row creation
    compensates the row, the formal directory and the staging directory in
    independent steps. Cleanup failures are logged (with stack) and never
    mask the original business exception.
    """

    settings = runtime.settings
    staging = settings.microseismic_staging_dir() / uuid.uuid4().hex
    staging.mkdir(parents=True, exist_ok=False)
    created_dataset_id: str | None = None
    tmp_dir: Path | None = None
    final_dir: Path | None = None
    try:
        result, outputs = derive_from_directory(bundle.config, bundle.source_dir, staging)
        if not result.validation.passed:
            failed = [
                {"name": check.name, "evidence": check.evidence}
                for check in result.validation.checks
                if not check.passed
            ]
            raise PlatformError(
                MICROSEISMIC_DERIVATION_FAILED,
                f"微震派生合同或黄金门禁未通过（{len(failed)} 项失败），导入已阻断",
                {"failed_checks": failed},
                http_status=422,
            )
        frame = _standardized_frame(result)

        with runtime.session() as session:
            record = DatasetRepository(session).create_version(case_id, source_path=PENDING_SOURCE_PATH)
        created_dataset_id = record.id

        final_dir = settings.microseismic_dataset_dir(case_id, record.id)
        tmp_dir = final_dir.with_name(f"{final_dir.name}.tmp-{uuid.uuid4().hex[:12]}")
        summary = _build_dataset_tree(tmp_dir, bundle, result, outputs, frame)
        _replace_directory(tmp_dir, final_dir)
        tmp_dir = None  # 重命名成功后临时目录已不存在

        # 重命名只改目录身份，字节与哈希不变；登记时以正式路径为准。
        summary["standardized_path"] = str(final_dir / "standardized.parquet")
        profile = _build_profile(result, summary)
        return _update_dataset_record(
            runtime,
            record.id,
            source_path=final_dir / "source" / "source_manifest.json",
            standardized_path=final_dir / "standardized.parquet",
            profile=profile,
        )
    except BaseException:
        # 补偿事务：数据库行、正式目录、临时兄弟目录各自独立清理；
        # 清理失败只记日志（含堆栈），绝不允许覆盖最初的业务异常。
        if created_dataset_id is not None:
            try:
                with runtime.session() as session:
                    row = session.get(tables.DatasetVersion, created_dataset_id)
                    if row is not None:
                        session.delete(row)
                        session.commit()
            except Exception:  # noqa: BLE001
                logger.exception(
                    "microseismic import compensation: row delete failed for %s", created_dataset_id
                )
        if final_dir is not None:
            try:
                _rmtree_missing_ok(final_dir)
                _prune_empty_parents(final_dir.parent, settings.datasets_dir)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "microseismic import compensation: formal directory cleanup failed: %s", final_dir
                )
        if tmp_dir is not None:
            try:
                _rmtree_missing_ok(tmp_dir)
                _prune_empty_parents(tmp_dir.parent, settings.datasets_dir)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "microseismic import compensation: temporary directory cleanup failed: %s", tmp_dir
                )
        raise
    finally:
        try:
            _rmtree_missing_ok(staging)
        except Exception:  # noqa: BLE001
            logger.exception("microseismic import: staging cleanup failed: %s", staging)
