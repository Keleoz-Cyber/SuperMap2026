"""Task 13 diagnosis service tests: persistent professional diagnosis jobs.

请求先落库再入队；worker 执行诊断计算并以「同级临时目录写齐 → 回读校验
→ 计算 SHA-256 → 原子替换」落盘六件工件；成功只在 manifest 校验通过后
提交。覆盖便携合成数据集上的完整链路、失败注入（临时写入、manifest
哈希、数据库收尾、清理异常优先级）与不可变确认服务。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from geomodeling.modeling.variogram import VARIOGRAM_FIT_FAILED
from geomodeling.platform import PlatformRuntime, tables
from geomodeling.platform.analysis_jobs import (
    create_professional_diagnosis,
    get_professional_diagnosis,
)
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.professional import (
    DIAGNOSIS_ARTIFACT_WRITE_FAILED,
    MANIFEST_VERIFICATION_FAILED,
    PROFESSIONAL_CONFIRMATION_INVALID,
    confirm_professional_diagnosis,
    verify_manifest,
)
from geomodeling.platform.repositories import (
    AnalysisJobRepository,
    ProfessionalConfirmationRepository,
    ProfessionalDiagnosticRepository,
)
from geomodeling.platform.worker import JobWorker

DIAGNOSIS_CONFIG = {
    "variogram": {
        "lag_count": 12,
        "min_pairs_per_bin": 20,
        "max_pairs": 50000,
        "directions": [
            {"dimension": "2d", "azimuth_deg": 0.0, "azimuth_tolerance_deg": 25.0},
            {"dimension": "2d", "azimuth_deg": 90.0, "azimuth_tolerance_deg": 25.0},
        ],
    }
}

# min_pairs_per_bin 超过任何 bin 的点对数 → 有效 bin 不足，必须结构化失败，
# 不允许静默改用旧固定 12-bin 拟合（§6.1/§17）。
INSUFFICIENT_CONFIG = {
    "variogram": {"lag_count": 12, "min_pairs_per_bin": 10000, "max_pairs": 50000}
}

DIAGNOSIS_ARTIFACT_FILES = (
    "metadata.json",
    "omnidirectional.csv",
    "directional.csv",
    "fitted_models.json",
    "anisotropy_candidates.json",
    "manifest.json",
)


def make_runtime(tmp_path: Path) -> PlatformRuntime:
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    return runtime


def make_diagnosis_dataset(
    runtime: PlatformRuntime, case_id: str = "c1", dataset_id: str = "ds1"
) -> tuple[str, str]:
    """便携合成数据集：14×14 规则点阵，x/y 方向空间结构不同（各向异性）。"""

    grid = np.arange(14) * 10.0
    xx, yy = np.meshgrid(grid, grid, indexing="ij")
    values = 2.0 * np.sin(xx.ravel() / 25.0) + np.cos(yy.ravel() / 60.0) + 10.0
    n = int(values.size)
    frame = pd.DataFrame(
        {
            "source_row": np.arange(1, n + 1),
            "x": xx.ravel(),
            "y": yy.ravel(),
            "z": np.nan,
            "value": values,
            "is_numeric_valid": True,
        }
    )
    target = runtime.settings.standardized_dataset(case_id, dataset_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(target, index=False)
    standardized_sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
    with runtime.session() as session:
        session.add(
            tables.Case(id=case_id, name="诊断案例", case_type="generic", config_json="{}")
        )
        session.add(
            tables.DatasetVersion(
                id=dataset_id,
                case_id=case_id,
                version=1,
                status="validated",
                source_path="x.csv",
                standardized_path=str(target),
                profile_json=tables.dumps_canonical(
                    {
                        "mapping": {
                            "dimension": "2d",
                            "x": "x",
                            "y": "y",
                            "value": "value",
                            "value_name": "属性",
                            "coordinate_kind": "local_linear",
                        },
                        "source_sha256": "a" * 64,
                        "standardized_sha256": standardized_sha256,
                        "quality": {"status": "passed", "confirmed": True},
                    }
                ),
            )
        )
        session.commit()
    return case_id, dataset_id


def wait_for_job(
    runtime: PlatformRuntime, job_id: str, statuses: set[str], timeout: float = 30.0
) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with runtime.session() as session:
            status = AnalysisJobRepository(session).get(job_id).status
        if status in statuses:
            return status
        time.sleep(0.05)
    raise AssertionError(f"analysis job {job_id} 未在 {timeout}s 内到达 {statuses}")


def run_diagnosis_to_success(
    runtime: PlatformRuntime, dataset_id: str, config: dict | None = None
):
    """计划 Step 2 的完整链路：创建 → 入队 → 等待 → 读取成功诊断。"""

    record = create_professional_diagnosis(runtime, dataset_id, config or DIAGNOSIS_CONFIG)
    worker = JobWorker(runtime)
    try:
        worker.enqueue_analysis(record.job_id)
        worker.wait_idle()
    finally:
        worker.shutdown()
    finished = get_professional_diagnosis(runtime, record.id)
    assert finished.status == "succeeded"
    return finished


def _diagnosis_count(runtime: PlatformRuntime) -> int:
    raw = sqlite3.connect(runtime.db_path)
    try:
        return raw.execute("SELECT COUNT(*) FROM professional_diagnostics").fetchone()[0]
    finally:
        raw.close()


# ---------------------------------------------------------------------------
# Happy path（计划 Step 2 原文断言）
# ---------------------------------------------------------------------------


class TestDiagnosisHappyPath:
    def test_create_enqueue_and_succeed_with_verified_manifest(self, tmp_path):
        runtime = make_runtime(tmp_path)
        _, dataset_id = make_diagnosis_dataset(runtime)

        record = create_professional_diagnosis(runtime, dataset_id, DIAGNOSIS_CONFIG)
        worker = JobWorker(runtime)
        try:
            worker.enqueue_analysis(record.job_id)
            worker.wait_idle()
        finally:
            worker.shutdown()
        finished = get_professional_diagnosis(runtime, record.id)

        assert finished.status == "succeeded"
        assert verify_manifest(finished.manifest)
        assert finished.manifest["artifacts"]["directional"]["sha256"]

    def test_six_artifacts_written_under_deterministic_dir(self, tmp_path):
        runtime = make_runtime(tmp_path)
        case_id, dataset_id = make_diagnosis_dataset(runtime)
        finished = run_diagnosis_to_success(runtime, dataset_id)

        final_dir = runtime.settings.professional_diagnosis_dir(
            case_id, dataset_id, finished.id
        )
        for name in DIAGNOSIS_ARTIFACT_FILES:
            assert (final_dir / name).is_file(), name
        # 无遗留临时目录（同级临时目录已清理）
        assert list(final_dir.parent.glob(f"{finished.id}-*")) == []

        omni_rows = (final_dir / "omnidirectional.csv").read_text(encoding="utf-8").splitlines()
        # 表头 + 12 个全向 bin
        assert len(omni_rows) == 1 + 12
        directional_rows = (final_dir / "directional.csv").read_text(encoding="utf-8").splitlines()
        # 表头 + 2 个方向 × 12 个 bin
        assert len(directional_rows) == 1 + 2 * 12

        fitted = json.loads((final_dir / "fitted_models.json").read_text(encoding="utf-8"))
        assert {m["model"] for m in fitted["models"]} == {"spherical", "exponential", "gaussian"}
        for model in fitted["models"]:
            assert model["parameter_origin"] == "automatic_candidate"
            assert model["converged"] is True
            assert model["weighted_sse"] >= 0.0
            assert model["bounds"]["range"][1] > 0.0

        candidates = json.loads(
            (final_dir / "anisotropy_candidates.json").read_text(encoding="utf-8")
        )
        assert 1 <= len(candidates["candidates"]) <= 3
        for candidate in candidates["candidates"]:
            assert candidate["status"] == "diagnostic_suggestion"

        metadata = json.loads((final_dir / "metadata.json").read_text(encoding="utf-8"))
        assert metadata["diagnosis_id"] == finished.id
        assert metadata["sampling"]["used_pair_count"] > 0

    def test_manifest_entries_cover_all_data_artifacts(self, tmp_path):
        runtime = make_runtime(tmp_path)
        _, dataset_id = make_diagnosis_dataset(runtime)
        finished = run_diagnosis_to_success(runtime, dataset_id)

        artifacts = finished.manifest["artifacts"]
        assert set(artifacts) == {
            "metadata",
            "omnidirectional",
            "directional",
            "fitted_models",
            "anisotropy_candidates",
        }
        for entry in artifacts.values():
            assert len(entry["sha256"]) == 64
            assert entry["bytes"] > 0
        # 成功提交后任务本身也是成功终态
        record = create_professional_diagnosis(runtime, dataset_id, DIAGNOSIS_CONFIG)
        assert record.reused is True
        assert record.job_id is None

    def test_same_data_same_config_is_deterministic(self, tmp_path):
        """同数据同配置（不同数据集身份）产生逐字节一致的数据工件。"""

        runtime = make_runtime(tmp_path)
        make_diagnosis_dataset(runtime, case_id="c1", dataset_id="ds-a")
        make_diagnosis_dataset(runtime, case_id="c2", dataset_id="ds-b")
        first = run_diagnosis_to_success(runtime, "ds-a")
        second = run_diagnosis_to_success(runtime, "ds-b")

        for name in ("omnidirectional", "directional", "fitted_models", "anisotropy_candidates"):
            assert (
                first.manifest["artifacts"][name]["sha256"]
                == second.manifest["artifacts"][name]["sha256"]
            ), name

    def test_idempotent_repeat_returns_existing_success(self, tmp_path):
        runtime = make_runtime(tmp_path)
        _, dataset_id = make_diagnosis_dataset(runtime)
        finished = run_diagnosis_to_success(runtime, dataset_id)

        repeated = create_professional_diagnosis(runtime, dataset_id, DIAGNOSIS_CONFIG)
        assert repeated.reused is True
        assert repeated.id == finished.id
        assert repeated.job_id is None
        assert _diagnosis_count(runtime) == 1


# ---------------------------------------------------------------------------
# 结构化失败与失败注入
# ---------------------------------------------------------------------------


class TestDiagnosisFailures:
    def test_insufficient_bins_fail_structured_without_legacy_fallback(self, tmp_path):
        runtime = make_runtime(tmp_path)
        _, dataset_id = make_diagnosis_dataset(runtime)
        record = create_professional_diagnosis(runtime, dataset_id, INSUFFICIENT_CONFIG)
        worker = JobWorker(runtime)
        try:
            worker.enqueue_analysis(record.job_id)
            status = wait_for_job(runtime, record.job_id, {"succeeded", "failed"})
        finally:
            worker.shutdown()

        assert status == "failed"
        with runtime.session() as session:
            job = AnalysisJobRepository(session).get(record.job_id)
            diagnosis = ProfessionalDiagnosticRepository(session).get(record.id)
        assert job.error["code"] == VARIOGRAM_FIT_FAILED
        assert diagnosis.status == "failed"
        assert diagnosis.error["code"] == VARIOGRAM_FIT_FAILED
        # 未静默改用旧固定 12-bin：没有任何成功工件目录
        case_id, _ = "c1", dataset_id
        final_dir = runtime.settings.professional_diagnosis_dir(case_id, dataset_id, record.id)
        assert not final_dir.exists() or not any(final_dir.iterdir())

    def test_temp_write_failure_cleans_up_and_fails_structured(self, tmp_path, monkeypatch):
        runtime = make_runtime(tmp_path)
        case_id, dataset_id = make_diagnosis_dataset(runtime)

        import geomodeling.platform.professional as professional

        def boom_write(_path, _data):
            raise OSError("磁盘已满")

        monkeypatch.setattr(professional, "_write_file", boom_write)
        record = create_professional_diagnosis(runtime, dataset_id, DIAGNOSIS_CONFIG)
        worker = JobWorker(runtime)
        try:
            worker.enqueue_analysis(record.job_id)
            status = wait_for_job(runtime, record.job_id, {"succeeded", "failed"})
        finally:
            worker.shutdown()

        assert status == "failed"
        with runtime.session() as session:
            job = AnalysisJobRepository(session).get(record.job_id)
            diagnosis = ProfessionalDiagnosticRepository(session).get(record.id)
        assert job.error["code"] == DIAGNOSIS_ARTIFACT_WRITE_FAILED
        assert diagnosis.status == "failed"
        # 部分写入不得残留：最终目录为空或不存在，临时目录已清理
        final_dir = runtime.settings.professional_diagnosis_dir(case_id, dataset_id, record.id)
        assert not final_dir.exists() or not any(final_dir.iterdir())
        assert list(final_dir.parent.glob(f"{record.id}-*")) == []

    def test_manifest_verification_failure_blocks_success_commit(self, tmp_path, monkeypatch):
        runtime = make_runtime(tmp_path)
        _, dataset_id = make_diagnosis_dataset(runtime)

        import geomodeling.platform.professional as professional

        def boom_verify(_manifest):
            raise PlatformError(
                MANIFEST_VERIFICATION_FAILED, "工件哈希不匹配", http_status=409
            )

        monkeypatch.setattr(professional, "verify_manifest", boom_verify)
        record = create_professional_diagnosis(runtime, dataset_id, DIAGNOSIS_CONFIG)
        worker = JobWorker(runtime)
        try:
            worker.enqueue_analysis(record.job_id)
            status = wait_for_job(runtime, record.job_id, {"succeeded", "failed"})
        finally:
            worker.shutdown()

        assert status == "failed"
        with runtime.session() as session:
            job = AnalysisJobRepository(session).get(record.job_id)
            diagnosis = ProfessionalDiagnosticRepository(session).get(record.id)
        assert job.error["code"] == MANIFEST_VERIFICATION_FAILED
        assert diagnosis.status == "failed"
        assert diagnosis.error["code"] == MANIFEST_VERIFICATION_FAILED

    def test_database_finalization_failure_commits_no_success(self, tmp_path, monkeypatch):
        runtime = make_runtime(tmp_path)
        _, dataset_id = make_diagnosis_dataset(runtime)

        from geomodeling.platform.repositories import ProfessionalDiagnosticRepository as Repo

        def boom_mark_succeeded(self, diagnosis_id, *, manifest):
            raise RuntimeError("数据库提交失败")

        monkeypatch.setattr(Repo, "mark_succeeded", boom_mark_succeeded)
        record = create_professional_diagnosis(runtime, dataset_id, DIAGNOSIS_CONFIG)
        worker = JobWorker(runtime)
        try:
            worker.enqueue_analysis(record.job_id)
            status = wait_for_job(runtime, record.job_id, {"succeeded", "failed"})
        finally:
            worker.shutdown()

        assert status == "failed"
        with runtime.session() as session:
            job = AnalysisJobRepository(session).get(record.job_id)
            diagnosis = ProfessionalDiagnosticRepository(session).get(record.id)
        assert job.error["code"] == "WORKER_UNCAUGHT_EXCEPTION"
        # 诊断绝不能误报成功
        assert diagnosis.status != "succeeded"

    def test_cleanup_exception_never_masks_business_error(self, tmp_path, monkeypatch):
        runtime = make_runtime(tmp_path)
        _, dataset_id = make_diagnosis_dataset(runtime)

        import geomodeling.platform.professional as professional

        def boom_write(_path, _data):
            raise RuntimeError("业务写失败")

        def boom_rmtree(_path, *args, **kwargs):
            raise RuntimeError("清理失败")

        monkeypatch.setattr(professional, "_write_file", boom_write)
        monkeypatch.setattr(professional.shutil, "rmtree", boom_rmtree)
        record = create_professional_diagnosis(runtime, dataset_id, DIAGNOSIS_CONFIG)
        worker = JobWorker(runtime)
        try:
            worker.enqueue_analysis(record.job_id)
            status = wait_for_job(runtime, record.job_id, {"succeeded", "failed"})
        finally:
            worker.shutdown()

        assert status == "failed"
        with runtime.session() as session:
            job = AnalysisJobRepository(session).get(record.job_id)
        # 清理异常不得覆盖原业务异常
        assert job.error["code"] == DIAGNOSIS_ARTIFACT_WRITE_FAILED
        assert "清理失败" not in json.dumps(job.error, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 不可变确认服务
# ---------------------------------------------------------------------------


def _auto_config(manifest: dict) -> dict:
    return {
        "model": "gaussian",
        "parameter_strategy": "automatic_candidate",
        "fitted_models_sha256": manifest["artifacts"]["fitted_models"]["sha256"],
        "anisotropy": {"keep_isotropic": True},
    }


def _manual_config(manifest: dict) -> dict:
    return {
        "model": "spherical",
        "parameter_strategy": "manual",
        "manual_parameters": {"nugget": 0.05, "sill": 3.0, "range": 120.0},
        "anisotropy": {
            "keep_isotropic": False,
            "azimuth_deg": 90.0,
            "dip_deg": None,
            "roll_deg": None,
            "major_minor_ratio": 6.0,
            "major_vertical_ratio": None,
            "candidate_rank": 1,
            "anisotropy_candidates_sha256": manifest["artifacts"]["anisotropy_candidates"]["sha256"],
        },
    }


class TestConfirmationService:
    def test_automatic_strategy_creates_immutable_snapshot(self, tmp_path):
        runtime = make_runtime(tmp_path)
        _, dataset_id = make_diagnosis_dataset(runtime)
        finished = run_diagnosis_to_success(runtime, dataset_id)

        record = confirm_professional_diagnosis(
            runtime, finished.id, _auto_config(finished.manifest), note="采纳自动候选"
        )
        assert record.diagnostic_id == finished.id
        assert record.note == "采纳自动候选"
        assert record.config["parameter_strategy"] == "automatic_candidate"
        assert record.config["anisotropy"]["keep_isotropic"] is True
        assert record.fingerprint

    def test_manual_strategy_marks_user_prior(self, tmp_path):
        runtime = make_runtime(tmp_path)
        _, dataset_id = make_diagnosis_dataset(runtime)
        finished = run_diagnosis_to_success(runtime, dataset_id)

        record = confirm_professional_diagnosis(
            runtime, finished.id, _manual_config(finished.manifest), note="人工固定参数"
        )
        assert record.config["parameter_strategy"] == "manual"
        assert record.config["parameter_origin"] == "manual_confirmed"
        assert record.config["prior"] == "user_prior"
        assert record.config["manual_parameters"] == {"nugget": 0.05, "sill": 3.0, "range": 120.0}
        assert record.config["anisotropy"]["candidate_rank"] == 1

    def test_duplicate_fingerprint_is_rejected_never_updated(self, tmp_path):
        runtime = make_runtime(tmp_path)
        _, dataset_id = make_diagnosis_dataset(runtime)
        finished = run_diagnosis_to_success(runtime, dataset_id)
        config = _auto_config(finished.manifest)

        first = confirm_professional_diagnosis(runtime, finished.id, config, note="第一次")
        with pytest.raises(PlatformError) as excinfo:
            confirm_professional_diagnosis(runtime, finished.id, config, note="试图改写")
        assert excinfo.value.code == "PROFESSIONAL_CONFIRMATION_CONFLICT"
        assert excinfo.value.http_status == 409

        with runtime.session() as session:
            snapshots = ProfessionalConfirmationRepository(session).list_for_diagnostic(finished.id)
        assert len(snapshots) == 1
        assert snapshots[0].id == first.id
        assert snapshots[0].note == "第一次"

    def test_distinct_configs_create_separate_snapshots(self, tmp_path):
        runtime = make_runtime(tmp_path)
        _, dataset_id = make_diagnosis_dataset(runtime)
        finished = run_diagnosis_to_success(runtime, dataset_id)

        auto = confirm_professional_diagnosis(
            runtime, finished.id, _auto_config(finished.manifest), note="自动"
        )
        manual = confirm_professional_diagnosis(
            runtime, finished.id, _manual_config(finished.manifest), note="人工"
        )
        assert auto.id != manual.id
        with runtime.session() as session:
            snapshots = ProfessionalConfirmationRepository(session).list_for_diagnostic(finished.id)
        assert [s.id for s in snapshots] == [auto.id, manual.id]
        # 既有快照不被新快照改写
        assert snapshots[0].note == "自动"

    def test_wrong_evidence_reference_is_rejected(self, tmp_path):
        runtime = make_runtime(tmp_path)
        _, dataset_id = make_diagnosis_dataset(runtime)
        finished = run_diagnosis_to_success(runtime, dataset_id)
        config = _auto_config(finished.manifest)
        config["fitted_models_sha256"] = "0" * 64

        with pytest.raises(PlatformError) as excinfo:
            confirm_professional_diagnosis(runtime, finished.id, config, note="伪造证据")
        assert excinfo.value.code == PROFESSIONAL_CONFIRMATION_INVALID

    def test_unknown_candidate_rank_is_rejected(self, tmp_path):
        runtime = make_runtime(tmp_path)
        _, dataset_id = make_diagnosis_dataset(runtime)
        finished = run_diagnosis_to_success(runtime, dataset_id)
        config = _manual_config(finished.manifest)
        config["anisotropy"]["candidate_rank"] = 99

        with pytest.raises(PlatformError) as excinfo:
            confirm_professional_diagnosis(runtime, finished.id, config, note="不存在的候选")
        assert excinfo.value.code == PROFESSIONAL_CONFIRMATION_INVALID

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda c: c.update({"parameter_strategy": "magic"}),
            lambda c: c.update({"manual_parameters": {"nugget": 3.0, "sill": 1.0, "range": 10.0}}),
            lambda c: c.update({"model": "cubic"}),
        ],
        ids=["unknown_strategy", "invalid_manual_parameters", "unknown_model"],
    )
    def test_invalid_configs_are_rejected(self, tmp_path, mutate):
        runtime = make_runtime(tmp_path)
        _, dataset_id = make_diagnosis_dataset(runtime)
        finished = run_diagnosis_to_success(runtime, dataset_id)
        config = _manual_config(finished.manifest)
        mutate(config)

        with pytest.raises(PlatformError) as excinfo:
            confirm_professional_diagnosis(runtime, finished.id, config, note="非法配置")
        assert excinfo.value.code == PROFESSIONAL_CONFIRMATION_INVALID

    def test_blank_note_is_rejected(self, tmp_path):
        runtime = make_runtime(tmp_path)
        _, dataset_id = make_diagnosis_dataset(runtime)
        finished = run_diagnosis_to_success(runtime, dataset_id)

        with pytest.raises(PlatformError) as excinfo:
            confirm_professional_diagnosis(
                runtime, finished.id, _auto_config(finished.manifest), note="  "
            )
        assert excinfo.value.code == PROFESSIONAL_CONFIRMATION_INVALID

    def test_confirmation_requires_succeeded_diagnosis(self, tmp_path):
        runtime = make_runtime(tmp_path)
        _, dataset_id = make_diagnosis_dataset(runtime)
        record = create_professional_diagnosis(runtime, dataset_id, DIAGNOSIS_CONFIG)

        with pytest.raises(PlatformError) as excinfo:
            confirm_professional_diagnosis(
                runtime,
                record.id,
                {"model": "spherical", "parameter_strategy": "automatic_candidate",
                 "fitted_models_sha256": "0" * 64, "anisotropy": {"keep_isotropic": True}},
                note="诊断尚未成功",
            )
        assert excinfo.value.code == "PROFESSIONAL_DIAGNOSIS_NOT_SUCCEEDED"
        assert excinfo.value.http_status == 409
