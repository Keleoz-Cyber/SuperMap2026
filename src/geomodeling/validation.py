from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .io import read_csv, sha256_file
from .schemas import (
    DatasetRegistration,
    DatasetType,
    IssueSeverity,
    QualityStatus,
    ValidationIssue,
    ValidationReport,
)

REQUIRED_COLUMNS = ["X", "Y", "Z", "RHO"]


def column_id(x: float, y: float) -> str:
    return f"X{x:g}_Y{y:g}"


def summarize_xyzrho(df: pd.DataFrame) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    for column in REQUIRED_COLUMNS:
        if column in df.columns:
            series = pd.to_numeric(df[column], errors="coerce")
            stats[column] = {
                "min": float(series.min()) if series.notna().any() else None,
                "max": float(series.max()) if series.notna().any() else None,
                "unique_count": int(series.nunique(dropna=True)),
                "null_count": int(series.isna().sum()),
            }
    if all(column in df.columns for column in ["X", "Y", "Z"]):
        stats["duplicate_xyz_count"] = int(df.duplicated(["X", "Y", "Z"]).sum())
        stats["spatial_column_count"] = int(df[["X", "Y"]].drop_duplicates().shape[0])
    return stats


def validate_xyzrho_contract(
    path: str | Path,
    dataset_id: str,
    dataset_type: DatasetType = DatasetType.STANDARDIZED_OBSERVATION,
    expected_row_count: int | None = None,
) -> ValidationReport:
    source_path = str(Path(path))
    issues: list[ValidationIssue] = []
    checks: dict[str, Any] = {}
    statistics: dict[str, Any] = {}
    try:
        df = read_csv(path)
    except Exception as exc:
        issues.append(
            ValidationIssue(
                severity=IssueSeverity.BLOCKER,
                code="READ_FAILED",
                message="input CSV cannot be read",
                evidence=str(exc),
                blocking=True,
            )
        )
        return ValidationReport(
            dataset_id=dataset_id,
            source_path=source_path,
            dataset_type=dataset_type,
            row_count=0,
            expected_row_count=expected_row_count,
            quality_status=QualityStatus.FAILED,
            checks={"readable": False},
            statistics={},
            issues=issues,
        )

    row_count = int(len(df))
    checks["readable"] = True
    missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    checks["required_fields_present"] = not missing
    if missing:
        issues.append(
            ValidationIssue(
                severity=IssueSeverity.BLOCKER,
                code="MISSING_FIELDS",
                message="required fields are missing",
                evidence=",".join(missing),
                blocking=True,
            )
        )
    else:
        numeric = df[REQUIRED_COLUMNS].apply(pd.to_numeric, errors="coerce")
        finite_mask = np.isfinite(numeric.to_numpy(dtype=float))
        invalid_numeric = int((~finite_mask).sum())
        checks["finite_values"] = invalid_numeric == 0
        checks["invalid_numeric_cells"] = invalid_numeric
        if invalid_numeric:
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.BLOCKER,
                    code="NON_FINITE_VALUES",
                    message="required fields contain empty, text, NaN, or infinite values",
                    evidence=str(invalid_numeric),
                    blocking=True,
                )
            )
        rho = numeric["RHO"]
        invalid_rho = int(((rho <= 0) | (rho == -9999)).sum())
        checks["rho_positive"] = invalid_rho == 0
        checks["invalid_rho_count"] = invalid_rho
        if invalid_rho:
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.BLOCKER,
                    code="INVALID_RHO",
                    message="RHO must be finite, greater than 0, and not equal to -9999",
                    evidence=str(invalid_rho),
                    blocking=True,
                )
            )
        duplicate_xyz = int(numeric.duplicated(["X", "Y", "Z"]).sum())
        checks["duplicate_xyz_count"] = duplicate_xyz
        if duplicate_xyz:
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.WARNING,
                    code="DUPLICATE_XYZ",
                    message="duplicate X,Y,Z records exist",
                    evidence=str(duplicate_xyz),
                    blocking=False,
                    current_handling="reported only; input file is not modified",
                )
            )
        statistics = summarize_xyzrho(numeric)

    if expected_row_count is not None:
        matches = row_count == expected_row_count
        checks["row_count_matches_expected"] = matches
        if not matches:
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    code="ROW_COUNT_MISMATCH",
                    message="row count differs from registered expectation",
                    evidence=f"actual={row_count}, expected={expected_row_count}",
                    blocking=True,
                )
            )

    if any(issue.blocking and issue.severity in {IssueSeverity.ERROR, IssueSeverity.BLOCKER} for issue in issues):
        quality = QualityStatus.FAILED
    elif issues:
        quality = QualityStatus.WARNING
    else:
        quality = QualityStatus.PASSED

    return ValidationReport(
        dataset_id=dataset_id,
        source_path=source_path,
        dataset_type=dataset_type,
        row_count=row_count,
        expected_row_count=expected_row_count,
        quality_status=quality,
        checks=checks,
        statistics=statistics,
        issues=issues,
    )


def validate_train_validation_split(training_path: str | Path, validation_path: str | Path) -> dict[str, Any]:
    training = read_csv(training_path)[["X", "Y"]].apply(pd.to_numeric, errors="coerce")
    validation = read_csv(validation_path)[["X", "Y"]].apply(pd.to_numeric, errors="coerce")
    training_columns = {column_id(row.X, row.Y) for row in training.drop_duplicates().itertuples(index=False)}
    validation_columns = {column_id(row.X, row.Y) for row in validation.drop_duplicates().itertuples(index=False)}
    overlap = sorted(training_columns & validation_columns)
    return {
        "training_column_count": len(training_columns),
        "validation_column_count": len(validation_columns),
        "spatial_column_overlap": len(overlap),
        "overlap_columns": overlap,
        "passed": len(overlap) == 0,
    }


def registration_from_report(
    report: ValidationReport,
    path: str | Path,
    created_by: str,
    source_reference: str,
    version: str = "0.1",
) -> DatasetRegistration:
    return DatasetRegistration(
        dataset_id=report.dataset_id,
        dataset_type=report.dataset_type,
        version=version,
        source_path=str(Path(path)),
        sha256=sha256_file(path),
        row_count=report.row_count,
        created_by=created_by,
        source_reference=source_reference,
        quality_status=report.quality_status,
        notes="registered by GeoModelingPlatform MVP",
        statistics=report.statistics,
    )
