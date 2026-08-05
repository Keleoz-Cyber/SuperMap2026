"""v4→v5 migration: literal v4 fixture, metadata-backed creation, invariants.

A real v4-shaped database copy is built with literal DDL (the exact v4
schema), then migrated by starting the current runtime. The migration must
create the five professional tables, preserve every existing v4 row, stay
idempotent, and keep rejecting databases newer than the code.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from geomodeling.platform import PlatformRuntime
from geomodeling.platform.tables import CandidateResult

NEW_V5_TABLES = (
    "professional_diagnostics",
    "professional_confirmations",
    "professional_result_artifacts",
    "anomaly_extractions",
    "analysis_jobs",
)

V4_TABLES = (
    "cases",
    "dataset_versions",
    "quality_reports",
    "experiments",
    "runs",
    "candidate_results",
    "formal_selections",
    "exports",
    "publications",
)

# 字面 v4 schema：与 v4 发布时 SQLAlchemy metadata 生成的 DDL 逐字一致。
V4_DDL = """
CREATE TABLE cases (
    id VARCHAR(128) NOT NULL,
    name VARCHAR(256) NOT NULL,
    case_type VARCHAR(64) NOT NULL,
    config_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (id)
);
CREATE TABLE dataset_versions (
    id VARCHAR(128) NOT NULL,
    case_id VARCHAR(128) NOT NULL,
    version INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL,
    source_path TEXT NOT NULL,
    standardized_path TEXT,
    profile_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_dataset_versions_case_version UNIQUE (case_id, version),
    FOREIGN KEY(case_id) REFERENCES cases (id)
);
CREATE TABLE experiments (
    id VARCHAR(128) NOT NULL,
    case_id VARCHAR(128) NOT NULL,
    name VARCHAR(256) NOT NULL,
    params_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(case_id) REFERENCES cases (id)
);
CREATE TABLE quality_reports (
    id VARCHAR(128) NOT NULL,
    dataset_version_id VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(dataset_version_id) REFERENCES dataset_versions (id)
);
CREATE TABLE runs (
    id VARCHAR(128) NOT NULL,
    experiment_id VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL,
    error_code VARCHAR(64),
    retry_of_run_id VARCHAR(128),
    metrics_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    PRIMARY KEY (id),
    FOREIGN KEY(experiment_id) REFERENCES experiments (id),
    FOREIGN KEY(retry_of_run_id) REFERENCES runs (id)
);
CREATE UNIQUE INDEX ux_runs_experiment_inflight ON runs (experiment_id)
    WHERE status IN ('queued', 'running');
CREATE TABLE candidate_results (
    id VARCHAR(128) NOT NULL,
    run_id VARCHAR(128) NOT NULL,
    category VARCHAR(32) NOT NULL,
    fingerprint VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    params_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    error_json TEXT,
    predictions_path TEXT,
    grid_path TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(run_id) REFERENCES runs (id)
);
CREATE TABLE exports (
    id VARCHAR(128) NOT NULL,
    case_id VARCHAR(128) NOT NULL,
    candidate_result_id VARCHAR(128),
    package_path TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(case_id) REFERENCES cases (id),
    FOREIGN KEY(candidate_result_id) REFERENCES candidate_results (id)
);
CREATE TABLE formal_selections (
    id VARCHAR(128) NOT NULL,
    case_id VARCHAR(128) NOT NULL,
    candidate_result_id VARCHAR(128) NOT NULL,
    selected_by VARCHAR(128),
    note TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(case_id) REFERENCES cases (id),
    FOREIGN KEY(candidate_result_id) REFERENCES candidate_results (id)
);
CREATE TABLE publications (
    id VARCHAR(128) NOT NULL,
    export_id VARCHAR(128) NOT NULL,
    target VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    detail_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(export_id) REFERENCES exports (id)
);
"""

_TS = "2026-07-26T00:00:00+00:00"

# 每张 v4 表一行代表性数据，迁移后必须逐字节保留。
V4_ROWS = f"""
INSERT INTO cases (id, name, case_type, config_json, created_at, updated_at)
VALUES ('case-1', '演示案例', 'generic', '{{}}', '{_TS}', '{_TS}');
INSERT INTO dataset_versions
    (id, case_id, version, status, source_path, standardized_path, profile_json, created_at)
VALUES ('ds-1', 'case-1', 1, 'validated', 'uploads/case-1/ds-1/source.csv',
        'datasets/case-1/ds-1/standardized.parquet', '{{}}', '{_TS}');
INSERT INTO quality_reports (id, dataset_version_id, status, report_json, created_at)
VALUES ('qr-1', 'ds-1', 'reviewed', '{{"verdict":"ok"}}', '{_TS}');
INSERT INTO experiments (id, case_id, name, params_json, created_at, updated_at)
VALUES ('exp-1', 'case-1', '实验一', '{{"algorithm":"idw"}}', '{_TS}', '{_TS}');
INSERT INTO runs
    (id, experiment_id, status, error_code, retry_of_run_id, metrics_json,
     created_at, updated_at, started_at, finished_at)
VALUES ('run-1', 'exp-1', 'succeeded', NULL, NULL, '{{"rmse":0.5}}',
        '{_TS}', '{_TS}', '{_TS}', '{_TS}');
INSERT INTO candidate_results
    (id, run_id, category, fingerprint, status, params_json, metrics_json,
     error_json, predictions_path, grid_path, created_at)
VALUES ('cand-1', 'run-1', 'formal', 'fp-cand-1', 'succeeded', '{{"power":2.0}}',
        '{{"rmse":0.5}}', NULL, 'results/cand-1/predictions.parquet',
        'results/cand-1/grid.npz', '{_TS}');
INSERT INTO formal_selections (id, case_id, candidate_result_id, selected_by, note, created_at)
VALUES ('sel-1', 'case-1', 'cand-1', 'op', '公共有效集最优', '{_TS}');
INSERT INTO exports (id, case_id, candidate_result_id, package_path, manifest_json, created_at)
VALUES ('export-1', 'case-1', 'cand-1', 'exports/export-1/result-package.zip', '{{}}', '{_TS}');
INSERT INTO publications (id, export_id, target, status, detail_json, created_at, updated_at)
VALUES ('pub-1', 'export-1', 'iserver', 'pending', '{{}}', '{_TS}', '{_TS}');
"""


def build_v4_fixture(db_path: Path) -> None:
    """Create a literal v4 database with one representative row per table."""

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(V4_DDL)
    conn.executescript(V4_ROWS)
    conn.execute("PRAGMA user_version=4")
    conn.commit()
    conn.close()


def table_fingerprint(db_path: Path, table: str) -> dict:
    """(column, type, notnull, pk) + index signatures for schema comparison."""

    raw = sqlite3.connect(db_path)
    try:
        columns = [
            (row[1], row[2], row[3], row[5])
            for row in raw.execute(f"PRAGMA table_info('{table}')")
        ]
        indexes = {}
        for row in raw.execute(f"PRAGMA index_list('{table}')"):
            name, unique = row[1], row[2]
            cols = [r[2] for r in raw.execute(f"PRAGMA index_info('{name}')")]
            where = raw.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (name,)
            ).fetchone()[0]
            indexes[name] = (unique, tuple(cols), where)
        return {"columns": columns, "indexes": indexes}
    finally:
        raw.close()


def test_v4_to_v5_migration_creates_professional_tables_and_preserves_rows(tmp_path):
    db_path = tmp_path / "runtime" / "platform.sqlite3"
    build_v4_fixture(db_path)

    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()

    # v4 夹具沿迁移链逐版本升到当前 schema（v6 起经 v5→v6 步骤）。
    assert runtime.schema_version() == 6
    with runtime.session() as session:
        existing_candidate = session.get(CandidateResult, "cand-1")
        assert existing_candidate is not None
        assert existing_candidate.status == "succeeded"
        assert existing_candidate.fingerprint == "fp-cand-1"
        assert existing_candidate.grid_path == "results/cand-1/grid.npz"
    with runtime.engine.connect() as conn:
        inspector = inspect(conn)
        for table in NEW_V5_TABLES:
            assert inspector.has_table(table), f"missing v5 table {table}"

    # 绝不重建或清空既有 v4 行：每张表仍恰好一行，关键载荷原样保留。
    raw = sqlite3.connect(db_path)
    try:
        for table in V4_TABLES:
            count = raw.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert count == 1, f"{table} row count changed during migration"
        assert raw.execute("SELECT status FROM runs WHERE id='run-1'").fetchone()[0] == "succeeded"
        assert raw.execute(
            "SELECT candidate_result_id FROM exports WHERE id='export-1'"
        ).fetchone()[0] == "cand-1"
        assert raw.execute("SELECT note FROM formal_selections WHERE id='sel-1'").fetchone()[0] == (
            "公共有效集最优"
        )
    finally:
        raw.close()
    runtime.close()


def test_migrated_v5_schema_matches_fresh_database(tmp_path):
    """迁移产物与全新 v5 库的表结构（列、约束、索引）必须完全一致。"""

    build_v4_fixture(tmp_path / "runtime" / "platform.sqlite3")
    migrated = PlatformRuntime(tmp_path / "runtime")
    migrated.initialize()
    migrated.close()

    fresh = PlatformRuntime(tmp_path / "fresh")
    fresh.initialize()
    fresh.close()

    for table in NEW_V5_TABLES:
        assert table_fingerprint(tmp_path / "runtime" / "platform.sqlite3", table) == (
            table_fingerprint(tmp_path / "fresh" / "platform.sqlite3", table)
        ), f"migrated schema of {table} diverges from a fresh v5 database"


def test_v5_initialize_is_idempotent_and_never_recreates_rows(tmp_path):
    build_v4_fixture(tmp_path / "runtime" / "platform.sqlite3")
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    runtime.close()

    # 二次启动不再执行迁移，v4 旧行保持原样。
    reopened = PlatformRuntime(tmp_path / "runtime")
    reopened.initialize()
    reopened.initialize()  # 同一实例重复 initialize 同样幂等
    assert reopened.schema_version() == 6
    with reopened.engine.connect() as conn:
        inspector = inspect(conn)
        assert all(inspector.has_table(t) for t in NEW_V5_TABLES)
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM candidate_results").scalar_one() == 1
        assert conn.exec_driver_sql(
            "SELECT status FROM candidate_results WHERE id='cand-1'"
        ).scalar_one() == "succeeded"
    reopened.close()


def test_initialize_rejects_schema_newer_than_v6(tmp_path):
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    runtime.close()
    with sqlite3.connect(runtime.db_path) as conn:
        conn.execute("PRAGMA user_version = 7")

    with pytest.raises(RuntimeError, match="newer than code"):
        PlatformRuntime(tmp_path / "runtime").initialize()


def test_v5_tables_enforce_foreign_keys(tmp_path):
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()

    with runtime.engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        # 合法外键链：dataset→diagnostic→confirmation，run→candidate→artifacts/anomaly。
        conn.exec_driver_sql(
            "INSERT INTO cases (id, name, case_type, config_json, created_at, updated_at) "
            "VALUES ('c1', 'c', 'generic', '{}', 't', 't')"
        )
        conn.exec_driver_sql(
            "INSERT INTO dataset_versions (id, case_id, version, status, source_path, "
            "profile_json, created_at) VALUES ('d1', 'c1', 1, 'validated', 'u/x.csv', '{}', 't')"
        )
        conn.exec_driver_sql(
            "INSERT INTO experiments (id, case_id, name, params_json, created_at, updated_at) "
            "VALUES ('e1', 'c1', 'e', '{}', 't', 't')"
        )
        conn.exec_driver_sql(
            "INSERT INTO runs (id, experiment_id, status, metrics_json, created_at, updated_at) "
            "VALUES ('r1', 'e1', 'succeeded', '{}', 't', 't')"
        )
        conn.exec_driver_sql(
            "INSERT INTO candidate_results "
            "(id, run_id, category, fingerprint, status, params_json, metrics_json, created_at) "
            "VALUES ('cand1', 'r1', 'formal', 'fp', 'succeeded', '{}', '{}', 't')"
        )
        conn.exec_driver_sql(
            "INSERT INTO professional_diagnostics "
            "(id, dataset_version_id, status, config_json, fingerprint, manifest_json, "
            "created_at, updated_at) VALUES ('pd1', 'd1', 'succeeded', '{}', 'fp', '{}', 't', 't')"
        )
        conn.exec_driver_sql(
            "INSERT INTO professional_confirmations "
            "(id, diagnostic_id, config_json, fingerprint, note, created_at) "
            "VALUES ('pc1', 'pd1', '{}', 'fp2', '确认', 't')"
        )
        # 合法引用成立：confirmation_id 可空，指向既有确认时入库成功。
        conn.exec_driver_sql(
            "INSERT INTO professional_result_artifacts "
            "(id, candidate_result_id, confirmation_id, status, capabilities_json, "
            "manifest_json, created_at) VALUES ('pa1', 'cand1', 'pc1', 'pending', '{}', '{}', 't')"
        )
        conn.exec_driver_sql(
            "INSERT INTO anomaly_extractions "
            "(id, candidate_result_id, status, config_json, fingerprint, manifest_json, "
            "created_at) VALUES ('ax0', 'cand1', 'pending', '{}', 'f', '{}', 't')"
        )
        conn.commit()
        ghost_inserts = [
            # 诊断必须挂在既有数据版本上
            "INSERT INTO professional_diagnostics "
            "(id, dataset_version_id, status, config_json, fingerprint, manifest_json, "
            "created_at, updated_at) VALUES ('pdX', 'ghost', 'queued', '{}', 'f', '{}', 't', 't')",
            # 确认必须挂在既有诊断上
            "INSERT INTO professional_confirmations "
            "(id, diagnostic_id, config_json, fingerprint, note, created_at) "
            "VALUES ('pcX', 'ghost', '{}', 'f', 'n', 't')",
            # 专业工件必须挂在既有候选上
            "INSERT INTO professional_result_artifacts "
            "(id, candidate_result_id, confirmation_id, status, capabilities_json, "
            "manifest_json, created_at) VALUES ('paX', 'ghost', NULL, 'pending', '{}', '{}', 't')",
            # confirmation_id 可空，但非空时必须指向既有确认
            "INSERT INTO professional_result_artifacts "
            "(id, candidate_result_id, confirmation_id, status, capabilities_json, "
            "manifest_json, created_at) VALUES ('paY', 'cand1', 'ghost', 'pending', '{}', '{}', 't')",
            # 异常提取必须挂在既有候选上
            "INSERT INTO anomaly_extractions "
            "(id, candidate_result_id, status, config_json, fingerprint, manifest_json, "
            "created_at) VALUES ('ax1', 'ghost', 'pending', '{}', 'f', '{}', 't')",
            # 重试来源必须指向既有分析任务
            "INSERT INTO analysis_jobs "
            "(id, job_kind, subject_type, subject_id, request_fingerprint, status, "
            "retry_of_job_id, progress_json, created_at, updated_at) "
            "VALUES ('aj1', 'professional_diagnosis', 'professional_diagnostic', 'pd1', 'f', "
            "'queued', 'ghost', '{}', 't', 't')",
        ]
        for statement in ghost_inserts:
            with pytest.raises(IntegrityError):
                conn.exec_driver_sql(statement)
            conn.rollback()
    runtime.close()


def test_analysis_job_inflight_partial_unique_index(tmp_path):
    """同一 job_kind + subject_id 同时最多一个 queued/running，终态不占名额。"""

    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()

    insert = (
        "INSERT INTO analysis_jobs "
        "(id, job_kind, subject_type, subject_id, request_fingerprint, status, "
        "progress_json, created_at, updated_at) "
        "VALUES ('{id}', '{kind}', 'professional_diagnostic', '{subject}', 'fp', "
        "'{status}', '{{}}', 't', 't')"
    )

    def add(conn, job_id, kind="professional_diagnosis", subject="pd1", status="queued"):
        conn.exec_driver_sql(insert.format(id=job_id, kind=kind, subject=subject, status=status))

    with runtime.engine.connect() as conn:
        index_names = {
            row[1] for row in conn.exec_driver_sql("PRAGMA index_list('analysis_jobs')")
        }
        assert "ux_analysis_jobs_subject_inflight" in index_names

        add(conn, "j1")  # queued 占在途名额
        conn.commit()
        with pytest.raises(IntegrityError):
            add(conn, "j2", status="running")
        conn.rollback()
        with pytest.raises(IntegrityError):
            add(conn, "j3")
        conn.rollback()
        # 终态不触发部分唯一索引
        add(conn, "j4", status="canceled")
        add(conn, "j5", status="interrupted")
        # 不同 job_kind 或不同 subject 各自占独立名额
        add(conn, "j6", kind="anomaly_extraction")
        add(conn, "j7", subject="pd2")
        conn.commit()
    runtime.close()
