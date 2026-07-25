"""Task 8 worker tests: queue semantics, persistence, cancel/retry, recovery."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pandas as pd
import pytest

from geomodeling.platform import PlatformRuntime, tables
from geomodeling.platform.repositories import RunRepository


def make_runtime(tmp_path: Path) -> PlatformRuntime:
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    return runtime


def make_experiment(runtime: PlatformRuntime, dataset_id: str = "ds1") -> str:
    import uuid
    import numpy as np
    import pandas as pd

    case_id = "c1"
    experiment_id = str(uuid.uuid4())
    # 最小标准化数据（供 runner 使用）
    rng = np.random.default_rng(1)
    n = 20
    frame = pd.DataFrame(
        {
            "source_row": np.arange(1, n + 1),
            "x": rng.uniform(-160, -40, n),
            "y": rng.uniform(220, 660, n),
            "z": np.nan,
            "value": rng.uniform(5, 15, n),
            "is_numeric_valid": True,
        }
    )
    target = runtime.settings.standardized_dataset(case_id, dataset_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(target, index=False)

    with runtime.session() as session:
        session.add(tables.Case(id=case_id, name="案例", case_type="generic", config_json="{}"))
        session.add(
            tables.DatasetVersion(
                id=dataset_id, case_id=case_id, version=1, status="validated",
                source_path="x.csv", profile_json=tables.dumps_canonical(
                    {"mapping": {"dimension": "2d", "x": "x", "y": "y", "value": "value",
                                 "value_name": "属性", "coordinate_kind": "local_linear"},
                     "source_sha256": "a" * 64, "standardized_sha256": "b" * 64,
                     "quality": {"status": "passed", "confirmed": True}}
                ),
            )
        )
        session.add(
            tables.Experiment(
                id=experiment_id, case_id=case_id, name="实验",
                params_json=tables.dumps_canonical(
                    {
                        "dimension": "2d",
                        "algorithm": "idw",
                        "dataset_version_id": dataset_id,
                        "search_mode": "manual",
                        "parameters": {"power": 2.0, "neighbor_count": 6},
                        "validation": {"method": "spatial_kfold", "folds": 3, "seed": 1,
                                       "holdout_fraction": 0.2},
                        "grid": None,
                    }
                ),
            )
        )
        session.commit()
    return experiment_id


def create_run(runtime: PlatformRuntime, experiment_id: str) -> str:
    import uuid

    with runtime.session() as session:
        record = RunRepository(session).create(experiment_id)
        return record.id


def wait_for(runtime: PlatformRuntime, run_id: str, statuses: set[str], timeout: float = 20.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with runtime.session() as session:
            status = RunRepository(session).get(run_id).status
        if status in statuses:
            return status
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} 未在 {timeout}s 内到达 {statuses}")


def test_worker_executes_queued_run_to_success(tmp_path):
    from geomodeling.platform.worker import JobWorker

    runtime = make_runtime(tmp_path)
    experiment_id = make_experiment(runtime)
    run_id = create_run(runtime, experiment_id)

    worker = JobWorker(runtime)
    try:
        worker.enqueue(run_id)
        status = wait_for(runtime, run_id, {"succeeded", "failed"}, timeout=30)
        assert status == "succeeded"
        with runtime.session() as session:
            record = RunRepository(session).get(run_id)
        assert record.started_at is not None
        assert record.finished_at is not None
        assert record.metrics["completed"] == record.metrics["total"]
    finally:
        worker.shutdown()


def test_progress_survives_new_reader_instance(tmp_path):
    from geomodeling.platform.worker import JobWorker

    runtime = make_runtime(tmp_path)
    experiment_id = make_experiment(runtime)
    run_id = create_run(runtime, experiment_id)

    worker = JobWorker(runtime)
    try:
        worker.enqueue(run_id)
        wait_for(runtime, run_id, {"succeeded", "failed"}, timeout=30)
        # 换一个“新的 API 实例”（新 Session）读取持久化进度
        with runtime.session() as session:
            record = RunRepository(session).get(run_id)
        assert record.metrics.get("total") == 1
        assert record.metrics.get("completed") == 1
        assert record.status == "succeeded"
    finally:
        worker.shutdown()


def test_cancel_before_start_marks_canceled(tmp_path):
    from geomodeling.platform.worker import JobWorker

    runtime = make_runtime(tmp_path)
    experiment_id = make_experiment(runtime)
    run_id = create_run(runtime, experiment_id)

    worker = JobWorker(runtime)
    try:
        worker.cancel(run_id)  # 入队前取消
        worker.enqueue(run_id)
        status = wait_for(runtime, run_id, {"canceled", "succeeded", "failed"}, timeout=30)
        assert status == "canceled"
    finally:
        worker.shutdown()


def test_startup_recovery_marks_inflight_interrupted(tmp_path):
    runtime = make_runtime(tmp_path)
    experiment_id = make_experiment(runtime)
    run_id = create_run(runtime, experiment_id)

    runtime.recover_interrupted_runs()
    with runtime.session() as session:
        record = RunRepository(session).get(run_id)
    assert record.status == "interrupted"
    assert record.error_code == "PROCESS_RESTARTED"


def test_retry_creates_new_run_with_link(tmp_path):
    runtime = make_runtime(tmp_path)
    experiment_id = make_experiment(runtime)
    run_id = create_run(runtime, experiment_id)

    # 把原 run 置为 failed（不删除记录）
    with runtime.session() as session:
        repo = RunRepository(session)
        repo.mark_running(run_id)
        repo.mark_failed(run_id, error_code="SIMULATED_FAILURE")

    with runtime.session() as session:
        retry = RunRepository(session).retry(run_id)
    assert retry.retry_of_run_id == run_id
    assert retry.status == "queued"

    with runtime.session() as session:
        original = RunRepository(session).get(run_id)
    assert original.status == "failed"  # 原失败记录不被覆盖


def test_retry_rejected_for_active_or_nonretryable(tmp_path):
    from geomodeling.platform.errors import PlatformError

    runtime = make_runtime(tmp_path)
    experiment_id = make_experiment(runtime)
    run_id = create_run(runtime, experiment_id)

    with runtime.session() as session:
        repo = RunRepository(session)
        with pytest.raises(PlatformError) as exc:
            repo.retry(run_id)  # queued 不可重试
        assert exc.value.code == "RUN_NOT_RETRYABLE"
