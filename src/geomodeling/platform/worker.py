"""Single-process background worker for interpolation and analysis jobs.

One ``ThreadPoolExecutor(max_workers=1)`` executes CPU-heavy candidates
sequentially so concurrent Kriging solves cannot exhaust the demo
machine's memory. Jobs are persisted before enqueueing; cancellation sets
both the in-memory event and a durable flag, so recovery and polling read
the same truth from the database.

v0.6（设计 §5.2）：worker 扩展为带 ``job_kind`` 的分派器——插值 run 走
``enqueue(run_id)``（行为不变），持久化专业分析任务走
``enqueue_analysis(job_id)``，按 ``job_kind`` 分派到诊断/异常提取执行
体；两条路径共享同一个单线程执行器（内存边界不变）与同一套
``_register_cancel_event``/``_register_future`` 私有方法。
"""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor

from geomodeling.modeling.runner import execute_run
from geomodeling.platform import tables
from geomodeling.platform.professional import (
    execute_anomaly_extraction,
    execute_professional_diagnosis,
    fail_unknown_kind,
)
from geomodeling.platform.repositories import AnalysisJobRepository

CANCEL_REQUESTED = "cancel_requested"

WORKER_UNCAUGHT_EXCEPTION = "WORKER_UNCAUGHT_EXCEPTION"


class JobWorker:
    """Serial job executor owned by the FastAPI lifespan (or tests)."""

    def __init__(self, runtime, max_workers: int = 1) -> None:
        self._runtime = runtime
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._cancel_events: dict[str, threading.Event] = {}
        self._pending_cancels: set[str] = set()
        self._futures: list[Future] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 共享私有方法：插值 run 与分析任务同一套入队登记语义
    # ------------------------------------------------------------------

    def _register_cancel_event(self, subject_id: str) -> threading.Event:
        event = threading.Event()
        with self._lock:
            if subject_id in self._pending_cancels:
                event.set()
                self._pending_cancels.discard(subject_id)
            self._cancel_events[subject_id] = event
        return event

    def _register_future(self, future: Future) -> None:
        with self._lock:
            self._futures.append(future)

    def enqueue(self, run_id: str) -> None:
        event = self._register_cancel_event(run_id)
        future = self._executor.submit(self._execute, run_id, event)
        self._register_future(future)

    def enqueue_analysis(self, job_id: str) -> None:
        event = self._register_cancel_event(job_id)
        future = self._executor.submit(self._execute_analysis, job_id, event)
        self._register_future(future)

    def _execute(self, run_id: str, event: threading.Event) -> None:
        try:
            execute_run(self._runtime, run_id, event)
        except Exception:  # worker 兜底：未捕获异常不得让 run 悬在 running
            with self._runtime.session() as session:
                row = session.get(tables.Run, run_id)
                if row is not None and row.status == "running":
                    row.status = "failed"
                    row.error_code = WORKER_UNCAUGHT_EXCEPTION
                    session.commit()
            raise

    def _execute_analysis(self, job_id: str, event: threading.Event) -> None:
        try:
            with self._runtime.session() as session:
                job = AnalysisJobRepository(session).get(job_id)
            if job.job_kind == "professional_diagnosis":
                execute_professional_diagnosis(self._runtime, job, event)
            elif job.job_kind == "anomaly_extraction":
                execute_anomaly_extraction(self._runtime, job, event)
            else:
                fail_unknown_kind(self._runtime, job)
        except Exception:  # worker 兜底：未捕获异常不得让分析任务悬在 running
            with self._runtime.session() as session:
                row = session.get(tables.AnalysisJob, job_id)
                if row is not None and row.status == "running":
                    row.status = "failed"
                    row.error_json = tables.dumps_canonical(
                        {
                            "code": WORKER_UNCAUGHT_EXCEPTION,
                            "message": "分析任务执行出现未捕获异常",
                        }
                    )
                    row.finished_at = tables.utc_now_iso()
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

    def cancel_analysis(self, job_id: str) -> None:
        """取消分析任务：内存事件 + 持久旗标（与插值 run 同一语义）。

        取消意图只允许对在途（queued/running）任务原子落库；终态行完全
        不可变。取消只影响当前任务，不改已有成功工件（§5.2）。
        """

        with self._lock:
            event = self._cancel_events.get(job_id)
            if event is None:
                self._pending_cancels.add(job_id)
            else:
                event.set()
        with self._runtime.session() as session:
            row = session.get(tables.AnalysisJob, job_id)
            if row is None or row.status not in tables.RUN_INFLIGHT_STATUSES:
                return
            progress = tables.loads_canonical(row.progress_json)
            progress[CANCEL_REQUESTED] = True
            session.execute(
                tables.AnalysisJob.__table__.update()
                .where(
                    tables.AnalysisJob.id == job_id,
                    tables.AnalysisJob.status.in_(sorted(tables.RUN_INFLIGHT_STATUSES)),
                )
                .values(
                    progress_json=tables.dumps_canonical(progress),
                    updated_at=tables.utc_now_iso(),
                )
            )
            session.commit()

    def wait_idle(self, timeout: float = 30.0) -> None:
        for future in list(self._futures):
            future.result(timeout=timeout)

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)
