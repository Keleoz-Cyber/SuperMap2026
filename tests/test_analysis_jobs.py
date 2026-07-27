"""Task 13 analysis-job state machine tests.

断言（计划 Step 1）：诊断请求先落库再入队；worker 按 job_kind 分派；进程
恢复把在途分析任务标记为 interrupted；重试产生新任务并保留旧证据；取消
是持久的；未捕获异常不得留下 running 状态；重复在途请求返回 409；成功
只在 manifest 校验通过后提交。
"""

from __future__ import annotations


import pytest

from geomodeling.modeling.variogram import VARIOGRAM_FIT_FAILED
from geomodeling.platform.analysis_jobs import (
    create_professional_diagnosis,
    get_analysis_job,
    get_professional_diagnosis,
    retry_analysis_job,
)
from geomodeling.platform.errors import ANALYSIS_JOB_ALREADY_ACTIVE, PlatformError
from geomodeling.platform.professional import (
    ANALYSIS_JOB_KIND_UNKNOWN,
    MANIFEST_VERIFICATION_FAILED,
    fail_unknown_kind,
)
from geomodeling.platform.repositories import (
    AnalysisJobRepository,
    ProfessionalDiagnosticRepository,
)
from geomodeling.platform.schemas import AnalysisJobRecord
from geomodeling.platform.tables import ERROR_PROCESS_RESTARTED
from geomodeling.platform.worker import CANCEL_REQUESTED, JobWorker
from test_professional_diagnosis_service import (
    DIAGNOSIS_CONFIG,
    INSUFFICIENT_CONFIG,
    make_diagnosis_dataset,
    make_runtime,
    wait_for_job,
)


def _job(runtime, job_id: str) -> AnalysisJobRecord:
    return get_analysis_job(runtime, job_id)


class TestRequestPersistsBeforeEnqueue:
    def test_diagnosis_request_persists_before_enqueue(self, tmp_path):
        runtime = make_runtime(tmp_path)
        _, dataset_id = make_diagnosis_dataset(runtime)

        record = create_professional_diagnosis(runtime, dataset_id, DIAGNOSIS_CONFIG)

        # 未入队：新会话即可读到 queued 诊断与 queued 任务（先落库）
        diagnosis = get_professional_diagnosis(runtime, record.id)
        job = _job(runtime, record.job_id)
        assert diagnosis.status == "queued"
        assert diagnosis.manifest == {}
        assert job.status == "queued"
        assert job.job_kind == "professional_diagnosis"
        assert job.subject_id == record.id
        assert job.request_fingerprint == diagnosis.fingerprint
        assert record.reused is False


class TestWorkerDispatch:
    def test_worker_dispatches_by_job_kind(self, tmp_path, monkeypatch):
        runtime = make_runtime(tmp_path)
        _, dataset_id = make_diagnosis_dataset(runtime)
        record = create_professional_diagnosis(runtime, dataset_id, DIAGNOSIS_CONFIG)
        # 不同 kind 各有在途槽位：同 subject 也可插一条 anomaly_extraction 任务
        with runtime.session() as session:
            anomaly_job = AnalysisJobRepository(session).create(
                job_kind="anomaly_extraction",
                subject_type="anomaly_extraction",
                subject_id="ext-spy",
                request_fingerprint="fp-spy",
            )

        calls: list[tuple[str, str]] = []

        import geomodeling.platform.worker as worker_module

        def spy_diagnosis(_runtime, job, _event):
            calls.append(("professional_diagnosis", job.id))

        def spy_anomaly(_runtime, job, _event):
            calls.append(("anomaly_extraction", job.id))

        monkeypatch.setattr(worker_module, "execute_professional_diagnosis", spy_diagnosis)
        monkeypatch.setattr(worker_module, "execute_anomaly_extraction", spy_anomaly)

        worker = JobWorker(runtime)
        try:
            worker.enqueue_analysis(record.job_id)
            worker.enqueue_analysis(anomaly_job.id)
            worker.wait_idle()
        finally:
            worker.shutdown()

        assert ("professional_diagnosis", record.job_id) in calls
        assert ("anomaly_extraction", anomaly_job.id) in calls
        # 分派收到的 job 记录带有正确的 subject
        kinds = {kind for kind, _ in calls}
        assert kinds == {"professional_diagnosis", "anomaly_extraction"}

    def test_fail_unknown_kind_marks_job_failed(self, tmp_path):
        runtime = make_runtime(tmp_path)
        with runtime.session() as session:
            job = AnalysisJobRepository(session).create(
                job_kind="professional_diagnosis",
                subject_type="professional_diagnostic",
                subject_id="ghost",
                request_fingerprint="fp",
            )
        unknown = AnalysisJobRecord.model_construct(
            id=job.id,
            job_kind="mystery_kind",
            subject_type="x",
            subject_id="s",
            request_fingerprint="fp",
            status="queued",
            retry_of_job_id=None,
            progress={},
            error=None,
            created_at="t",
            updated_at="t",
            started_at=None,
            finished_at=None,
        )
        fail_unknown_kind(runtime, unknown)
        failed = _job(runtime, job.id)
        assert failed.status == "failed"
        assert failed.error["code"] == ANALYSIS_JOB_KIND_UNKNOWN

    def test_missing_subject_fails_structured_not_silent(self, tmp_path):
        runtime = make_runtime(tmp_path)
        with runtime.session() as session:
            job = AnalysisJobRepository(session).create(
                job_kind="professional_diagnosis",
                subject_type="professional_diagnostic",
                subject_id="ghost-diagnosis",
                request_fingerprint="fp",
            )
        worker = JobWorker(runtime)
        try:
            worker.enqueue_analysis(job.id)
            status = wait_for_job(runtime, job.id, {"succeeded", "failed"})
        finally:
            worker.shutdown()
        assert status == "failed"
        assert _job(runtime, job.id).error["code"] == "PROFESSIONAL_DIAGNOSIS_NOT_FOUND"


class TestRecovery:
    def test_process_recovery_marks_analysis_jobs_interrupted(self, tmp_path):
        runtime = make_runtime(tmp_path)
        _, dataset_id = make_diagnosis_dataset(runtime)
        record = create_professional_diagnosis(runtime, dataset_id, DIAGNOSIS_CONFIG)

        assert runtime.recover_interrupted_runs() == 1

        job = _job(runtime, record.job_id)
        assert job.status == "interrupted"
        assert job.error["code"] == ERROR_PROCESS_RESTARTED
        # 恢复只翻转任务；诊断行保持 queued，等待显式重试
        diagnosis = get_professional_diagnosis(runtime, record.id)
        assert diagnosis.status == "queued"
        # 幂等：再次恢复不再翻转
        assert runtime.recover_interrupted_runs() == 0


class TestRetry:
    def test_retry_creates_new_job_and_retains_old_evidence(self, tmp_path):
        runtime = make_runtime(tmp_path)
        _, dataset_id = make_diagnosis_dataset(runtime)
        record = create_professional_diagnosis(runtime, dataset_id, INSUFFICIENT_CONFIG)
        worker = JobWorker(runtime)
        try:
            worker.enqueue_analysis(record.job_id)
            assert wait_for_job(runtime, record.job_id, {"failed"}) == "failed"

            retried = retry_analysis_job(runtime, record.job_id)
            assert retried.id != record.job_id
            assert retried.retry_of_job_id == record.job_id
            assert retried.status == "queued"
            assert retried.subject_id == record.id

            # 确定性重跑：同数据同配置仍以同一结构化错误失败
            worker.enqueue_analysis(retried.id)
            assert wait_for_job(runtime, retried.id, {"failed"}) == "failed"
        finally:
            worker.shutdown()

        # 旧证据保留：原任务与原诊断的错误不被重试覆盖
        original = _job(runtime, record.job_id)
        assert original.status == "failed"
        assert original.error["code"] == VARIOGRAM_FIT_FAILED
        retried_job = _job(runtime, retried.id)
        assert retried_job.error["code"] == VARIOGRAM_FIT_FAILED
        with runtime.session() as session:
            diagnosis = ProfessionalDiagnosticRepository(session).get(record.id)
        assert diagnosis.status == "failed"
        assert diagnosis.error["code"] == VARIOGRAM_FIT_FAILED


class TestCancellation:
    def test_cancellation_is_durable(self, tmp_path):
        runtime = make_runtime(tmp_path)
        _, dataset_id = make_diagnosis_dataset(runtime)
        record = create_professional_diagnosis(runtime, dataset_id, DIAGNOSIS_CONFIG)

        worker = JobWorker(runtime)
        try:
            worker.cancel_analysis(record.job_id)  # 入队前取消
            # 取消意图原子落库：新会话读出持久旗标
            job = _job(runtime, record.job_id)
            assert job.progress.get(CANCEL_REQUESTED) is True

            worker.enqueue_analysis(record.job_id)
            status = wait_for_job(runtime, record.job_id, {"canceled", "succeeded", "failed"})
        finally:
            worker.shutdown()

        assert status == "canceled"
        # 取消只影响当前任务：诊断行不被改写、不产生工件
        diagnosis = get_professional_diagnosis(runtime, record.id)
        assert diagnosis.status == "queued"
        assert diagnosis.manifest == {}

    def test_cancel_terminal_job_does_not_rewrite_it(self, tmp_path):
        runtime = make_runtime(tmp_path)
        _, dataset_id = make_diagnosis_dataset(runtime)
        record = create_professional_diagnosis(runtime, dataset_id, DIAGNOSIS_CONFIG)
        worker = JobWorker(runtime)
        try:
            worker.enqueue_analysis(record.job_id)
            worker.wait_idle()
            assert _job(runtime, record.job_id).status == "succeeded"
            # 终态任务取消意图不落库
            worker.cancel_analysis(record.job_id)
        finally:
            worker.shutdown()
        job = _job(runtime, record.job_id)
        assert job.status == "succeeded"
        assert not job.progress.get(CANCEL_REQUESTED)


class TestUncaughtException:
    def test_uncaught_exception_cannot_leave_running_state(self, tmp_path, monkeypatch):
        runtime = make_runtime(tmp_path)
        _, dataset_id = make_diagnosis_dataset(runtime)
        record = create_professional_diagnosis(runtime, dataset_id, DIAGNOSIS_CONFIG)

        import geomodeling.platform.professional as professional

        def boom(*_args, **_kwargs):
            raise RuntimeError("模拟崩溃")

        monkeypatch.setattr(professional, "compute_empirical_variogram", boom)
        worker = JobWorker(runtime)
        try:
            worker.enqueue_analysis(record.job_id)
            status = wait_for_job(runtime, record.job_id, {"failed"})
        finally:
            worker.shutdown()

        assert status == "failed"
        job = _job(runtime, record.job_id)
        assert job.error["code"] == "WORKER_UNCAUGHT_EXCEPTION"
        assert job.finished_at is not None


class TestDuplicateInflight:
    def test_duplicate_inflight_request_returns_409(self, tmp_path):
        runtime = make_runtime(tmp_path)
        _, dataset_id = make_diagnosis_dataset(runtime)
        create_professional_diagnosis(runtime, dataset_id, DIAGNOSIS_CONFIG)

        with pytest.raises(PlatformError) as excinfo:
            create_professional_diagnosis(runtime, dataset_id, DIAGNOSIS_CONFIG)
        assert excinfo.value.code == ANALYSIS_JOB_ALREADY_ACTIVE
        assert excinfo.value.http_status == 409


class TestSuccessCommit:
    def test_success_committed_only_after_manifest_verification(self, tmp_path, monkeypatch):
        runtime = make_runtime(tmp_path)
        _, dataset_id = make_diagnosis_dataset(runtime)

        import geomodeling.platform.professional as professional

        def boom_verify(_manifest):
            raise PlatformError(MANIFEST_VERIFICATION_FAILED, "工件哈希不匹配", http_status=409)

        monkeypatch.setattr(professional, "verify_manifest", boom_verify)
        record = create_professional_diagnosis(runtime, dataset_id, DIAGNOSIS_CONFIG)
        worker = JobWorker(runtime)
        try:
            worker.enqueue_analysis(record.job_id)
            status = wait_for_job(runtime, record.job_id, {"succeeded", "failed"})
        finally:
            worker.shutdown()

        assert status == "failed"
        job = _job(runtime, record.job_id)
        diagnosis = get_professional_diagnosis(runtime, record.id)
        assert job.error["code"] == MANIFEST_VERIFICATION_FAILED
        # manifest 校验未过：诊断不得提交成功
        assert diagnosis.status == "failed"
        assert diagnosis.manifest == {}
