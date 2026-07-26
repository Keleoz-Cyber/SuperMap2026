"""Task 17: professional analysis public API and path-free DTOs.

端到端覆盖 v0.6 专业分析公开面：诊断（202 + 任务身份、轮询、幂等复用）、
不可变确认（201）、analysis-jobs 生命周期（cancel 只改当前任务、retry 新身
份 ``retry_of_job_id``）、成果专业证据（capabilities/参数出处/manifest 摘
要、folds、有界 residuals、不确定性层能力矩阵）、异常提取（202 + 状态）、
双候选比较（幂等 fingerprint 查询）与白名单工件下载（只接受已登记身份）。

Red-phase note: 本模块刻意不 import ``geomodeling.api.routes.professional``
与新的 DTO 构造函数——路由实现前每个测试必须以 HTTP 404（路由缺失）失败，
而不是 collection ImportError。脱敏断言复用 ``test_public_dto`` 的递归助手。
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from geomodeling.api.app import create_app
from geomodeling.api.deps import ApiSettings, get_settings
from geomodeling.modeling.variogram import VARIOGRAM_FIT_FAILED
from geomodeling.platform.analysis_jobs import create_professional_diagnosis
from test_public_dto import assert_no_path_leak

# ---------------------------------------------------------------------------
# 固定夹具数据：14×14 规则点阵（x/y 方向空间结构不同），与服务层测试同源
# ---------------------------------------------------------------------------

MAPPING_2D = {
    "dimension": "2d",
    "x": "x",
    "y": "y",
    "value": "value",
    "value_name": "属性",
    "coordinate_kind": "local_linear",
}

VALIDATION = {"method": "spatial_kfold", "folds": 3, "seed": 11, "holdout_fraction": 0.2}
NEIGHBORHOOD = {"radii": [500.0, 500.0], "min_neighbors": 2, "max_neighbors": 8}
EMPIRICAL = {"min_neighbors": 2, "max_neighbors": 8}

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

# min_pairs_per_bin 超过任何 bin 的点对数 → 有效 bin 不足，结构化失败
INSUFFICIENT_CONFIG = {
    "variogram": {"lag_count": 12, "min_pairs_per_bin": 10000, "max_pairs": 50000}
}

GRID_POINT_COUNT = 14 * 14


def _grid_csv() -> str:
    lines = ["x,y,value"]
    grid = [index * 10.0 for index in range(14)]
    for x in grid:
        for y in grid:
            value = 2.0 * math.sin(x / 25.0) + math.cos(y / 60.0) + 10.0
            lines.append(f"{x},{y},{value!r}")
    return "\n".join(lines) + "\n"


GRID_CSV = _grid_csv()

DIAGNOSIS_ARTIFACT_NAMES = {
    "metadata",
    "omnidirectional",
    "directional",
    "fitted_models",
    "anisotropy_candidates",
}


# ---------------------------------------------------------------------------
# 应用与链路夹具
# ---------------------------------------------------------------------------


def _make_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """完整集成应用：lifespan 自持 runtime/worker，无前端静态挂载。"""

    monkeypatch.setenv("GEOMODELING_DATA_DIR", str(tmp_path / "data"))
    settings = ApiSettings(
        config_path=Path("config/default.yaml"),
        metrics_json=None,
        evidence_dir=tmp_path / "evidence",
        frontend_dist=None,
        voxel_cache_dir=None,
    )
    monkeypatch.setattr("geomodeling.api.app.get_settings", lambda: settings)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    return app


def _prepare_dataset(client: TestClient, name: str) -> tuple[str, str]:
    resp = client.post("/api/cases", json={"name": name})
    assert resp.status_code == 201, resp.text
    case_id = resp.json()["id"]
    upload = client.post(
        f"/api/cases/{case_id}/datasets/uploads",
        files={"file": ("grid.csv", io.BytesIO(GRID_CSV.encode()), "application/octet-stream")},
    )
    assert upload.status_code == 201, upload.text
    dataset_id = upload.json()["id"]
    mapping = client.post(f"/api/datasets/{dataset_id}/mapping", json=MAPPING_2D)
    assert mapping.status_code == 200, mapping.text
    validated = client.post(f"/api/datasets/{dataset_id}/validate")
    assert validated.status_code == 200, validated.text
    return case_id, dataset_id


def _wait_job(client: TestClient, job_id: str, terminal: set[str], timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/analysis-jobs/{job_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        if body["status"] in terminal:
            return body
        time.sleep(0.1)
    raise AssertionError(f"analysis job {job_id} 未在 {timeout}s 内到达 {terminal}")


def _wait_run(client: TestClient, run_id: str, terminal: set[str], timeout: float = 90.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/runs/{run_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        if body["status"] in terminal:
            return body
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} 未在 {timeout}s 内到达 {terminal}")


def _run_experiment(client: TestClient, body: dict) -> str:
    """创建实验、发起 run 并等待成功，返回成功候选 id。"""

    created = client.post("/api/experiments", json=body)
    assert created.status_code == 201, created.text
    experiment_id = created.json()["id"]
    run = client.post(f"/api/experiments/{experiment_id}/runs")
    assert run.status_code == 201, run.text
    finished = _wait_run(client, run.json()["id"], {"succeeded", "failed"})
    assert finished["status"] == "succeeded", finished
    candidates = client.get(f"/api/experiments/{experiment_id}/candidates").json()["candidates"]
    succeeded = [candidate for candidate in candidates if candidate["status"] == "succeeded"]
    assert succeeded, candidates
    return succeeded[0]["id"]


def _experiment_body(
    case_id: str,
    dataset_id: str,
    *,
    name: str,
    algorithm: str,
    parameters: dict,
    confirmation_id: str | None = None,
    professional: bool = True,
) -> dict:
    body = {
        "case_id": case_id,
        "name": name,
        "algorithm": algorithm,
        "dataset_version_id": dataset_id,
        "search_mode": "manual",
        "parameters": parameters,
        "validation": VALIDATION,
    }
    if professional:
        body["neighborhood"] = NEIGHBORHOOD
        body["empirical_uncertainty"] = EMPIRICAL
    if confirmation_id is not None:
        body["professional_confirmation_id"] = confirmation_id
    return body


def _auto_confirm_body(fitted_models_sha256: str, *, note: str) -> dict:
    return {
        "model": "spherical",
        "parameter_strategy": "automatic_candidate",
        "fitted_models_sha256": fitted_models_sha256,
        "anisotropy": {"keep_isotropic": True},
        "note": note,
    }


@pytest.fixture(scope="class")
def diagnosis_api(tmp_path_factory):
    """一个数据版本 + 一条已成功诊断（worker 真实执行）。"""

    tmp_path = tmp_path_factory.mktemp("prof_diag_api")
    with pytest.MonkeyPatch.context() as monkeypatch:
        app = _make_app(tmp_path, monkeypatch)
        with TestClient(app) as client:
            case_id, dataset_id = _prepare_dataset(client, "专业诊断案例")
            created = client.post(
                f"/api/datasets/{dataset_id}/professional-diagnostics", json=DIAGNOSIS_CONFIG
            )
            assert created.status_code == 202, created.text
            payload = created.json()
            job = _wait_job(client, payload["job_id"], {"succeeded", "failed"})
            assert job["status"] == "succeeded", job
            yield SimpleNamespace(
                client=client,
                runtime=app.state.platform_runtime,
                case_id=case_id,
                dataset_id=dataset_id,
                diagnosis_id=payload["diagnosis_id"],
                job_id=payload["job_id"],
                created=payload,
            )


@pytest.fixture(scope="class")
def jobs_api(tmp_path_factory):
    """一个数据版本（不在 fixture 内创建任务，测试自行驱动生命周期）。"""

    tmp_path = tmp_path_factory.mktemp("prof_jobs_api")
    with pytest.MonkeyPatch.context() as monkeypatch:
        app = _make_app(tmp_path, monkeypatch)
        with TestClient(app) as client:
            case_id, dataset_id = _prepare_dataset(client, "分析任务案例")
            yield SimpleNamespace(
                client=client,
                runtime=app.state.platform_runtime,
                case_id=case_id,
                dataset_id=dataset_id,
            )


@pytest.fixture(scope="class")
def professional_api(tmp_path_factory):
    """全链路：诊断 → 双确认 → Kriging/IDW 专业候选（物化）+ legacy 候选 +
    未物化 Kriging 候选 + 第二数据版本候选 + 异常提取 + 兼容比较。"""

    tmp_path = tmp_path_factory.mktemp("prof_result_api")
    with pytest.MonkeyPatch.context() as monkeypatch:
        app = _make_app(tmp_path, monkeypatch)
        with TestClient(app) as client:
            ns = SimpleNamespace(client=client, runtime=app.state.platform_runtime)
            ns.case_id, ns.dataset_id = _prepare_dataset(client, "专业成果案例")

            created = client.post(
                f"/api/datasets/{ns.dataset_id}/professional-diagnostics", json=DIAGNOSIS_CONFIG
            )
            assert created.status_code == 202, created.text
            ns.diagnosis_id = created.json()["diagnosis_id"]
            job = _wait_job(client, created.json()["job_id"], {"succeeded", "failed"})
            assert job["status"] == "succeeded", job
            diagnosis = client.get(f"/api/professional-diagnostics/{ns.diagnosis_id}")
            assert diagnosis.status_code == 200, diagnosis.text
            fitted_sha = diagnosis.json()["manifest"]["artifacts"]["fitted_models"]["sha256"]

            auto = client.post(
                f"/api/professional-diagnostics/{ns.diagnosis_id}/confirm",
                json=_auto_confirm_body(fitted_sha, note="采纳自动候选"),
            )
            assert auto.status_code == 201, auto.text
            ns.auto_confirmation_id = auto.json()["id"]
            manual = client.post(
                f"/api/professional-diagnostics/{ns.diagnosis_id}/confirm",
                json={
                    "model": "spherical",
                    "parameter_strategy": "manual",
                    "manual_parameters": {"nugget": 0.05, "sill": 3.0, "range": 120.0},
                    "anisotropy": {"keep_isotropic": True},
                    "note": "人工固定参数",
                },
            )
            assert manual.status_code == 201, manual.text
            ns.manual_confirmation_id = manual.json()["id"]

            # Kriging 自动专业候选（物化）
            ns.kriging_result_id = _run_experiment(
                client,
                _experiment_body(
                    ns.case_id,
                    ns.dataset_id,
                    name="Kriging 自动",
                    algorithm="ordinary_kriging",
                    parameters={"neighbor_count": 8},
                    confirmation_id=ns.auto_confirmation_id,
                ),
            )
            metadata = client.post(f"/api/results/{ns.kriging_result_id}/materialize")
            assert metadata.status_code == 200, metadata.text
            ns.kriging_metadata = metadata.json()

            # IDW 专业候选（物化）
            ns.idw_result_id = _run_experiment(
                client,
                _experiment_body(
                    ns.case_id,
                    ns.dataset_id,
                    name="IDW 专业",
                    algorithm="idw",
                    parameters={"power": 2.0, "neighbor_count": 8},
                ),
            )
            idw_metadata = client.post(f"/api/results/{ns.idw_result_id}/materialize")
            assert idw_metadata.status_code == 200, idw_metadata.text

            # legacy IDW 候选（无专业上下文，物化）
            ns.legacy_result_id = _run_experiment(
                client,
                _experiment_body(
                    ns.case_id,
                    ns.dataset_id,
                    name="IDW legacy",
                    algorithm="idw",
                    parameters={"power": 2.0, "neighbor_count": 8},
                    professional=False,
                ),
            )
            legacy_metadata = client.post(f"/api/results/{ns.legacy_result_id}/materialize")
            assert legacy_metadata.status_code == 200, legacy_metadata.text
            assert "professional" not in legacy_metadata.json()

            # Kriging 人工策略专业候选（不物化）
            ns.kriging_unmat_result_id = _run_experiment(
                client,
                _experiment_body(
                    ns.case_id,
                    ns.dataset_id,
                    name="Kriging 人工",
                    algorithm="ordinary_kriging",
                    parameters={"neighbor_count": 8},
                    confirmation_id=ns.manual_confirmation_id,
                ),
            )

            # 第二数据版本（不兼容比较对）
            ns.case_b_id, ns.dataset_b_id = _prepare_dataset(client, "专业成果案例 B")
            ns.dataset_b_result_id = _run_experiment(
                client,
                _experiment_body(
                    ns.case_b_id,
                    ns.dataset_b_id,
                    name="B legacy",
                    algorithm="idw",
                    parameters={"power": 2.0, "neighbor_count": 8},
                    professional=False,
                ),
            )

            # 异常提取（阈值取值域低端，保证连通区非空）
            value_range = ns.kriging_metadata["value_range"]
            threshold = value_range[0] + 0.1 * (value_range[1] - value_range[0])
            ns.anomaly_body = {"direction": "high", "threshold": threshold}
            extraction = client.post(
                f"/api/results/{ns.kriging_result_id}/anomaly-extractions", json=ns.anomaly_body
            )
            assert extraction.status_code == 202, extraction.text
            ns.extraction_id = extraction.json()["extraction_id"]
            job = _wait_job(client, extraction.json()["job_id"], {"succeeded", "failed"})
            assert job["status"] == "succeeded", job

            # 兼容比较（Kriging × IDW，同数据同折分）
            comparison = client.post(
                "/api/professional-comparisons",
                json={
                    "first_result_id": ns.kriging_result_id,
                    "second_result_id": ns.idw_result_id,
                },
            )
            assert comparison.status_code == 201, comparison.text
            ns.comparison = comparison.json()
            yield ns


# ---------------------------------------------------------------------------
# 诊断端点
# ---------------------------------------------------------------------------


class TestDiagnosisEndpoints:
    def test_post_returns_202_with_job_identity(self, diagnosis_api):
        body = diagnosis_api.created
        assert body["diagnosis_id"] == diagnosis_api.diagnosis_id
        assert body["job_id"] == diagnosis_api.job_id
        assert body["status"] == "queued"
        assert body["reused"] is False
        assert_no_path_leak(body, "$.post_diagnosis")

    def test_polling_job_reports_subject_and_progress(self, diagnosis_api):
        resp = diagnosis_api.client.get(f"/api/analysis-jobs/{diagnosis_api.job_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["job_kind"] == "professional_diagnosis"
        assert body["subject_id"] == diagnosis_api.diagnosis_id
        assert body["status"] == "succeeded"
        assert body["progress"]["phase"] == "succeeded"
        assert body["error"] is None
        assert_no_path_leak(body, "$.job")

    def test_idempotent_repost_returns_existing_success(self, diagnosis_api):
        resp = diagnosis_api.client.post(
            f"/api/datasets/{diagnosis_api.dataset_id}/professional-diagnostics",
            json=DIAGNOSIS_CONFIG,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["reused"] is True
        assert body["diagnosis_id"] == diagnosis_api.diagnosis_id
        assert body["job_id"] is None
        assert body["status"] == "succeeded"

    def test_get_diagnosis_returns_manifest_summary_without_directory(self, diagnosis_api):
        resp = diagnosis_api.client.get(
            f"/api/professional-diagnostics/{diagnosis_api.diagnosis_id}"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "succeeded"
        assert len(body["fingerprint"]) == 64
        assert body["dataset_version_id"] == diagnosis_api.dataset_id
        assert body["error"] is None
        manifest = body["manifest"]
        assert "directory" not in json.dumps(manifest)
        artifacts = manifest["artifacts"]
        assert set(artifacts) == DIAGNOSIS_ARTIFACT_NAMES
        for entry in artifacts.values():
            assert set(entry) <= {"file", "sha256", "bytes"}
            assert len(entry["sha256"]) == 64
            assert entry["bytes"] > 0
        summary = manifest["summary"]
        assert summary["best_model"] in {"spherical", "exponential", "gaussian"}
        assert summary["omni_used_bin_count"] >= 4
        assert summary["direction_count"] == 2
        assert_no_path_leak(body, "$.diagnosis")

    def test_variogram_returns_bounded_omni_and_directional_bins(self, diagnosis_api):
        resp = diagnosis_api.client.get(
            f"/api/professional-diagnostics/{diagnosis_api.diagnosis_id}/variogram"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        omni = body["omnidirectional"]
        assert omni["total"] == 12
        assert omni["returned"] == 12
        assert omni["decimate"] == 1
        row = omni["rows"][0]
        for key in ("bin_index", "center_distance", "semivariance", "pair_count", "used_for_fit"):
            assert key in row
        directional = body["directional"]
        assert directional["total"] == 24
        assert {entry["direction_id"] for entry in directional["rows"]} == {"d000", "d001"}
        models = body["fitted_models"]["models"]
        assert {model["model"] for model in models} == {"spherical", "exponential", "gaussian"}
        assert body["anisotropy_candidates"]["candidates"]
        downloads = body["downloads"]
        assert downloads["omnidirectional"].startswith("/api/professional-artifacts/")
        assert downloads["directional"].startswith("/api/professional-artifacts/")
        assert_no_path_leak(body, "$.variogram")

    def test_variogram_decimate_bounds_inline_rows(self, diagnosis_api):
        resp = diagnosis_api.client.get(
            f"/api/professional-diagnostics/{diagnosis_api.diagnosis_id}/variogram",
            params={"decimate": 4},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["omnidirectional"]["returned"] == 3
        assert body["omnidirectional"]["decimate"] == 4
        assert body["omnidirectional"]["total"] == 12
        assert body["directional"]["returned"] == 6
        assert body["directional"]["total"] == 24

    def test_failed_diagnosis_blocks_variogram_and_confirm(self, diagnosis_api):
        client = diagnosis_api.client
        created = client.post(
            f"/api/datasets/{diagnosis_api.dataset_id}/professional-diagnostics",
            json=INSUFFICIENT_CONFIG,
        )
        assert created.status_code == 202, created.text
        diagnosis_id = created.json()["diagnosis_id"]
        job = _wait_job(client, created.json()["job_id"], {"succeeded", "failed"})
        assert job["status"] == "failed"
        assert job["error"]["code"] == VARIOGRAM_FIT_FAILED

        diagnosis = client.get(f"/api/professional-diagnostics/{diagnosis_id}")
        assert diagnosis.status_code == 200, diagnosis.text
        body = diagnosis.json()
        assert body["status"] == "failed"
        assert body["error"]["code"] == VARIOGRAM_FIT_FAILED
        assert body["manifest"] is None
        assert_no_path_leak(body, "$.failed_diagnosis")

        variogram = client.get(f"/api/professional-diagnostics/{diagnosis_id}/variogram")
        assert variogram.status_code == 409
        assert variogram.json()["error"]["code"] == "PROFESSIONAL_DIAGNOSIS_NOT_SUCCEEDED"

        confirm = client.post(
            f"/api/professional-diagnostics/{diagnosis_id}/confirm",
            json=_auto_confirm_body("0" * 64, note="失败诊断不可确认"),
        )
        assert confirm.status_code == 409
        assert confirm.json()["error"]["code"] == "PROFESSIONAL_DIAGNOSIS_NOT_SUCCEEDED"

    def test_confirm_creates_immutable_snapshot(self, diagnosis_api):
        client = diagnosis_api.client
        diagnosis = client.get(
            f"/api/professional-diagnostics/{diagnosis_api.diagnosis_id}"
        ).json()
        fitted_sha = diagnosis["manifest"]["artifacts"]["fitted_models"]["sha256"]
        resp = client.post(
            f"/api/professional-diagnostics/{diagnosis_api.diagnosis_id}/confirm",
            json=_auto_confirm_body(fitted_sha, note="API 确认快照"),
        )
        assert resp.status_code == 201, resp.text
        snapshot = resp.json()
        assert snapshot["id"]
        assert snapshot["diagnostic_id"] == diagnosis_api.diagnosis_id
        assert len(snapshot["fingerprint"]) == 64
        assert snapshot["note"] == "API 确认快照"
        assert snapshot["created_at"]
        assert_no_path_leak(snapshot, "$.confirm")

    def test_confirm_rejects_wrong_evidence_reference(self, diagnosis_api):
        client = diagnosis_api.client
        resp = client.post(
            f"/api/professional-diagnostics/{diagnosis_api.diagnosis_id}/confirm",
            json=_auto_confirm_body("0" * 64, note="伪造证据引用"),
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "PROFESSIONAL_CONFIRMATION_INVALID"

    def test_unknown_diagnosis_returns_404(self, diagnosis_api):
        client = diagnosis_api.client
        missing = client.get("/api/professional-diagnostics/no-such-diagnosis")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "PROFESSIONAL_DIAGNOSIS_NOT_FOUND"
        variogram = client.get("/api/professional-diagnostics/no-such-diagnosis/variogram")
        assert variogram.status_code == 404
        confirm = client.post(
            "/api/professional-diagnostics/no-such-diagnosis/confirm",
            json=_auto_confirm_body("0" * 64, note="不存在"),
        )
        assert confirm.status_code == 404
        assert confirm.json()["error"]["code"] == "PROFESSIONAL_DIAGNOSIS_NOT_FOUND"

    def test_invalid_config_rejected(self, diagnosis_api):
        resp = diagnosis_api.client.post(
            f"/api/datasets/{diagnosis_api.dataset_id}/professional-diagnostics",
            json={"variogram": {"lag_count": 999}},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "PROFESSIONAL_CONFIG_INVALID"

    def test_unknown_dataset_returns_404(self, diagnosis_api):
        resp = diagnosis_api.client.post(
            "/api/datasets/no-such-dataset/professional-diagnostics", json=DIAGNOSIS_CONFIG
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "DATASET_NOT_FOUND"


# ---------------------------------------------------------------------------
# analysis-jobs 生命周期（cancel 只改当前任务；retry 新身份且不改写原记录）
# ---------------------------------------------------------------------------


class TestAnalysisJobEndpoints:
    def test_cancel_queued_job_changes_only_current_job(self, jobs_api):
        # 经服务层直接落库（不入队），得到确定性的 queued 任务
        record = create_professional_diagnosis(
            jobs_api.runtime, jobs_api.dataset_id, DIAGNOSIS_CONFIG
        )
        jobs_api.canceled_job_id = record.job_id
        jobs_api.canceled_diagnosis_id = record.id

        resp = jobs_api.client.post(f"/api/analysis-jobs/{record.job_id}/cancel")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["id"] == record.job_id
        assert body["status"] == "canceled"
        assert_no_path_leak(body, "$.cancel_job")

        # 取消只影响当前任务：诊断行保持 queued，不产生工件
        diagnosis = jobs_api.client.get(f"/api/professional-diagnostics/{record.id}")
        assert diagnosis.status_code == 200, diagnosis.text
        assert diagnosis.json()["status"] == "queued"
        assert diagnosis.json()["manifest"] is None

        again = jobs_api.client.get(f"/api/analysis-jobs/{record.job_id}")
        assert again.json()["status"] == "canceled"

    def test_retry_creates_new_job_and_never_mutates_original(self, jobs_api):
        original = jobs_api.canceled_job_id
        resp = jobs_api.client.post(f"/api/analysis-jobs/{original}/retry")
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["id"] != original
        assert body["retry_of_job_id"] == original
        assert body["status"] == "queued"
        assert body["subject_id"] == jobs_api.canceled_diagnosis_id
        assert_no_path_leak(body, "$.retry_job")
        jobs_api.retried_job_id = body["id"]

        finished = _wait_job(jobs_api.client, body["id"], {"succeeded", "failed"})
        assert finished["status"] == "succeeded"

        # 原任务记录不被重试改写（状态与终态时间保持）
        prior = jobs_api.client.get(f"/api/analysis-jobs/{original}")
        assert prior.status_code == 200
        assert prior.json()["status"] == "canceled"
        assert prior.json()["retry_of_job_id"] is None

    def test_cancel_terminal_job_returns_409(self, jobs_api):
        resp = jobs_api.client.post(f"/api/analysis-jobs/{jobs_api.retried_job_id}/cancel")
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "ANALYSIS_JOB_NOT_CANCELABLE"

    def test_retry_succeeded_job_returns_409(self, jobs_api):
        resp = jobs_api.client.post(f"/api/analysis-jobs/{jobs_api.retried_job_id}/retry")
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "ANALYSIS_JOB_NOT_RETRYABLE"

    def test_unknown_job_returns_404(self, jobs_api):
        missing = jobs_api.client.get("/api/analysis-jobs/no-such-job")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "ANALYSIS_JOB_NOT_FOUND"
        canceled = jobs_api.client.post("/api/analysis-jobs/no-such-job/cancel")
        assert canceled.status_code == 404
        assert canceled.json()["error"]["code"] == "ANALYSIS_JOB_NOT_FOUND"
        retried = jobs_api.client.post("/api/analysis-jobs/no-such-job/retry")
        assert retried.status_code == 404
        assert retried.json()["error"]["code"] == "ANALYSIS_JOB_NOT_FOUND"


# ---------------------------------------------------------------------------
# 成果专业证据：professional / folds / residuals / uncertainty
# ---------------------------------------------------------------------------


class TestProfessionalResultEndpoints:
    def test_professional_returns_capabilities_provenance_and_manifest(self, professional_api):
        ns = professional_api
        resp = ns.client.get(f"/api/results/{ns.kriging_result_id}/professional")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["available"] is True
        assert body["algorithm"] == "ordinary_kriging"
        assert body["confirmation_id"] == ns.auto_confirmation_id
        assert body["capabilities"]["native_kriging_std"] == "supported"
        assert body["capabilities"]["empirical_error_scale"] == "supported"
        provenance = body["parameter_provenance"]
        assert provenance["final"]["origin"] == "final_full_data_fit"
        assert provenance["final"]["scope"] == "all_valid_rows"
        artifacts = body["manifest"]["artifacts"]
        for name in (
            "fold_assignments",
            "out_of_fold_predictions",
            "prediction_diagnostics",
            "empirical_error_scale",
            "kriging_standard_deviation",
            "neighborhood_summary",
            "metadata",
        ):
            assert name in artifacts, name
            assert set(artifacts[name]) <= {"file", "sha256", "bytes"}
        assert "directory" not in json.dumps(body)
        assert_no_path_leak(body, "$.professional")

    def test_idw_professional_capabilities_mark_kriging_std_not_applicable(self, professional_api):
        ns = professional_api
        resp = ns.client.get(f"/api/results/{ns.idw_result_id}/professional")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["available"] is True
        assert body["capabilities"]["native_kriging_std"] == "not_applicable"
        # 能力不适用：manifest 不登记空占位工件
        assert "kriging_standard_deviation" not in body["manifest"]["artifacts"]
        assert_no_path_leak(body, "$.professional_idw")

    def test_legacy_result_returns_unavailable_without_fabricated_values(self, professional_api):
        ns = professional_api
        resp = ns.client.get(f"/api/results/{ns.legacy_result_id}/professional")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # legacy 候选：明确不可用原因，绝不伪造零值指标或能力
        assert body == {
            "result_id": ns.legacy_result_id,
            "available": False,
            "reason": "LEGACY_RESULT_NOT_COMPUTED",
            "algorithm": "idw",
        }
        assert_no_path_leak(body, "$.professional_legacy")

    def test_professional_unknown_result_returns_404(self, professional_api):
        resp = professional_api.client.get("/api/results/no-such-result/professional")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "CANDIDATE_NOT_FOUND"

    def test_folds_return_counts_groups_leakage_and_metrics(self, professional_api):
        ns = professional_api
        resp = ns.client.get(f"/api/results/{ns.kriging_result_id}/folds")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["fold_count"] == 3
        assert body["leakage_detected"] is False
        validation_total = 0
        for fold in body["folds"]:
            assert fold["training_count"] > 0
            assert fold["validation_count"] > 0
            validation_total += fold["validation_count"]
            assert fold["leakage_detected"] is False
            assert fold["validation_groups"]
            assert fold["metrics"]["rmse"] is not None
            assert fold["metrics"]["valid_count"] > 0
        assert validation_total == GRID_POINT_COUNT
        assert_no_path_leak(body, "$.folds")

    def test_folds_available_for_legacy_candidate(self, professional_api):
        resp = professional_api.client.get(
            f"/api/results/{professional_api.legacy_result_id}/folds"
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["fold_count"] == 3

    def test_folds_unknown_result_returns_404(self, professional_api):
        resp = professional_api.client.get("/api/results/no-such-result/folds")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "CANDIDATE_NOT_FOUND"

    def test_residuals_inline_bounded_with_decimate_and_download(self, professional_api):
        ns = professional_api
        resp = ns.client.get(f"/api/results/{ns.kriging_result_id}/residuals")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == GRID_POINT_COUNT
        assert body["returned"] == GRID_POINT_COUNT
        assert body["decimate"] == 1
        for key in (
            "source_row",
            "fold_index",
            "observed",
            "predicted",
            "residual",
            "absolute_error",
            "is_nodata",
        ):
            assert len(body[key]) == GRID_POINT_COUNT, key
        assert sorted(set(body["fold_index"])) == [0, 1, 2]
        assert body["download_url"].startswith("/api/professional-artifacts/")
        assert_no_path_leak(body, "$.residuals")

        decimated = ns.client.get(
            f"/api/results/{ns.kriging_result_id}/residuals", params={"decimate": 4}
        )
        assert decimated.status_code == 200, decimated.text
        view = decimated.json()
        assert view["total"] == GRID_POINT_COUNT
        assert view["returned"] == GRID_POINT_COUNT // 4
        assert view["decimate"] == 4
        assert len(view["residual"]) == view["returned"]

    def test_residuals_unknown_result_returns_404(self, professional_api):
        resp = professional_api.client.get("/api/results/no-such-result/residuals")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "CANDIDATE_NOT_FOUND"

    def test_uncertainty_layers_bounded_for_kriging(self, professional_api):
        ns = professional_api
        empirical = ns.client.get(f"/api/results/{ns.kriging_result_id}/uncertainty/empirical_error")
        assert empirical.status_code == 200, empirical.text
        body = empirical.json()
        assert body["layer"] == "empirical_error"
        assert body["served_cell_count"] <= body["original_cell_count"]
        assert body["stride"] >= 1
        assert len(body["values"]) == body["served_cell_count"]
        assert_no_path_leak(body, "$.uncertainty_empirical")

        std = ns.client.get(f"/api/results/{ns.kriging_result_id}/uncertainty/kriging_std")
        assert std.status_code == 200, std.text
        assert std.json()["layer"] == "kriging_std"

    def test_uncertainty_kriging_std_not_applicable_for_idw(self, professional_api):
        resp = professional_api.client.get(
            f"/api/results/{professional_api.idw_result_id}/uncertainty/kriging_std"
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "PROFESSIONAL_CAPABILITY_NOT_APPLICABLE"

    def test_uncertainty_layer_not_materialized(self, professional_api):
        ns = professional_api
        # 专业候选未物化：网格未生成
        resp = ns.client.get(f"/api/results/{ns.kriging_unmat_result_id}/uncertainty/empirical_error")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "RESULT_NOT_MATERIALIZED"
        # legacy 候选已物化但无专业层
        legacy = ns.client.get(f"/api/results/{ns.legacy_result_id}/uncertainty/empirical_error")
        assert legacy.status_code == 404
        assert legacy.json()["error"]["code"] == "PROFESSIONAL_LAYER_NOT_MATERIALIZED"

    def test_uncertainty_unknown_kind_rejected(self, professional_api):
        resp = professional_api.client.get(
            f"/api/results/{professional_api.kriging_result_id}/uncertainty/banana"
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "PREVIEW_LAYER_UNKNOWN"


# ---------------------------------------------------------------------------
# 异常提取（202 + 任务身份 + 状态查询）
# ---------------------------------------------------------------------------


class TestAnomalyExtractionEndpoints:
    def test_extraction_get_returns_status_and_components_summary(self, professional_api):
        ns = professional_api
        resp = ns.client.get(f"/api/anomaly-extractions/{ns.extraction_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "succeeded"
        assert body["candidate_result_id"] == ns.kriging_result_id
        assert len(body["fingerprint"]) == 64
        assert body["error"] is None
        summary = body["manifest"]["summary"]
        assert summary["component_count"] >= 1
        assert summary["eligible_node_count"] >= 1
        assert "directory" not in json.dumps(body)
        components = body["components"]
        assert components["total"] == summary["component_count"]
        assert components["returned"] <= components["total"]
        first = components["rows"][0]
        assert "component_id" in first
        assert "support_node_count" in first
        assert_no_path_leak(body, "$.extraction")

    def test_repost_reuses_existing_success(self, professional_api):
        ns = professional_api
        resp = ns.client.post(
            f"/api/results/{ns.kriging_result_id}/anomaly-extractions", json=ns.anomaly_body
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["reused"] is True
        assert body["extraction_id"] == ns.extraction_id
        assert body["job_id"] is None

    def test_extraction_requires_materialized_result(self, professional_api):
        resp = professional_api.client.post(
            f"/api/results/{professional_api.kriging_unmat_result_id}/anomaly-extractions",
            json={"direction": "high", "threshold": 10.0},
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "RESULT_NOT_MATERIALIZED"

    def test_extraction_kriging_std_gate_unavailable_for_idw(self, professional_api):
        resp = professional_api.client.post(
            f"/api/results/{professional_api.idw_result_id}/anomaly-extractions",
            json={"direction": "high", "threshold": 10.0, "kriging_std_max": 1.0},
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "ANOMALY_UNCERTAINTY_UNAVAILABLE"

    def test_extraction_invalid_config_rejected(self, professional_api):
        resp = professional_api.client.post(
            f"/api/results/{professional_api.kriging_result_id}/anomaly-extractions",
            json={"direction": "sideways", "threshold": 10.0},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "PROFESSIONAL_CONFIG_INVALID"

    def test_extraction_unknown_result_returns_404(self, professional_api):
        resp = professional_api.client.post(
            "/api/results/no-such-result/anomaly-extractions",
            json={"direction": "high", "threshold": 10.0},
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "CANDIDATE_NOT_FOUND"

    def test_unknown_extraction_returns_404(self, professional_api):
        resp = professional_api.client.get("/api/anomaly-extractions/no-such-extraction")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "ANOMALY_EXTRACTION_NOT_FOUND"


# ---------------------------------------------------------------------------
# 双候选比较（幂等 fingerprint 查询）
# ---------------------------------------------------------------------------


class TestComparisonEndpoints:
    def test_compatible_pair_returns_metric_deltas_and_grid_difference(self, professional_api):
        body = professional_api.comparison
        assert body["compatible"] is True
        assert body["mismatches"] == []
        assert body["common_valid_count"] == GRID_POINT_COUNT
        assert set(body["metric_deltas"]) == {"mae", "rmse", "r2", "bias"}
        assert body["grid_difference_available"] is True
        assert body["grid_difference"]["common_valid_count"] > 0
        assert len(body["comparison_fingerprint"]) == 64
        assert body["first_result_id"] == professional_api.kriging_result_id
        assert body["second_result_id"] == professional_api.idw_result_id
        assert_no_path_leak(body, "$.comparison")

    def test_get_by_fingerprint_is_idempotent(self, professional_api):
        ns = professional_api
        fingerprint = ns.comparison["comparison_fingerprint"]
        resp = ns.client.get(f"/api/professional-comparisons/{fingerprint}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["comparison_fingerprint"] == fingerprint
        assert body["compatible"] is True
        assert body["metric_deltas"] == ns.comparison["metric_deltas"]
        assert_no_path_leak(body, "$.comparison_get")

        again = ns.client.post(
            "/api/professional-comparisons",
            json={
                "first_result_id": ns.kriging_result_id,
                "second_result_id": ns.idw_result_id,
            },
        )
        assert again.status_code == 201, again.text
        assert again.json()["comparison_fingerprint"] == fingerprint

    def test_incompatible_pair_never_shows_metric_deltas(self, professional_api):
        ns = professional_api
        resp = ns.client.post(
            "/api/professional-comparisons",
            json={
                "first_result_id": ns.kriging_result_id,
                "second_result_id": ns.dataset_b_result_id,
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["compatible"] is False
        assert "dataset_version_id" in body["mismatches"]
        assert body["metric_deltas"] is None
        assert body["common_valid_count"] is None
        assert body["grid_difference_available"] is False
        assert_no_path_leak(body, "$.comparison_incompatible")

        got = ns.client.get(f"/api/professional-comparisons/{body['comparison_fingerprint']}")
        assert got.status_code == 200, got.text
        assert got.json()["compatible"] is False

    def test_same_candidate_rejected(self, professional_api):
        resp = professional_api.client.post(
            "/api/professional-comparisons",
            json={
                "first_result_id": professional_api.kriging_result_id,
                "second_result_id": professional_api.kriging_result_id,
            },
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "COMPARISON_SAME_CANDIDATE"

    def test_unknown_comparison_returns_404(self, professional_api):
        resp = professional_api.client.get(f"/api/professional-comparisons/{'0' * 64}")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "COMPARISON_NOT_FOUND"

    def test_comparison_unknown_result_returns_404(self, professional_api):
        resp = professional_api.client.post(
            "/api/professional-comparisons",
            json={
                "first_result_id": professional_api.kriging_result_id,
                "second_result_id": "no-such-result",
            },
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "CANDIDATE_NOT_FOUND"


# ---------------------------------------------------------------------------
# 白名单工件下载（只接受已登记身份，路径从 manifest 解析）
# ---------------------------------------------------------------------------


class TestArtifactDownload:
    def test_download_resolves_registered_identities(self, professional_api):
        ns = professional_api
        client = ns.client
        professional = client.get(f"/api/results/{ns.kriging_result_id}/professional").json()
        expected = professional["manifest"]["artifacts"]["out_of_fold_predictions"]["sha256"]
        resp = client.get(
            f"/api/professional-artifacts/result:{ns.kriging_result_id}:out_of_fold_predictions/download"
        )
        assert resp.status_code == 200, resp.text
        assert hashlib.sha256(resp.content).hexdigest() == expected

        diagnosis = client.get(
            f"/api/professional-artifacts/diagnosis:{ns.diagnosis_id}:omnidirectional/download"
        )
        assert diagnosis.status_code == 200, diagnosis.text
        assert "semivariance" in diagnosis.text.splitlines()[0]

        extraction = client.get(
            f"/api/professional-artifacts/extraction:{ns.extraction_id}:components/download"
        )
        assert extraction.status_code == 200, extraction.text
        assert "component_id" in extraction.text.splitlines()[0]

    def test_download_rejects_unregistered_identities(self, professional_api):
        ns = professional_api
        client = ns.client
        base = "/api/professional-artifacts"
        cases = [
            # 未登记逻辑名
            f"{base}/result:{ns.kriging_result_id}:bogus/download",
            # IDW 能力不适用：无 Kriging 标准差工件登记（绝不给空占位）
            f"{base}/result:{ns.idw_result_id}:kriging_standard_deviation/download",
            # 未知 subject
            f"{base}/result:no-such-result:out_of_fold_predictions/download",
            f"{base}/diagnosis:no-such-diagnosis:omnidirectional/download",
            f"{base}/extraction:no-such-extraction:components/download",
            # 未知类别
            f"{base}/hack:{ns.kriging_result_id}:out_of_fold_predictions/download",
            # 畸形身份（段数不符）
            f"{base}/result:{ns.kriging_result_id}/download",
            # Windows 形态路径遍历：到达处理器但绝不拼接客户端输入
            f"{base}/result:{ns.kriging_result_id}:..%5C..%5Csecret/download",
        ]
        for url in cases:
            resp = client.get(url)
            assert resp.status_code == 404, url
            assert resp.json()["error"]["code"] == "PROFESSIONAL_ARTIFACT_NOT_FOUND", url
        # POSIX 形态路径遍历：URL 规范化后路由不命中，同样 404（绝不返回文件）
        for url in (
            f"{base}/result:{ns.kriging_result_id}:../secret/download",
            f"{base}/result:{ns.kriging_result_id}:..%2F..%2Fsecret/download",
        ):
            assert client.get(url).status_code == 404, url

    def test_download_pending_subject_not_registered(self, professional_api):
        ns = professional_api
        # 未物化 Kriging 候选：run 期 manifest 不含不确定性层
        resp = ns.client.get(
            f"/api/professional-artifacts/result:{ns.kriging_unmat_result_id}:empirical_error_scale/download"
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "PROFESSIONAL_ARTIFACT_NOT_FOUND"
        # run 期已登记的折证据仍可下载
        resp = ns.client.get(
            f"/api/professional-artifacts/result:{ns.kriging_unmat_result_id}:fold_assignments/download"
        )
        assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# 归属链：确认快照与实验数据版本不一致 409；IDW 确认 409
# ---------------------------------------------------------------------------


class TestOwnershipChain:
    def test_confirmation_from_other_dataset_rejected(self, professional_api):
        ns = professional_api
        body = _experiment_body(
            ns.case_b_id,
            ns.dataset_b_id,
            name="错误数据版本",
            algorithm="ordinary_kriging",
            parameters={"neighbor_count": 8},
            confirmation_id=ns.auto_confirmation_id,
        )
        resp = ns.client.post("/api/experiments", json=body)
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "PROFESSIONAL_CONFIRMATION_DATASET_MISMATCH"

    def test_idw_with_confirmation_rejected(self, professional_api):
        ns = professional_api
        body = _experiment_body(
            ns.case_id,
            ns.dataset_id,
            name="IDW 携带确认",
            algorithm="idw",
            parameters={"power": 2.0, "neighbor_count": 8},
            confirmation_id=ns.auto_confirmation_id,
        )
        resp = ns.client.post("/api/experiments", json=body)
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "PROFESSIONAL_CAPABILITY_NOT_APPLICABLE"
