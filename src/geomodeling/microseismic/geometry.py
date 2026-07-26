from __future__ import annotations

from .config import MicroseismicConfig
from .schemas import SourceFileManifestEntry, SurveyLine, SurveyPoint

INTERVAL_SOURCE = "点间距.xlsx"
ORDER_SOURCE = "config formal point order (paper survey line description)"


def build_survey_geometry(
    config: MicroseismicConfig,
    manifest: list[SourceFileManifestEntry],
) -> tuple[list[SurveyLine], list[SurveyPoint]]:
    counts = {
        entry.point_id: (entry.source_record_count, entry.valid_numeric_count) for entry in manifest
    }
    interval_lookup = config.interval_lookup()
    coordinates = config.coordinate_lookup()
    interval_workbook = config.source.get("interval_workbook", INTERVAL_SOURCE)
    lines: list[SurveyLine] = []
    points: list[SurveyPoint] = []
    for line in config.lines:
        cumulative = 0.0
        previous_id: str | None = None
        for sequence, point in enumerate(line.points, start=1):
            interval = None
            if previous_id is not None:
                spec = interval_lookup.get((previous_id, point.point_id))
                if spec is not None:
                    interval = spec.distance_m
                    cumulative += spec.distance_m
            source_records, valid_numeric = counts.get(point.point_id, (0, 0))
            xy = coordinates.get(point.point_id)
            note_parts = []
            if interval is None and previous_id is not None:
                note_parts.append("interval to previous point not registered")
            if xy is not None:
                note_parts.append(
                    "local engineering coordinates confirmed from versioned config "
                    "(local_engineering_m); no EPSG declared"
                )
            points.append(
                SurveyPoint(
                    point_id=point.point_id,
                    original_point_label=point.point_id,
                    source_file_id=f"microseismic_dat_{point.point_id}",
                    line_id=line.line_id,
                    sequence_on_line=sequence,
                    previous_point_id=previous_id,
                    interval_from_previous_m=interval,
                    cumulative_s_m=cumulative,
                    interval_source=interval_workbook if interval is not None else None,
                    order_source=ORDER_SOURCE,
                    included_in_formal_set=True,
                    exclusion_reason=None,
                    source_record_count=source_records,
                    valid_numeric_count=valid_numeric,
                    coordinate_status="confirmed_local" if xy is not None else "unconfirmed",
                    x_local_m=xy[0] if xy is not None else None,
                    y_local_m=xy[1] if xy is not None else None,
                    z_reference_status="unconfirmed",
                    source_confidence=(
                        "interval_source_confirmed; local_coordinates_confirmed; absolute_geometry_unconfirmed"
                        if xy is not None
                        else "interval_source_confirmed; absolute_geometry_unconfirmed"
                    ),
                    notes="; ".join(note_parts) or None,
                )
            )
            previous_id = point.point_id
        line_records = sum(counts.get(point.point_id, (0, 0))[0] for point in line.points)
        line_valid = sum(counts.get(point.point_id, (0, 0))[1] for point in line.points)
        lines.append(
            SurveyLine(
                line_id=line.line_id,
                point_start=line.point_start,
                point_end=line.point_end,
                formal_point_count=len(line.points),
                source_record_count=line_records,
                valid_numeric_count=line_valid,
                geometry_status="cumulative_1d_only",
                crs_type="none",
                origin_status="confirmed_local",
                direction_status="confirmed_local",
                geometry_source=(
                    f"point intervals from {interval_workbook}; order from {ORDER_SOURCE}; "
                    "local coordinates from config local_coordinates"
                ),
                source_confidence="interval_source_confirmed; local_origin_and_direction_confirmed; absolute_crs_unconfirmed",
                notes=(
                    "2D local engineering coordinates confirmed from versioned config "
                    "(local_engineering_m); absolute CRS/EPSG unavailable"
                ),
            )
        )
    for excluded in config.excluded_points:
        points.append(
            SurveyPoint(
                point_id=excluded.point_id,
                original_point_label=excluded.point_id,
                source_file_id="",
                line_id=excluded.line_id,
                sequence_on_line=None,
                previous_point_id=excluded.interval_from,
                interval_from_previous_m=excluded.conflict_interval_m,
                cumulative_s_m=None,
                interval_source=interval_workbook if excluded.conflict_interval_m is not None else None,
                order_source="conflict registration only",
                included_in_formal_set=False,
                exclusion_reason=excluded.reason,
                source_record_count=0,
                valid_numeric_count=0,
                coordinate_status="unconfirmed",
                x_local_m=None,
                y_local_m=None,
                z_reference_status="unconfirmed",
                source_confidence="conflict_only",
                notes=f"issue_code={excluded.issue_code}; excluded from formal cumulative distance",
            )
        )
    return lines, points
