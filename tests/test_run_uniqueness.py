"""Merge-blocker 4: at most one inflight run per experiment, DB-enforced."""

from __future__ import annotations

import sqlite3

import pytest

from geomodeling.platform import PlatformRuntime, tables
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.repositories import RunRepository
from test_cancel_semantics import _make_experiment
from test_experiment_api import make_client

V3_DDL = """
CREATE TABLE runs (
    id VARCHAR(128) PRIMARY KEY,
    experiment_id VARCHAR(128) NOT NULL,
    status VARCHAR(32),
    error_code VARCHAR(64),
    retry_of_run_id VARCHAR(128),
    metrics_json TEXT,
    created_at TEXT,
    updated_at TEXT,
    started_at TEXT,
    finished_at TEXT
);
CREATE TABLE exports (
    id VARCHAR(128) PRIMARY KEY,
    case_id VARCHAR(128) NOT NULL,
    package_path TEXT NOT NULL,
    manifest_json TEXT,
    created_at TEXT
);
"""


def test_partial_unique_index_rejects_second_inflight_run(tmp_path):
    client, runtime = make_client(tmp_path)
    experiment_id = _make_experiment(runtime)
    with runtime.session() as session:
        run = RunRepository(session).create(experiment_id)
        assert run.status == "queued"

        # 仓储层：第二个在途 run 直接被唯一约束拦下 → RUN_ALREADY_ACTIVE
        with pytest.raises(PlatformError) as excinfo:
            RunRepository(session).create(experiment_id)
        assert excinfo.value.code == "RUN_ALREADY_ACTIVE"
        assert excinfo.value.http_status == 409

        # DB 层：绕过仓储裸插同样违反部分唯一索引
        with pytest.raises(Exception) as raw:
            session.execute(
                tables.Run.__table__.insert().values(
                    id="raw-second", experiment_id=experiment_id, status="queued"
                )
            )
        assert "UNIQUE" in str(raw.value).upper() or "unique" in str(raw.value)


def test_terminal_runs_do_not_block_new_run(tmp_path):
    client, runtime = make_client(tmp_path)
    experiment_id = _make_experiment(runtime)
    with runtime.session() as session:
        repo = RunRepository(session)
        first = repo.create(experiment_id)
        repo.cancel(first.id)  # canceled 是终态，不占在途名额
        second = repo.create(experiment_id)
        assert second.status == "queued"
        assert second.id != first.id


def test_retry_with_inflight_run_returns_already_active(tmp_path):
    client, runtime = make_client(tmp_path)
    experiment_id = _make_experiment(runtime)
    with runtime.session() as session:
        repo = RunRepository(session)
        old = repo.create(experiment_id)
        repo.cancel(old.id)
        active = repo.create(experiment_id)
        with pytest.raises(PlatformError) as excinfo:
            repo.retry(old.id)
        assert excinfo.value.code == "RUN_ALREADY_ACTIVE"


def test_v3_to_v4_migration_adds_index_and_export_column(tmp_path):
    """v3 形状的既有数据库经 initialize 迁移到 v4：部分唯一索引 + exports.candidate_result_id。"""

    db_path = tmp_path / "runtime" / "platform.sqlite3"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(V3_DDL)
    conn.execute(
        "INSERT INTO runs (id, experiment_id, status) VALUES ('r1', 'e1', 'queued')"
    )
    conn.execute(
        "INSERT INTO runs (id, experiment_id, status) VALUES ('r0', 'e1', 'canceled')"
    )
    conn.execute("PRAGMA user_version=3")
    conn.commit()
    conn.close()

    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()  # 应触发 v3→v4 迁移而非报错
    assert runtime.schema_version() == 4

    raw = sqlite3.connect(db_path)
    index_names = {row[1] for row in raw.execute("PRAGMA index_list('runs')")}
    assert "ux_runs_experiment_inflight" in index_names
    export_cols = {row[1] for row in raw.execute("PRAGMA table_info('exports')")}
    assert "candidate_result_id" in export_cols

    # 迁移后约束即刻生效：e1 已有一个 queued，不能再插 queued；canceled 不拦
    with pytest.raises(sqlite3.IntegrityError):
        raw.execute("INSERT INTO runs (id, experiment_id, status) VALUES ('r2', 'e1', 'queued')")
    raw.execute("INSERT INTO runs (id, experiment_id, status) VALUES ('r3', 'e1', 'canceled')")
    raw.close()
    runtime.close()
