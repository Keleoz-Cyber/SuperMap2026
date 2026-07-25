"""SQLite-backed platform runtime: engine lifecycle, schema, startup recovery.

The runtime owns the SQLAlchemy engine, creates the initial schema on first
initialize, and deterministically marks persisted in-flight runs as
``interrupted`` (error code ``PROCESS_RESTARTED``) at startup. Interrupted
runs are never auto-requeued; retry is an explicit user action.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, engine, event, update
from sqlalchemy.orm import Session, sessionmaker

from geomodeling.platform.settings import PlatformSettings
from geomodeling.platform.tables import (
    ERROR_PROCESS_RESTARTED,
    RUN_INFLIGHT_STATUSES,
    Base,
    Run,
    RunStatus,
    utc_now_iso,
)

# v2: dataset_versions 增加 status 列与 (case_id, version) 唯一约束，
# runs 增加 retry_of_run_id 列。v1 开发库按 greenfield 删除重建，不做迁移。
SCHEMA_VERSION = 4  # v3: candidate_results 成果列；v4: 在途 run 部分唯一索引 + exports.candidate_result_id

_BUSY_TIMEOUT_MS = 30000

# 逐版本迁移步骤：键为起始版本。每步必须在事务内幂等执行；
# 迁移完成后统一重打 user_version。比代码新的数据库仍然拒绝启动。
_MIGRATIONS: dict[int, tuple[str, ...]] = {
    3: (
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_runs_experiment_inflight "
        "ON runs(experiment_id) WHERE status IN ('queued', 'running')",
        "ALTER TABLE exports ADD COLUMN candidate_result_id "
        "VARCHAR(128) REFERENCES candidate_results(id)",
    ),
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
                        for statement in _MIGRATIONS[step_version]:
                            conn.exec_driver_sql(statement)
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
        """Mark persisted queued/running runs interrupted after a restart.

        Returns the number of runs flipped. Runs are not requeued; retrying
        is an explicit user action.
        """

        with self.session() as session:
            result = session.execute(
                update(Run)
                .where(Run.status.in_(sorted(RUN_INFLIGHT_STATUSES)))
                .values(
                    status=RunStatus.INTERRUPTED.value,
                    error_code=ERROR_PROCESS_RESTARTED,
                    updated_at=utc_now_iso(),
                )
            )
            session.commit()
            return int(result.rowcount)

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
            self._session_factory = None
