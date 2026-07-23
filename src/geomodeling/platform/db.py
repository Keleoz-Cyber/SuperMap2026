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

SCHEMA_VERSION = 1

_BUSY_TIMEOUT_MS = 30000


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

        Base.metadata.create_all(new_engine)
        with new_engine.begin() as conn:
            conn.exec_driver_sql(f"PRAGMA user_version={SCHEMA_VERSION}")

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
