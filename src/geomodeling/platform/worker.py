"""Single-process background worker for interpolation jobs.

One ``ThreadPoolExecutor(max_workers=1)`` executes CPU-heavy candidates
sequentially so concurrent Kriging solves cannot exhaust the demo
machine's memory. Jobs are persisted before enqueueing; cancellation sets
both the in-memory event and a durable flag, so recovery and polling read
the same truth from the database.
"""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from geomodeling.modeling.runner import execute_run
from geomodeling.platform import tables
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.repositories import RunRepository

CANCEL_REQUESTED = "cancel_requested"


class JobWorker:
    """Serial job executor owned by the FastAPI lifespan (or tests)."""

    def __init__(self, runtime, max_workers: int = 1) -> None:
        self._runtime = runtime
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._cancel_events: dict[str, threading.Event] = {}
        self._pending_cancels: set[str] = set()
        self._futures: list[Future] = []
        self._lock = threading.Lock()

    def enqueue(self, run_id: str) -> None:
        event = threading.Event()
        with self._lock:
            if run_id in self._pending_cancels:
                event.set()
                self._pending_cancels.discard(run_id)
            self._cancel_events[run_id] = event
        future = self._executor.submit(self._execute, run_id, event)
        with self._lock:
            self._futures.append(future)

    def _execute(self, run_id: str, event: threading.Event) -> None:
        try:
            execute_run(self._runtime, run_id, event)
        except Exception:  # worker 兜底：未捕获异常不得让 run 悬在 running
            with self._runtime.session() as session:
                row = session.get(tables.Run, run_id)
                if row is not None and row.status == "running":
                    row.status = "failed"
                    row.error_code = "WORKER_UNCAUGHT_EXCEPTION"
                    session.commit()
            raise

    def cancel(self, run_id: str) -> None:
        with self._lock:
            event = self._cancel_events.get(run_id)
            if event is None:
                self._pending_cancels.add(run_id)
            else:
                event.set()
        # 取消意图只允许对在途（queued/running）任务原子落库；
        # 终态行完全不可变——不读改写、不追加旗标。
        with self._runtime.session() as session:
            row = session.get(tables.Run, run_id)
            if row is None or row.status not in tables.RUN_INFLIGHT_STATUSES:
                return
            metrics = tables.loads_canonical(row.metrics_json)
            metrics[CANCEL_REQUESTED] = True
            session.execute(
                tables.Run.__table__.update()
                .where(
                    tables.Run.id == run_id,
                    tables.Run.status.in_(sorted(tables.RUN_INFLIGHT_STATUSES)),
                )
                .values(
                    metrics_json=tables.dumps_canonical(metrics),
                    updated_at=tables.utc_now_iso(),
                )
            )
            session.commit()

    def wait_idle(self, timeout: float = 30.0) -> None:
        for future in list(self._futures):
            future.result(timeout=timeout)

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)
