"""SQLite-backed platform runtime: engine lifecycle, schema, startup recovery.

The runtime owns the SQLAlchemy engine, creates the initial schema on first
initialize, and deterministically marks persisted in-flight runs as
``interrupted`` (error code ``PROCESS_RESTARTED``) at startup. Interrupted
runs are never auto-requeued; retry is an explicit user action. v5 起启动
恢复同样覆盖持久化分析任务（analysis_jobs）；v6 起覆盖 NetCDF 渲染资产
（render_assets 的 creating 行原子转 interrupted）。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, engine, event, inspect, update
from sqlalchemy.orm import Session, sessionmaker

from geomodeling.platform.schemas import STATUS_CREATING, STATUS_INTERRUPTED
from geomodeling.platform.settings import PlatformSettings
from geomodeling.platform.tables import (
    ERROR_PROCESS_RESTARTED,
    RUN_INFLIGHT_STATUSES,
    AnalysisJob,
    Base,
    CasePurgeOperation,
    RenderAsset,
    Run,
    RunStatus,
    dumps_canonical,
    utc_now_iso,
)

# v2: dataset_versions 增加 status 列与 (case_id, version) 唯一约束，
# runs 增加 retry_of_run_id 列。v1 开发库按 greenfield 删除重建，不做迁移。
# v3: candidate_results 成果列；v4: 在途 run 部分唯一索引 + exports.candidate_result_id；
# v5: professional_diagnostics / professional_confirmations /
# professional_result_artifacts / anomaly_extractions / analysis_jobs 五表。
# v6: render_assets（NetCDF 渲染资产状态表，v0.6.1 设计 §2.2）。
# v7: cases.lifecycle_state/trashed_at + case_purge_operations（v0.7.0 第三批设计 §4）。
SCHEMA_VERSION = 7

_BUSY_TIMEOUT_MS = 30000

# v5 新增表：迁移后显式核验必须全部存在。
_V5_NEW_TABLES = (
    "professional_diagnostics",
    "professional_confirmations",
    "professional_result_artifacts",
    "anomaly_extractions",
    "analysis_jobs",
)

# v6 新增表：迁移后显式核验必须存在。
_V6_NEW_TABLES = ("render_assets",)


def _create_v5_tables(conn: engine.Connection) -> None:
    """v4→v5：在同一事务内用 ORM metadata 创建五张新表并显式核验。

    采用 metadata 而非字面 SQL，消除 tables.py 与迁移脚本的漂移风险；
    ``checkfirst`` 保证绝不重建或清空既有 v4 行。新表在迁移前不存在，
    始终为空表，部分唯一索引无需像 v3→v4 在途 run 迁移那样先翻转历史数据。
    """

    Base.metadata.create_all(bind=conn, checkfirst=True)
    inspector = inspect(conn)
    missing = [name for name in _V5_NEW_TABLES if not inspector.has_table(name)]
    if missing:
        raise RuntimeError(f"v5 migration did not create tables: {missing}")


def _create_v6_tables(conn: engine.Connection) -> None:
    """v5->v6：在同一事务内用 ORM metadata 创建 render_assets 并显式核验。

    与 v5 迁移同构：metadata-backed 创建消除表定义漂移，``checkfirst``
    保证绝不触碰既有 v5 行；新表迁移前不存在，始终为空表。
    """

    Base.metadata.create_all(bind=conn, checkfirst=True)
    inspector = inspect(conn)
    missing = [name for name in _V6_NEW_TABLES if not inspector.has_table(name)]
    if missing:
        raise RuntimeError(f"v6 migration did not create tables: {missing}")


def _create_v7_schema(conn: engine.Connection) -> None:
    """v6->v7：在同一事务内添加 Case 生命周期列、索引和 purge 操作表。

    幂等：``inspect`` 检查列是否已存在，``checkfirst`` 保证索引和表不重建。
    迁移前所有既有 Case 行由 ALTER TABLE DEFAULT 'active' 赋值为 active。
    """

    columns = {item["name"] for item in inspect(conn).get_columns("cases")}
    if "lifecycle_state" not in columns:
        conn.exec_driver_sql(
            "ALTER TABLE cases ADD COLUMN lifecycle_state VARCHAR(16) "
            "NOT NULL DEFAULT 'active'"
        )
    if "trashed_at" not in columns:
        conn.exec_driver_sql("ALTER TABLE cases ADD COLUMN trashed_at TEXT")
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_cases_lifecycle_state ON cases(lifecycle_state)"
    )
    CasePurgeOperation.__table__.create(bind=conn, checkfirst=True)

    inspector = inspect(conn)
    if not inspector.has_table("case_purge_operations"):
        raise RuntimeError("v7 migration did not create case_purge_operations")
    case_columns = {c["name"] for c in inspector.get_columns("cases")}
    if "lifecycle_state" not in case_columns or "trashed_at" not in case_columns:
        raise RuntimeError("v7 migration did not add lifecycle columns to cases")


# 逐版本迁移步骤：键为起始版本。步骤为 SQL 字符串或接受连接的可调用对象；
# 每步必须在事务内幂等执行；迁移完成后统一重打 user_version。
# 比代码新的数据库仍然拒绝启动。
_MIGRATIONS: dict[int, tuple[str | Callable[[engine.Connection], None], ...]] = {
    3: (
        # 先按重启语义把历史在途 run 原子转 interrupted（v3 允许同一实验双在途），
        # 否则部分唯一索引建不起来
        "UPDATE runs SET status='interrupted', error_code='PROCESS_RESTARTED', "
        "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
        "WHERE status IN ('queued', 'running')",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_runs_experiment_inflight "
        "ON runs(experiment_id) WHERE status IN ('queued', 'running')",
        "ALTER TABLE exports ADD COLUMN candidate_result_id "
        "VARCHAR(128) REFERENCES candidate_results(id)",
    ),
    4: (_create_v5_tables,),
    5: (_create_v6_tables,),
    6: (_create_v7_schema,),
}


class PlatformRuntime:
    """Owns the platform database and runtime directory layout."""

    def __init__(
        self,
        data_dir: str | Path | None = None,
        settings: PlatformSettings | None = None,
    ) -> None:
        if settings is None:
            settings = (
                PlatformSettings(data_dir=Path(data_dir))
                if data_dir is not None
                else PlatformSettings.resolve()
            )
        self.settings = settings
        self._engine: engine.Engine | None = None
        self._session_factory: sessionmaker[Session] | None = None

    @property
    def db_path(self) -> Path:
        return self.settings.db_path

    @property
    def engine(self) -> engine.Engine:
        if self._engine is None:
            raise RuntimeError("platform runtime is not initialized")
        return self._engine

    def initialize(self) -> None:
        """Create the runtime layout and the initial schema (idempotent)."""

        self.close()
        for directory in self.settings.runtime_directories():
            directory.mkdir(parents=True, exist_ok=True)

        url = engine.URL.create("sqlite", database=str(self.db_path))
        new_engine = create_engine(url)

        @event.listens_for(new_engine, "connect")
        def _apply_sqlite_pragmas(dbapi_conn, _connection_record) -> None:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
            cursor.close()

        try:
            with new_engine.begin() as conn:
                existing = int(conn.exec_driver_sql("PRAGMA user_version").scalar_one())
                if existing == 0:  # fresh database: create tables, then stamp
                    Base.metadata.create_all(new_engine)
                    conn.exec_driver_sql(f"PRAGMA user_version={SCHEMA_VERSION}")
                elif existing < SCHEMA_VERSION:
                    missing = [v for v in range(existing, SCHEMA_VERSION) if v not in _MIGRATIONS]
                    if missing:
                        raise RuntimeError(
                            f"database schema v{existing} has no migration path to "
                            f"v{SCHEMA_VERSION} (missing steps: {missing}); "
                            "recreate the development database"
                        )
                    for step_version in sorted(v for v in _MIGRATIONS if v >= existing):
                        for step in _MIGRATIONS[step_version]:
                            if isinstance(step, str):
                                conn.exec_driver_sql(step)
                            else:
                                step(conn)
                    conn.exec_driver_sql(f"PRAGMA user_version={SCHEMA_VERSION}")
                elif existing > SCHEMA_VERSION:
                    raise RuntimeError(
                        f"database schema v{existing} is newer than code v{SCHEMA_VERSION}"
                    )
        except Exception:
            new_engine.dispose()
            raise

        self._engine = new_engine
        self._session_factory = sessionmaker(bind=new_engine, expire_on_commit=False)

    def schema_version(self) -> int:
        with self.engine.connect() as conn:
            return int(conn.exec_driver_sql("PRAGMA user_version").scalar_one())

    @contextmanager
    def session(self) -> Iterator[Session]:
        if self._session_factory is None:
            raise RuntimeError("platform runtime is not initialized")
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    def recover_interrupted_runs(self) -> int:
        """Mark persisted queued/running runs and analysis jobs interrupted.

        v5 起同一段恢复语义同时覆盖持久化分析任务：进程重启后在途任务
        一律转 ``interrupted``（错误码 ``PROCESS_RESTARTED``）。v6 起覆盖
        NetCDF 渲染资产：``creating`` 行原子转 ``interrupted``。返回三张表
        翻转的总行数。任务与资产都不会被自动重排队/重建；重试是显式用户动作。
        """

        with self.session() as session:
            runs_flipped = session.execute(
                update(Run)
                .where(Run.status.in_(sorted(RUN_INFLIGHT_STATUSES)))
                .values(
                    status=RunStatus.INTERRUPTED.value,
                    error_code=ERROR_PROCESS_RESTARTED,
                    updated_at=utc_now_iso(),
                )
            )
            jobs_flipped = session.execute(
                update(AnalysisJob)
                .where(AnalysisJob.status.in_(sorted(RUN_INFLIGHT_STATUSES)))
                .values(
                    status=RunStatus.INTERRUPTED.value,
                    error_json=dumps_canonical(
                        {
                            "code": ERROR_PROCESS_RESTARTED,
                            "message": "进程重启，在途分析任务被标记为中断",
                        }
                    ),
                    updated_at=utc_now_iso(),
                )
            )
            assets_flipped = session.execute(
                update(RenderAsset)
                .where(RenderAsset.status == STATUS_CREATING)
                .values(
                    status=STATUS_INTERRUPTED,
                    error_json=dumps_canonical(
                        {
                            "code": ERROR_PROCESS_RESTARTED,
                            "message": "render asset creation interrupted",
                        }
                    ),
                    updated_at=utc_now_iso(),
                )
            )
            session.commit()
            return (
                int(runs_flipped.rowcount)
                + int(jobs_flipped.rowcount)
                + int(assets_flipped.rowcount)
            )

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
            self._session_factory = None
