"""SQLAlchemy table definitions for the v0.4 platform database.

Conventions follow the v0.3 codebase: statuses are plain enum strings,
structured fields are stored as canonical JSON text
(``json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"))``),
and timestamps are UTC ISO-8601 strings.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def dumps_canonical(value: Any) -> str:
    """Serialize structured fields to canonical JSON text.

    Python's ``json`` defaults to ``allow_nan=True``, which emits ``NaN`` /
    ``Infinity`` literals that are invalid strict JSON. Callers (run metrics,
    quality reports, manifests, ...) must sanitize non-finite floats before
    persisting; this helper intentionally does not mask bad input.
    """

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def loads_canonical(raw: str) -> Any:
    return json.loads(raw)


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    INTERRUPTED = "interrupted"


RUN_INFLIGHT_STATUSES = frozenset({RunStatus.QUEUED.value, RunStatus.RUNNING.value})
RUN_TERMINAL_STATUSES = frozenset(
    {RunStatus.SUCCEEDED.value, RunStatus.FAILED.value, RunStatus.CANCELED.value}
)

ERROR_PROCESS_RESTARTED = "PROCESS_RESTARTED"


class Base(DeclarativeBase):
    pass


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    case_type: Mapped[str] = mapped_column(String(64))
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(Text, default=utc_now_iso)
    updated_at: Mapped[str] = mapped_column(Text, default=utc_now_iso, onupdate=utc_now_iso)


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    version: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(String(32), default="uploaded")
    source_path: Mapped[str] = mapped_column(Text)
    standardized_path: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    profile_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(Text, default=utc_now_iso)


class QualityReport(Base):
    __tablename__ = "quality_reports"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    dataset_version_id: Mapped[str] = mapped_column(ForeignKey("dataset_versions.id"))
    status: Mapped[str] = mapped_column(String(32), default="unreviewed")
    report_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(Text, default=utc_now_iso)


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    name: Mapped[str] = mapped_column(String(256))
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(Text, default=utc_now_iso)
    updated_at: Mapped[str] = mapped_column(Text, default=utc_now_iso, onupdate=utc_now_iso)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"))
    status: Mapped[str] = mapped_column(String(32), default=RunStatus.QUEUED.value)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    retry_of_run_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("runs.id"), nullable=True, default=None
    )
    metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(Text, default=utc_now_iso)
    updated_at: Mapped[str] = mapped_column(Text, default=utc_now_iso, onupdate=utc_now_iso)
    started_at: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    finished_at: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)


class CandidateResult(Base):
    __tablename__ = "candidate_results"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    category: Mapped[str] = mapped_column(String(32), default="preview")
    grid_path: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(Text, default=utc_now_iso)


class FormalSelection(Base):
    __tablename__ = "formal_selections"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    candidate_result_id: Mapped[str] = mapped_column(ForeignKey("candidate_results.id"))
    selected_by: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(Text, default=utc_now_iso)


class Export(Base):
    __tablename__ = "exports"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    package_path: Mapped[str] = mapped_column(Text)
    manifest_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(Text, default=utc_now_iso)


class Publication(Base):
    __tablename__ = "publications"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    export_id: Mapped[str] = mapped_column(ForeignKey("exports.id"))
    target: Mapped[str] = mapped_column(String(64), default="iserver")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(Text, default=utc_now_iso)
    updated_at: Mapped[str] = mapped_column(Text, default=utc_now_iso, onupdate=utc_now_iso)
