"""SQLite v8 migration test: ai_analysis_records table."""

from __future__ import annotations

from pathlib import Path

import pytest

from geomodeling.platform import PlatformRuntime
from geomodeling.platform.db import SCHEMA_VERSION
from geomodeling.platform.tables import AIAnalysisRecord
from sqlalchemy import inspect


def test_fresh_db_has_ai_analysis_records(tmp_path):
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    with runtime.session() as session:
        inspector = inspect(session.bind)
        assert inspector.has_table("ai_analysis_records")
    assert SCHEMA_VERSION == 8


def test_v7_to_v8_migration(tmp_path):
    """Create a v7 database, then verify migration to v8."""
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()

    # Stamp to v7, then re-initialize to trigger migration
    with runtime.engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA user_version=7")
        # Drop the v8 table to simulate pre-migration state
        conn.exec_driver_sql("DROP TABLE IF EXISTS ai_analysis_records")

    runtime.close()
    runtime2 = PlatformRuntime(tmp_path / "runtime")
    runtime2.initialize()

    with runtime2.session() as session:
        inspector = inspect(session.bind)
        assert inspector.has_table("ai_analysis_records")
        assert SCHEMA_VERSION == 8

    # Verify the table has expected columns
    with runtime2.session() as session:
        inspector = inspect(session.bind)
        columns = {c["name"] for c in inspector.get_columns("ai_analysis_records")}
        assert "id" in columns
        assert "result_id" in columns
        assert "grid_sha256" in columns
        assert "evidence_hash" in columns
        assert "prompt_version" in columns
        assert "review_json" in columns
        assert "error_code" in columns
        assert "usage_prompt_tokens" in columns
        assert "latency_ms" in columns
