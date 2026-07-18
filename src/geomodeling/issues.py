from __future__ import annotations

from .config import AppConfig
from .schemas import IssueSeverity, ValidationIssue


def current_issues(config: AppConfig) -> list[ValidationIssue]:
    return [
        ValidationIssue(
            severity=IssueSeverity.WARNING,
            code="RHO_UNIT_PENDING",
            message="RHO physical unit is pending source confirmation",
            scope="all resistivity displays and exports",
            evidence="data contract marks property_unit=null and UI text as unit pending source confirmation",
            blocking=False,
            current_handling="display as resistivity with unit pending source confirmation",
        ),
        ValidationIssue(
            severity=IssueSeverity.WARNING,
            code="LOCAL_CRS_EPSG_UNCONFIRMED",
            message="CRS is local engineering coordinates and EPSG is not confirmed",
            scope="all coordinates and SuperMap registration metadata",
            evidence="crs.type=local_engineering, crs.epsg=null",
            blocking=False,
            current_handling="do not attach an unverified EPSG code",
        ),
        ValidationIssue(
            severity=IssueSeverity.WARNING,
            code="VERTICAL_SLICE_UNVERIFIED",
            message="vertical slice configuration is reserved but not verified",
            scope="3D view configuration",
            evidence="SuperMap known issues record vertical slicing as not yet formally reproducible",
            blocking=False,
            current_handling="keep vertical_slice_status=unverified",
        ),
        ValidationIssue(
            severity=IssueSeverity.ERROR,
            code="NATIVE_ISOSURFACE_FAILED",
            message="native isosurface extraction failed and produced empty datasets",
            scope="RHO_ISO_77_K40 and RHO_ISO_HIGH_P95_K40",
            evidence="Failed to extract continuous surface, please check IsoValue.",
            blocking=True,
            current_handling="register as failed/failed_empty/object_count=0 and exclude from formal results",
        ),
        ValidationIssue(
            severity=IssueSeverity.WARNING,
            code="SUPERMAP_DATASET_VERIFICATION_BOUNDARY",
            message="SuperMap dataset-level verification is not claimed without a supported API adapter",
            scope="SuperMap result evidence",
            evidence=f"dataset_api={config.supermap.get('dataset_api', 'none')}",
            blocking=False,
            current_handling="use declared/file_verified/manual_evidence unless a supported dataset API adapter is added",
        ),
    ]
