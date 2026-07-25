"""Merge-blocker 3: terminal runs are immutable to cancel intent.

Cancel intent may only land as an atomic write on queued/running rows;
terminal runs reject cancellation (409) and keep metrics untouched.
Tests are fully deterministic: repository/worker calls only, no executor
thread, no sleeps.
"""

from __future__ import annotations

from geomodeling.platform import tables
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.repositories import ExperimentRepository, RunRepository
from geomodeling.platform.schemas import ExperimentCreateRequest
from geomodeling.platform.worker import CANCEL_REQUESTED, JobWorker
from test_experiment_api import make_client


def _make_experiment(runtime) -> str:
    from geomodeling.platform.repositories import CaseRepository, DatasetRepository
    from geomodeling.platform.schemas import CaseCreateRequest

    with runtime.session() as session:
        case = CaseRepository(session).create(CaseCreateRequest(name="取消语义案例"))
        dataset = DatasetRepository(session).create_version(case.id, source_path="pending://test")
        experiment = ExperimentRepository(session).create(
            case.id,
            ExperimentCreateRequest(
                case_id=case.id,
                name="取消语义实验",
                algorithm="idw",
                dataset_version_id=dataset.id,
                search_mode="manual",
                parameters={"power": 2.0},
            ),
        )
    return experiment.id


def _drive_to_terminal(runtime, run_id: str) -> None:
    with runtime.session() as session:
        repo = RunRepository(session)
        repo.mark_running(run_id)
        repo.mark_succeeded(run_id, metrics={"public_metrics": {"n_valid": 42}})


def test_terminal_run_rejects_cancel_and_keeps_metrics(tmp_path):
    client, runtime = make_client(tmp_path)
    experiment_id = _make_experiment(runtime)
    with runtime.session() as session:
        run = RunRepository(session).create(experiment_id)
    _drive_to_terminal(runtime, run.id)

    with runtime.session() as session:
        before = RunRepository(session).get(run.id)

    # 路由层：终态取消 → 409 RUN_NOT_CANCELABLE
    resp = client.post(f"/api/runs/{run.id}/cancel")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "RUN_NOT_CANCELABLE"

    # Worker 层：直接调用也不得修改终态指标
    worker = JobWorker(runtime)
    worker.cancel(run.id)

    with runtime.session() as session:
        after = RunRepository(session).get(run.id)
    assert after.status == "succeeded"
    assert after.metrics == before.metrics
    assert CANCEL_REQUESTED not in after.metrics


def test_cancel_intent_lands_atomically_only_on_inflight(tmp_path):
    client, runtime = make_client(tmp_path)
    experiment_id = _make_experiment(runtime)
    with runtime.session() as session:
        run = RunRepository(session).create(experiment_id)

    worker = JobWorker(runtime)
    worker.cancel(run.id)  # queued：原子写取消旗标

    with runtime.session() as session:
        flagged = RunRepository(session).get(run.id)
    assert flagged.metrics.get(CANCEL_REQUESTED) is True
    assert flagged.status == "queued"  # 旗标不直接改状态，状态迁移走 CAS

    # 路由层：queued → canceled（CAS 原子迁移）
    resp = client.post(f"/api/runs/{run.id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "canceled"

    # 已 canceled 后再取消 → 409，且 metrics 不再变化
    resp = client.post(f"/api/runs/{run.id}/cancel")
    assert resp.status_code == 409
    with runtime.session() as session:
        final = RunRepository(session).get(run.id)
    assert final.metrics == flagged.metrics


def test_cancel_on_missing_run_is_404(tmp_path):
    client, _ = make_client(tmp_path)
    resp = client.post("/api/runs/00000000-0000-0000-0000-000000000000/cancel")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "RUN_NOT_FOUND"
