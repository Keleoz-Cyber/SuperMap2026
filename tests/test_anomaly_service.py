"""Task 13 anomaly service tests: persistent anomaly extraction jobs.

异常提取要求已物化成果（metadata 存在、grid 哈希登记）与已请求的不确定性
能力；按登记网格哈希与配置计算指纹，同成果同配置幂等返回既有成功。工件
（mask.npz / components.csv / summary.json / manifest.json）原子写入，
成功只在 manifest 校验通过后提交。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

import numpy as np
import pytest

from geomodeling.modeling.anomalies import ANOMALY_UNCERTAINTY_UNAVAILABLE
from geomodeling.platform import PlatformRuntime
from geomodeling.platform.analysis_jobs import (
    create_anomaly_extraction,
    get_anomaly_extraction,
)
from geomodeling.platform.errors import (
    ANALYSIS_JOB_ALREADY_ACTIVE,
    CANDIDATE_NOT_FOUND,
    PlatformError,
)
from geomodeling.platform.professional import (
    MANIFEST_VERIFICATION_FAILED,
    verify_manifest,
)
from geomodeling.platform.repositories import AnalysisJobRepository
from geomodeling.platform.results import RESULT_NOT_MATERIALIZED
from geomodeling.platform.worker import JobWorker
from test_platform_repositories import create_case, create_succeeded_candidate
from test_professional_diagnosis_service import make_runtime, wait_for_job

ANOMALY_CONFIG = {"direction": "high", "threshold": 6.0}


def make_materialized_result(
    runtime: PlatformRuntime, case_id: str = "c1", *, with_empirical_layer: bool = True
) -> str:
    """便携合成已物化成果：8×8 规则网格，中心一个高值异常斑。"""

    candidate_id = create_succeeded_candidate(runtime, create_case(runtime, name=case_id))
    axis = np.linspace(0.0, 10.5, 8)
    xx, yy = np.meshgrid(axis, axis, indexing="ij")
    values = 5.0 + 5.0 * np.exp(-((xx - 6.0) ** 2 + (yy - 6.0) ** 2) / 4.0)
    is_nodata = np.zeros(values.shape, dtype=bool)

    grid_path = runtime.settings.result_grid(candidate_id)
    grid_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        grid_path, axes=np.array([axis, axis], dtype=object), values=values, is_nodata=is_nodata
    )
    grid_sha256 = hashlib.sha256(grid_path.read_bytes()).hexdigest()
    metadata = {
        "result_id": candidate_id,
        "dimension": "2d",
        "algorithm": "idw",
        "shape": [8, 8],
        "cell_count": 64,
        "value_range": [5.0, 10.0],
        "nodata_count": 0,
        "grid_sha256": grid_sha256,
        "created_at": "2026-07-26T00:00:00+00:00",
    }
    (grid_path.parent / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if with_empirical_layer:
        layer_dir = runtime.settings.professional_result_dir(candidate_id)
        layer_dir.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            layer_dir / "empirical_error_scale.npz",
            values=np.full(values.shape, 0.5),
            is_nodata=np.zeros(values.shape, dtype=bool),
        )
    return candidate_id


def run_extraction_to_success(runtime: PlatformRuntime, result_id: str, config: dict):
    record = create_anomaly_extraction(runtime, result_id, config)
    worker = JobWorker(runtime)
    try:
        worker.enqueue_analysis(record.job_id)
        worker.wait_idle()
    finally:
        worker.shutdown()
    finished = get_anomaly_extraction(runtime, record.id)
    assert finished.status == "succeeded"
    return finished


def _extraction_count(runtime: PlatformRuntime, candidate_id: str) -> int:
    raw = sqlite3.connect(runtime.db_path)
    try:
        return raw.execute(
            "SELECT COUNT(*) FROM anomaly_extractions WHERE candidate_result_id = ?",
            (candidate_id,),
        ).fetchone()[0]
    finally:
        raw.close()


class TestAnomalyHappyPath:
    def test_create_enqueue_and_succeed_with_verified_manifest(self, tmp_path):
        runtime = make_runtime(tmp_path)
        result_id = make_materialized_result(runtime)

        record = create_anomaly_extraction(runtime, result_id, ANOMALY_CONFIG)
        assert record.reused is False
        worker = JobWorker(runtime)
        try:
            worker.enqueue_analysis(record.job_id)
            worker.wait_idle()
        finally:
            worker.shutdown()
        finished = get_anomaly_extraction(runtime, record.id)

        assert finished.status == "succeeded"
        assert verify_manifest(finished.manifest)
        assert set(finished.manifest["artifacts"]) == {"mask", "components", "summary"}

        final_dir = runtime.settings.anomaly_extraction_dir(result_id, record.id)
        for name in ("mask.npz", "components.csv", "summary.json", "manifest.json"):
            assert (final_dir / name).is_file(), name
        # 无遗留临时目录
        assert list(final_dir.parent.glob(f"{record.id}-*")) == []

        with np.load(final_dir / "mask.npz", allow_pickle=True) as bundle:
            mask = bundle["mask"]
        # threshold 6.0：9 个节点进入掩膜，连通为 1 个异常区
        assert int(mask.sum()) == 9

        components_lines = (final_dir / "components.csv").read_text(encoding="utf-8").splitlines()
        assert len(components_lines) == 1 + 1  # 表头 + 1 个连通区

        summary = json.loads((final_dir / "summary.json").read_text(encoding="utf-8"))
        assert summary["diagnostics"]["component_count"] == 1
        assert summary["diagnostics"]["eligible_node_count"] == 9
        assert summary["diagnostics"]["empirical_error_gated"] is False

        with runtime.session() as session:
            job = AnalysisJobRepository(session).get(record.job_id)
        assert job.status == "succeeded"
        assert job.progress["component_count"] == 1

    def test_same_result_same_config_returns_existing_success(self, tmp_path):
        runtime = make_runtime(tmp_path)
        result_id = make_materialized_result(runtime)
        finished = run_extraction_to_success(runtime, result_id, ANOMALY_CONFIG)

        repeated = create_anomaly_extraction(runtime, result_id, ANOMALY_CONFIG)
        assert repeated.reused is True
        assert repeated.id == finished.id
        assert repeated.job_id is None
        assert _extraction_count(runtime, result_id) == 1

    def test_distinct_config_creates_distinct_extraction(self, tmp_path):
        runtime = make_runtime(tmp_path)
        result_id = make_materialized_result(runtime)
        first = run_extraction_to_success(runtime, result_id, ANOMALY_CONFIG)
        second = create_anomaly_extraction(
            runtime, result_id, {"direction": "high", "threshold": 7.0}
        )
        assert second.reused is False
        assert second.id != first.id

    def test_empirical_error_gate_uses_registered_layer(self, tmp_path):
        runtime = make_runtime(tmp_path)
        result_id = make_materialized_result(runtime, with_empirical_layer=True)
        finished = run_extraction_to_success(
            runtime,
            result_id,
            {"direction": "high", "threshold": 6.0, "empirical_error_max": 1.0},
        )
        final_dir = runtime.settings.anomaly_extraction_dir(result_id, finished.id)
        summary = json.loads((final_dir / "summary.json").read_text(encoding="utf-8"))
        assert summary["diagnostics"]["empirical_error_gated"] is True
        assert summary["diagnostics"]["component_count"] == 1


class TestAnomalyRequestValidation:
    def test_unmaterialized_result_is_rejected(self, tmp_path):
        runtime = make_runtime(tmp_path)
        result_id = create_succeeded_candidate(runtime, create_case(runtime))

        with pytest.raises(PlatformError) as excinfo:
            create_anomaly_extraction(runtime, result_id, ANOMALY_CONFIG)
        assert excinfo.value.code == RESULT_NOT_MATERIALIZED
        assert excinfo.value.http_status == 404

    def test_unknown_result_is_404(self, tmp_path):
        runtime = make_runtime(tmp_path)
        with pytest.raises(PlatformError) as excinfo:
            create_anomaly_extraction(runtime, "ghost", ANOMALY_CONFIG)
        assert excinfo.value.code == CANDIDATE_NOT_FOUND

    def test_missing_empirical_layer_fails_structured(self, tmp_path):
        runtime = make_runtime(tmp_path)
        result_id = make_materialized_result(runtime, with_empirical_layer=False)

        with pytest.raises(PlatformError) as excinfo:
            create_anomaly_extraction(
                runtime,
                result_id,
                {"direction": "high", "threshold": 6.0, "empirical_error_max": 1.0},
            )
        assert excinfo.value.code == ANOMALY_UNCERTAINTY_UNAVAILABLE
        assert excinfo.value.http_status == 409
        # 请求期结构化失败：不得静默忽略门槛、不产生提取行
        assert _extraction_count(runtime, result_id) == 0

    def test_missing_kriging_std_layer_fails_structured(self, tmp_path):
        runtime = make_runtime(tmp_path)
        # IDW 成果：Kriging 原生标准差不适用（§3.3/§5.3），层不存在
        result_id = make_materialized_result(runtime, with_empirical_layer=False)

        with pytest.raises(PlatformError) as excinfo:
            create_anomaly_extraction(
                runtime,
                result_id,
                {"direction": "high", "threshold": 6.0, "kriging_std_max": 0.5},
            )
        assert excinfo.value.code == ANOMALY_UNCERTAINTY_UNAVAILABLE

    def test_duplicate_inflight_request_returns_409(self, tmp_path):
        runtime = make_runtime(tmp_path)
        result_id = make_materialized_result(runtime)
        create_anomaly_extraction(runtime, result_id, ANOMALY_CONFIG)

        with pytest.raises(PlatformError) as excinfo:
            create_anomaly_extraction(runtime, result_id, ANOMALY_CONFIG)
        assert excinfo.value.code == ANALYSIS_JOB_ALREADY_ACTIVE
        assert excinfo.value.http_status == 409


class TestAnomalyFailures:
    def test_manifest_verification_failure_blocks_success_commit(self, tmp_path, monkeypatch):
        runtime = make_runtime(tmp_path)
        result_id = make_materialized_result(runtime)

        import geomodeling.platform.professional as professional

        def boom_verify(_manifest):
            raise PlatformError(MANIFEST_VERIFICATION_FAILED, "工件哈希不匹配", http_status=409)

        monkeypatch.setattr(professional, "verify_manifest", boom_verify)
        record = create_anomaly_extraction(runtime, result_id, ANOMALY_CONFIG)
        worker = JobWorker(runtime)
        try:
            worker.enqueue_analysis(record.job_id)
            status = wait_for_job(runtime, record.job_id, {"succeeded", "failed"})
        finally:
            worker.shutdown()

        assert status == "failed"
        with runtime.session() as session:
            job = AnalysisJobRepository(session).get(record.job_id)
        assert job.error["code"] == MANIFEST_VERIFICATION_FAILED
        finished = get_anomaly_extraction(runtime, record.id)
        assert finished.status == "failed"
        assert finished.error["code"] == MANIFEST_VERIFICATION_FAILED

    def test_failed_extraction_allows_rerun_with_same_fingerprint(
        self, tmp_path, monkeypatch
    ):
        runtime = make_runtime(tmp_path)
        result_id = make_materialized_result(runtime)

        import geomodeling.platform.professional as professional

        def boom_verify(_manifest):
            raise PlatformError(MANIFEST_VERIFICATION_FAILED, "工件哈希不匹配", http_status=409)

        monkeypatch.setattr(professional, "verify_manifest", boom_verify)
        failed_record = create_anomaly_extraction(runtime, result_id, ANOMALY_CONFIG)
        worker = JobWorker(runtime)
        try:
            worker.enqueue_analysis(failed_record.job_id)
            assert wait_for_job(runtime, failed_record.job_id, {"failed"}) == "failed"
        finally:
            worker.shutdown()
        monkeypatch.undo()

        # 同成果同配置指纹：失败行不短路幂等，可重新提取并成功
        rerun = create_anomaly_extraction(runtime, result_id, ANOMALY_CONFIG)
        assert rerun.reused is False
        assert rerun.id != failed_record.id
        worker = JobWorker(runtime)
        try:
            worker.enqueue_analysis(rerun.job_id)
            worker.wait_idle()
        finally:
            worker.shutdown()
        finished = get_anomaly_extraction(runtime, rerun.id)
        assert finished.status == "succeeded"
        assert verify_manifest(finished.manifest)
