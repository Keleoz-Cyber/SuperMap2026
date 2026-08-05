"""v5→v6 migration: literal v5 fixture, render_assets creation, invariants.

A real v5-shaped database copy is built with literal DDL (the exact v4
schema from the v5 migration fixture plus the five v5 professional tables),
then migrated by starting the current runtime. The migration must create
``render_assets``, preserve every existing v5 row, stay idempotent, and keep
rejecting databases newer than the code.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from geomodeling.platform import PlatformRuntime
from geomodeling.platform.tables import CandidateResult

from test_schema_v5_migration import V4_DDL, table_fingerprint

# 字面 v5 schema：v4 DDL（逐字复用 v5 迁移夹具）+ v5 五张专业建模表，
# 与 v5 发布时 SQLAlchemy metadata 生成的 DDL 逐字一致。
V5_EXTRA_DDL = """
CREATE TABLE professional_diagnostics (
    id VARCHAR(128) NOT NULL,
    dataset_version_id VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL,
    config_json TEXT NOT NULL,
    fingerprint VARCHAR(64) NOT NULL,
    manifest_json TEXT NOT NULL,
    error_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    PRIMARY KEY (id),
    FOREIGN KEY(dataset_version_id) REFERENCES dataset_versions (id)
);
CREATE TABLE professional_confirmations (
    id VARCHAR(128) NOT NULL,
    diagnostic_id VARCHAR(128) NOT NULL,
    config_json TEXT NOT NULL,
    fingerprint VARCHAR(64) NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_professional_confirmations_diagnostic_fingerprint
        UNIQUE (diagnostic_id, fingerprint),
    FOREIGN KEY(diagnostic_id) REFERENCES professional_diagnostics (id)
);
CREATE TABLE professional_result_artifacts (
    id VARCHAR(128) NOT NULL,
    candidate_result_id VARCHAR(128) NOT NULL,
    confirmation_id VARCHAR(128),
    status VARCHAR(32) NOT NULL,
    capabilities_json TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_professional_result_artifacts_candidate UNIQUE (candidate_result_id),
    FOREIGN KEY(candidate_result_id) REFERENCES candidate_results (id),
    FOREIGN KEY(confirmation_id) REFERENCES professional_confirmations (id)
);
CREATE TABLE anomaly_extractions (
    id VARCHAR(128) NOT NULL,
    candidate_result_id VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL,
    config_json TEXT NOT NULL,
    fingerprint VARCHAR(64) NOT NULL,
    manifest_json TEXT NOT NULL,
    error_json TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(candidate_result_id) REFERENCES candidate_results (id)
);
CREATE UNIQUE INDEX ux_anomaly_extractions_succeeded_fingerprint
    ON anomaly_extractions (candidate_result_id, fingerprint) WHERE status = 'succeeded';
CREATE TABLE analysis_jobs (
    id VARCHAR(128) NOT NULL,
    job_kind VARCHAR(32) NOT NULL,
    subject_type VARCHAR(64) NOT NULL,
    subject_id VARCHAR(128) NOT NULL,
    request_fingerprint VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    retry_of_job_id VARCHAR(128),
    progress_json TEXT NOT NULL,
    error_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    PRIMARY KEY (id),
    FOREIGN KEY(retry_of_job_id) REFERENCES analysis_jobs (id)
);
CREATE UNIQUE INDEX ux_analysis_jobs_subject_inflight
    ON analysis_jobs (job_kind, subject_id) WHERE status IN ('queued', 'running');
"""

_TS = "2026-08-04T00:00:00+00:00"

# 一个候选及其外键链：迁移后必须逐字节保留。
V5_ROWS = f"""
INSERT INTO cases (id, name, case_type, config_json, created_at, updated_at)
VALUES ('case-1', '演示案例', 'generic', '{{}}', '{_TS}', '{_TS}');
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
"""

RENDER_ASSET_UNIQUE_COLUMNS = {
    "source_kind",
    "source_id",
    "grid_sha256",
    "renderer",
    "format_version",
}


def build_v5_fixture(db_path: Path) -> None:
    """Create a literal v5 database with one candidate row (plus its FK chain)."""

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(V4_DDL)
    conn.executescript(V5_EXTRA_DDL)
    conn.executescript(V5_ROWS)
    conn.execute("PRAGMA user_version=5")
    conn.commit()
    conn.close()


def render_asset_unique_columns(db_path: Path) -> set[str]:
    """Column set of the UNIQUE constraint on render_assets (raw PRAGMA read).

    origin='u' 只取 UNIQUE 约束生成的自动索引，排除主键（origin='pk'）
    与普通索引（origin='c'）。
    """

    raw = sqlite3.connect(db_path)
    try:
        columns: set[str] = set()
        for row in raw.execute("PRAGMA index_list('render_assets')"):
            name, unique, origin = row[1], row[2], row[3]
            if unique and origin == "u":
                columns.update(r[2] for r in raw.execute(f"PRAGMA index_info('{name}')"))
        return columns
    finally:
        raw.close()


def test_v5_to_v6_migration_creates_render_assets_and_preserves_rows(tmp_path):
    db_path = tmp_path / "runtime" / "platform.sqlite3"
    build_v5_fixture(db_path)
    raw = sqlite3.connect(db_path)
    try:
        candidate_count_before = raw.execute("SELECT COUNT(*) FROM candidate_results").fetchone()[0]
    finally:
        raw.close()

    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()

    assert runtime.schema_version() == 6
    with runtime.session() as session:
        existing_candidate = session.get(CandidateResult, "cand-1")
        assert existing_candidate is not None
        assert existing_candidate.status == "succeeded"
        assert existing_candidate.grid_path == "results/cand-1/grid.npz"
    with runtime.engine.connect() as conn:
        inspector = inspect(conn)
        assert inspector.has_table("render_assets"), "missing v6 table render_assets"

    raw = sqlite3.connect(db_path)
    try:
        candidate_count_after = raw.execute("SELECT COUNT(*) FROM candidate_results").fetchone()[0]
        assert candidate_count_after == candidate_count_before == 1
        render_asset_count = raw.execute("SELECT COUNT(*) FROM render_assets").fetchone()[0]
        assert render_asset_count == 0
        assert (
            raw.execute("SELECT fingerprint FROM candidate_results WHERE id='cand-1'").fetchone()[0]
            == "fp-cand-1"
        )
    finally:
        raw.close()
    assert render_asset_unique_columns(db_path) == RENDER_ASSET_UNIQUE_COLUMNS
    runtime.close()


def test_render_assets_check_constraint_rejects_invalid_status(tmp_path):
    build_v5_fixture(tmp_path / "runtime" / "platform.sqlite3")
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()

    with runtime.engine.connect() as conn:
        with pytest.raises(IntegrityError):
            conn.exec_driver_sql(
                "INSERT INTO render_assets "
                "(id, source_kind, source_id, candidate_result_id, renderer, format_version, "
                "status, grid_sha256, netcdf_sha256, asset_dir, manifest_json, error_json, "
                "created_at, updated_at) "
                "VALUES ('nc-bogus', 'candidate_result', 'cand-1', 'cand-1', "
                "'supermap_voxelgrid_netcdf', 2, 'bogus', '" + "a" * 64 + "', NULL, NULL, "
                "'{}', NULL, 't', 't')"
            )
        conn.rollback()
        # 合法状态入库成功：CHECK 白名单不会误伤正常状态机取值。
        for asset_id, status in (
            ("nc-ok-creating", "creating"),
            ("nc-ok-ready", "ready"),
            ("nc-ok-failed", "failed"),
            ("nc-ok-interrupted", "interrupted"),
        ):
            conn.exec_driver_sql(
                "INSERT INTO render_assets "
                "(id, source_kind, source_id, candidate_result_id, renderer, format_version, "
                "status, grid_sha256, manifest_json, created_at, updated_at) "
                f"VALUES ('{asset_id}', 'builtin_legacy', 'resistivity', NULL, "
                f"'supermap_voxelgrid_netcdf', 2, '{status}', '{'b' * 64}', '{{}}', 't', 't')"
            )
            conn.exec_driver_sql(f"DELETE FROM render_assets WHERE id='{asset_id}'")
        conn.commit()
    runtime.close()


def test_render_assets_enforces_candidate_result_foreign_key(tmp_path):
    build_v5_fixture(tmp_path / "runtime" / "platform.sqlite3")
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()

    insert = (
        "INSERT INTO render_assets "
        "(id, source_kind, source_id, candidate_result_id, renderer, format_version, "
        "status, grid_sha256, manifest_json, created_at, updated_at) "
        "VALUES ('{asset_id}', '{source_kind}', '{source_id}', {candidate_id}, "
        "'supermap_voxelgrid_netcdf', 2, 'creating', '{grid_sha}', '{{}}', 't', 't')"
    )
    with runtime.engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        # candidate_result_id 可空，且指向既有候选时入库成功。
        conn.exec_driver_sql(
            insert.format(
                asset_id="nc-fk-null",
                source_kind="builtin_legacy",
                source_id="resistivity",
                candidate_id="NULL",
                grid_sha="c" * 64,
            )
        )
        conn.exec_driver_sql(
            insert.format(
                asset_id="nc-fk-ok",
                source_kind="candidate_result",
                source_id="cand-1",
                candidate_id="'cand-1'",
                grid_sha="d" * 64,
            )
        )
        conn.commit()
        # 幽灵候选引用被拒绝。
        with pytest.raises(IntegrityError):
            conn.exec_driver_sql(
                insert.format(
                    asset_id="nc-fk-ghost",
                    source_kind="candidate_result",
                    source_id="ghost",
                    candidate_id="'ghost'",
                    grid_sha="e" * 64,
                )
            )
        conn.rollback()
    runtime.close()


def test_migrated_v6_render_assets_matches_fresh_database(tmp_path):
    """迁移产物的 render_assets 结构（列、约束、索引）与全新 v6 库完全一致。"""

    build_v5_fixture(tmp_path / "runtime" / "platform.sqlite3")
    migrated = PlatformRuntime(tmp_path / "runtime")
    migrated.initialize()
    migrated.close()

    fresh = PlatformRuntime(tmp_path / "fresh")
    fresh.initialize()
    fresh.close()

    assert table_fingerprint(tmp_path / "runtime" / "platform.sqlite3", "render_assets") == (
        table_fingerprint(tmp_path / "fresh" / "platform.sqlite3", "render_assets")
    ), "migrated render_assets schema diverges from a fresh v6 database"


def test_v6_initialize_is_idempotent_and_never_recreates_rows(tmp_path):
    build_v5_fixture(tmp_path / "runtime" / "platform.sqlite3")
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    runtime.close()

    # 二次启动不再执行迁移，v5 旧行保持原样。
    reopened = PlatformRuntime(tmp_path / "runtime")
    reopened.initialize()
    reopened.initialize()  # 同一实例重复 initialize 同样幂等
    assert reopened.schema_version() == 6
    with reopened.engine.connect() as conn:
        inspector = inspect(conn)
        assert inspector.has_table("render_assets")
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM render_assets").scalar_one() == 0
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
