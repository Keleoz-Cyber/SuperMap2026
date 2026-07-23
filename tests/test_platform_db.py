"""Portable tests for the v0.4 platform runtime and SQLite persistence.

Everything runs against tmp_path; no real data directories, UDBX, S3M caches,
or iServer endpoints are touched.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from geomodeling.platform import PlatformRuntime, PlatformSettings
from geomodeling.platform import db as platform_db
from geomodeling.platform.settings import DEFAULT_DATA_DIR, ENV_DATA_DIR
from geomodeling.platform.tables import (
    ERROR_PROCESS_RESTARTED,
    RUN_INFLIGHT_STATUSES,
    RUN_TERMINAL_STATUSES,
    Case,
    Experiment,
    Run,
    dumps_canonical,
    loads_canonical,
)

EXPECTED_TABLES = {
    "cases",
    "dataset_versions",
    "quality_reports",
    "experiments",
    "runs",
    "candidate_results",
    "formal_selections",
    "exports",
    "publications",
}


def initialized_runtime(tmp_path: Path) -> PlatformRuntime:
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    return runtime


def insert_run(
    runtime: PlatformRuntime,
    status: str = "queued",
    run_id: str | None = None,
    case_id: str = "case-1",
    experiment_id: str = "exp-1",
) -> str:
    run_id = run_id or f"run-{status}"
    with runtime.session() as session:
        if session.get(Case, case_id) is None:
            session.add(Case(id=case_id, name=case_id, case_type="resistivity"))
        if session.get(Experiment, experiment_id) is None:
            session.add(Experiment(id=experiment_id, case_id=case_id, name=experiment_id))
        session.add(Run(id=run_id, experiment_id=experiment_id, status=status))
        session.commit()
    return run_id


def load_run(runtime: PlatformRuntime, run_id: str) -> Run:
    with runtime.session() as session:
        run = session.get(Run, run_id)
        assert run is not None, f"run {run_id} not persisted"
        session.expunge(run)
        return run


def test_database_creates_schema_and_is_reopenable(tmp_path):
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    assert runtime.db_path.is_file()
    assert runtime.schema_version() == 1
    runtime.close()
    PlatformRuntime(tmp_path / "runtime").initialize()


def test_startup_marks_inflight_runs_interrupted(tmp_path):
    runtime = initialized_runtime(tmp_path)
    run_id = insert_run(runtime, status="running")
    runtime.recover_interrupted_runs()
    assert load_run(runtime, run_id).status == "interrupted"


def test_interrupted_run_records_error_code_and_terminal_runs_survive(tmp_path):
    runtime = initialized_runtime(tmp_path)
    for status in sorted(RUN_INFLIGHT_STATUSES):
        insert_run(runtime, status=status)
    for status in sorted(RUN_TERMINAL_STATUSES):
        insert_run(runtime, status=status)

    runtime.recover_interrupted_runs()

    for status in RUN_INFLIGHT_STATUSES:
        recovered = load_run(runtime, f"run-{status}")
        assert recovered.status == "interrupted"
        assert recovered.error_code == ERROR_PROCESS_RESTARTED
    for status in RUN_TERMINAL_STATUSES:
        untouched = load_run(runtime, f"run-{status}")
        assert untouched.status == status
        assert untouched.error_code is None


def test_all_expected_tables_exist_with_foreign_keys(tmp_path):
    runtime = initialized_runtime(tmp_path)
    with runtime.engine.connect() as conn:
        assert set(inspect(conn).get_table_names()) == EXPECTED_TABLES
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() == 30000


def test_settings_resolve_env_override_and_default_layout(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_DATA_DIR, raising=False)
    assert PlatformSettings.resolve().data_dir == Path(DEFAULT_DATA_DIR)

    monkeypatch.setenv(ENV_DATA_DIR, str(tmp_path / "custom"))
    settings = PlatformSettings.resolve()
    assert settings.data_dir == tmp_path / "custom"
    assert settings.db_path == tmp_path / "custom" / "platform.sqlite3"
    assert (
        settings.upload_source("caseA", "ds1", "csv")
        == tmp_path / "custom" / "uploads" / "caseA" / "ds1" / "source.csv"
    )
    assert (
        settings.upload_source("caseA", "ds1", "xlsx")
        == tmp_path / "custom" / "uploads" / "caseA" / "ds1" / "source.xlsx"
    )
    assert (
        settings.standardized_dataset("caseA", "ds1")
        == tmp_path / "custom" / "datasets" / "caseA" / "ds1" / "standardized.parquet"
    )
    assert settings.experiment_dir("exp9") == tmp_path / "custom" / "experiments" / "exp9"
    assert settings.result_grid("res7") == tmp_path / "custom" / "results" / "res7" / "grid.npz"
    assert (
        settings.export_package("exp3")
        == tmp_path / "custom" / "exports" / "exp3" / "result-package.zip"
    )


def test_structured_fields_roundtrip_as_canonical_json(tmp_path):
    runtime = initialized_runtime(tmp_path)
    run_id = insert_run(runtime, status="succeeded")
    payload = {"rmse": 0.42, "params": {"b": 2, "a": 1}, "label": "中文标签"}

    with runtime.session() as session:
        run = session.get(Run, run_id)
        run.metrics_json = dumps_canonical(payload)
        session.commit()

    with runtime.engine.connect() as conn:
        raw = conn.execute(
            text("SELECT metrics_json FROM runs WHERE id = :run_id"), {"run_id": run_id}
        ).scalar_one()
    assert raw == json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert loads_canonical(raw) == payload


def test_recover_interrupted_runs_returns_count_and_is_idempotent(tmp_path):
    runtime = initialized_runtime(tmp_path)
    insert_run(runtime, status="queued")
    insert_run(runtime, status="running")
    insert_run(runtime, status="succeeded")

    assert runtime.recover_interrupted_runs() == 2
    assert runtime.recover_interrupted_runs() == 0


def test_repeated_initialize_on_same_instance_is_idempotent(tmp_path):
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    runtime.initialize()

    assert runtime.db_path.is_file()
    assert runtime.schema_version() == 1
    with runtime.engine.connect() as conn:
        assert set(inspect(conn).get_table_names()) == EXPECTED_TABLES


def test_operations_after_close_raise_runtime_error(tmp_path):
    runtime = initialized_runtime(tmp_path)
    runtime.close()

    with pytest.raises(RuntimeError, match="not initialized"):
        with runtime.session():
            pass
    with pytest.raises(RuntimeError, match="not initialized"):
        runtime.schema_version()


def test_initialize_rejects_schema_older_than_code(tmp_path, monkeypatch):
    runtime = initialized_runtime(tmp_path)
    runtime.close()

    monkeypatch.setattr(platform_db, "SCHEMA_VERSION", platform_db.SCHEMA_VERSION + 1)
    with pytest.raises(RuntimeError, match="migration"):
        PlatformRuntime(tmp_path / "runtime").initialize()

    # failed initialize leaves the file untouched: v1 still opens cleanly
    monkeypatch.undo()
    reopened = PlatformRuntime(tmp_path / "runtime")
    reopened.initialize()
    assert reopened.schema_version() == 1


def test_initialize_rejects_schema_newer_than_code(tmp_path):
    runtime = initialized_runtime(tmp_path)
    runtime.close()
    with sqlite3.connect(runtime.db_path) as conn:
        conn.execute(f"PRAGMA user_version = {platform_db.SCHEMA_VERSION + 1}")

    with pytest.raises(RuntimeError, match="newer than code"):
        PlatformRuntime(tmp_path / "runtime").initialize()
