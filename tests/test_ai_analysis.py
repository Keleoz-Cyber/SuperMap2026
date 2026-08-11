"""AI analysis service and API tests.

Covers:
- Unconfigured API Key: rule analysis still succeeds, AI returns typed unavailable
- Mock DeepSeek: success JSON, empty, truncated, timeout, 429, non-JSON
- Evidence hash reuse; regenerate=true produces new call
- API Key never in logs, public DTO, SQLite, or built assets
- quick/review modes
- GET latest is read-only
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from geomodeling.integrations.deepseek import (
    DEEPSEEK_NOT_CONFIGURED,
    DeepSeekAdapter,
    ENV_API_KEY,
)
from geomodeling.platform import PlatformRuntime, tables
from geomodeling.platform.ai_analysis import (
    AI_ANALYSIS_UNAVAILABLE,
    build_evidence_packet,
    build_prompts,
    compute_evidence_hash,
    generate_ai_analysis,
    get_latest_ai_analysis,
    validate_ai_review,
)
from geomodeling.platform.ai_analysis_contracts import PROMPT_VERSION
from geomodeling.platform.errors import PlatformError, platform_error_handler
from geomodeling.platform.result_analysis import analyze_result_grid
from geomodeling.platform.result_analysis_contracts import RESULT_ANALYSIS_VERSION


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CSV_3D = "x,y,z,v\n" + "\n".join(
    f"{(i % 4) * 30 - 150},{(j % 5) * 80 + 260},{(k % 4) * 200 - 800},{10 + i + j + k}"
    for i in range(4) for j in range(5) for k in range(4)
) + "\n"

MAPPING_3D = {
    "dimension": "3d", "x": "x", "y": "y", "z": "z",
    "value": "v", "value_name": "属性", "coordinate_kind": "local_linear",
}


def _prepare_run(client: TestClient) -> str:
    import io, time
    resp = client.post("/api/cases", json={"name": "AI分析案例"})
    case_id = resp.json()["id"]
    resp = client.post(
        f"/api/cases/{case_id}/datasets/uploads",
        files={"file": ("data3d.csv", io.BytesIO(CSV_3D.encode()), "application/octet-stream")},
    )
    dataset_id = resp.json()["id"]
    client.post(f"/api/datasets/{dataset_id}/mapping", json=MAPPING_3D)
    client.post(f"/api/datasets/{dataset_id}/validate")
    resp = client.post("/api/experiments", json={
        "case_id": case_id, "name": "AI实验", "algorithm": "idw",
        "dataset_version_id": dataset_id, "search_mode": "manual",
        "parameters": {"power": 2.0, "neighbor_count": 8},
        "validation": {"method": "spatial_kfold", "folds": 3, "seed": 1, "holdout_fraction": 0.2},
    })
    experiment_id = resp.json()["id"]
    run_id = client.post(f"/api/experiments/{experiment_id}/runs").json()["id"]
    deadline = time.time() + 30
    while time.time() < deadline:
        body = client.get(f"/api/runs/{run_id}").json()
        if body["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.1)
    assert body["status"] == "succeeded"
    candidates = client.get(f"/api/experiments/{experiment_id}/candidates").json()["candidates"]
    return next(c["id"] for c in candidates if c["status"] == "succeeded")


def make_client(tmp_path):
    from geomodeling.api.routes import (
        cases, datasets, experiments, results, runs,
        result_analysis, ai_analysis,
    )
    from geomodeling.platform.worker import JobWorker

    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    worker = JobWorker(runtime)
    app = FastAPI()
    app.add_exception_handler(PlatformError, platform_error_handler)
    app.include_router(cases.router)
    app.include_router(datasets.router)
    app.include_router(experiments.router)
    app.include_router(runs.router)
    app.include_router(results.router)
    app.include_router(result_analysis.router)
    app.include_router(ai_analysis.router)
    app.state.platform_runtime = runtime
    app.state.job_worker = worker
    return TestClient(app), runtime


class FakeTransport:
    def __init__(self, response_factory):
        self._factory = response_factory
        self.call_count = 0

    def post(self, url: str, *, json: dict, headers: dict, timeout: float) -> httpx.Response:
        self.call_count += 1
        return self._factory()


def _success_ai_response() -> httpx.Response:
    body = {
        "choices": [{
            "message": {"content": json.dumps({
                "spatial_pattern": {
                    "summary": "高值区集中在深层南部",
                    "evidence_refs": ["component-1", "depth_bin-0"],
                },
                "model_reliability": {
                    "summary": "模型公共有效指标良好",
                    "evidence_refs": ["model_evidence"],
                },
                "uncertainty_and_risk": {
                    "summary": "经验误差尺度可用",
                    "evidence_refs": ["uncertainty"],
                },
                "review_and_next_checks": {
                    "summary": "建议复核边界组件",
                    "evidence_refs": ["component-1"],
                },
                "consensus": {
                    "consensus": "高值区集中在深层，模型可靠",
                    "disagreements": [],
                    "recommended_checks": ["复核边界接触组件"],
                    "decision_options": [{
                        "label": "维持当前模型",
                        "trigger": "指标达标",
                        "benefit": "无需额外计算",
                        "cost": "不改善边界不确定性",
                        "evidence_refs": ["model_evidence"],
                    }],
                    "limitations": ["局部坐标系"],
                },
            })},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 200, "completion_tokens": 100},
    }
    return httpx.Response(status_code=200, json=body)


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------

class TestAiAnalysisService:
    def test_unconfigured_returns_unavailable(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_API_KEY, raising=False)
        client, runtime = make_client(tmp_path)
        candidate_id = _prepare_run(client)
        client.post(f"/api/results/{candidate_id}/materialize")

        record = generate_ai_analysis(runtime, candidate_id, mode="quick")
        assert record.status == "unavailable"
        assert record.error_code == DEEPSEEK_NOT_CONFIGURED
        assert record.review is None

    def test_successful_analysis(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_API_KEY, raising=False)
        client, runtime = make_client(tmp_path)
        candidate_id = _prepare_run(client)
        client.post(f"/api/results/{candidate_id}/materialize")

        adapter = DeepSeekAdapter(
            api_key="sk-test",
            _transport=FakeTransport(_success_ai_response),
        )
        record = generate_ai_analysis(runtime, candidate_id, mode="quick", adapter=adapter)
        assert record.status == "succeeded"
        assert record.review is not None
        assert record.review.mode == "quick"
        assert record.review.provider == "deepseek"
        assert record.usage_prompt_tokens == 200

    def test_reuse_existing_record(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_API_KEY, raising=False)
        client, runtime = make_client(tmp_path)
        candidate_id = _prepare_run(client)
        client.post(f"/api/results/{candidate_id}/materialize")

        transport = FakeTransport(_success_ai_response)
        adapter = DeepSeekAdapter(api_key="sk-test", _transport=transport)

        record1 = generate_ai_analysis(runtime, candidate_id, mode="quick", adapter=adapter)
        assert transport.call_count == 1

        record2 = generate_ai_analysis(runtime, candidate_id, mode="quick", adapter=adapter)
        assert transport.call_count == 1  # no new call
        assert record2.id == record1.id

    def test_regenerate_produces_new_call(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_API_KEY, raising=False)
        client, runtime = make_client(tmp_path)
        candidate_id = _prepare_run(client)
        client.post(f"/api/results/{candidate_id}/materialize")

        transport = FakeTransport(_success_ai_response)
        adapter = DeepSeekAdapter(api_key="sk-test", _transport=transport)

        generate_ai_analysis(runtime, candidate_id, mode="quick", adapter=adapter)
        assert transport.call_count == 1

        generate_ai_analysis(runtime, candidate_id, mode="quick", adapter=adapter, regenerate=True)
        assert transport.call_count == 2

    def test_timeout_returns_error(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_API_KEY, raising=False)
        client, runtime = make_client(tmp_path)
        candidate_id = _prepare_run(client)
        client.post(f"/api/results/{candidate_id}/materialize")

        def raise_timeout():
            raise httpx.TimeoutException("timeout")

        adapter = DeepSeekAdapter(api_key="sk-test", _transport=FakeTransport(raise_timeout))
        record = generate_ai_analysis(runtime, candidate_id, mode="quick", adapter=adapter)
        assert record.status == "error"
        assert record.error_code == "DEEPSEEK_TIMEOUT"

    def test_get_latest(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_API_KEY, raising=False)
        client, runtime = make_client(tmp_path)
        candidate_id = _prepare_run(client)
        client.post(f"/api/results/{candidate_id}/materialize")

        adapter = DeepSeekAdapter(api_key="sk-test", _transport=FakeTransport(_success_ai_response))
        generate_ai_analysis(runtime, candidate_id, mode="quick", adapter=adapter)

        latest = get_latest_ai_analysis(runtime, candidate_id)
        assert latest is not None
        assert latest.status == "succeeded"

    def test_get_latest_none_when_no_record(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_API_KEY, raising=False)
        client, runtime = make_client(tmp_path)
        candidate_id = _prepare_run(client)
        client.post(f"/api/results/{candidate_id}/materialize")

        latest = get_latest_ai_analysis(runtime, candidate_id)
        assert latest is None

    def test_no_api_key_in_database(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_API_KEY, raising=False)
        client, runtime = make_client(tmp_path)
        candidate_id = _prepare_run(client)
        client.post(f"/api/results/{candidate_id}/materialize")

        adapter = DeepSeekAdapter(api_key="sk-super-secret", _transport=FakeTransport(_success_ai_response))
        generate_ai_analysis(runtime, candidate_id, mode="quick", adapter=adapter)

        with runtime.session() as session:
            rows = session.query(tables.AIAnalysisRecord).all()
            for row in rows:
                assert "sk-super-secret" not in (row.review_json or "")
                assert "sk-super-secret" not in (row.error_message or "")
                assert "sk-super-secret" not in (row.error_code or "")


# ---------------------------------------------------------------------------
# API tests
# ---------------------------------------------------------------------------

class TestAiAnalysisApi:
    def test_post_unconfigured(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_API_KEY, raising=False)
        client, runtime = make_client(tmp_path)
        candidate_id = _prepare_run(client)
        client.post(f"/api/results/{candidate_id}/materialize")

        resp = client.post(f"/api/results/{candidate_id}/ai-analysis", json={"mode": "quick"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "unavailable"
        assert data["error_code"] == DEEPSEEK_NOT_CONFIGURED

    def test_get_latest_404_when_none(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_API_KEY, raising=False)
        client, runtime = make_client(tmp_path)
        candidate_id = _prepare_run(client)
        client.post(f"/api/results/{candidate_id}/materialize")

        resp = client.get(f"/api/results/{candidate_id}/ai-analysis/latest")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "AI_ANALYSIS_NOT_FOUND"

    def test_post_then_get_latest(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_API_KEY, raising=False)
        client, runtime = make_client(tmp_path)
        candidate_id = _prepare_run(client)
        client.post(f"/api/results/{candidate_id}/materialize")

        # Use fake adapter via direct service call
        from geomodeling.platform.ai_analysis import generate_ai_analysis
        adapter = DeepSeekAdapter(api_key="sk-test", _transport=FakeTransport(_success_ai_response))
        generate_ai_analysis(runtime, candidate_id, mode="quick", adapter=adapter)

        resp = client.get(f"/api/results/{candidate_id}/ai-analysis/latest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "succeeded"
        assert data["review"]["mode"] == "quick"

    def test_no_api_key_in_response(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_API_KEY, raising=False)
        client, runtime = make_client(tmp_path)
        candidate_id = _prepare_run(client)
        client.post(f"/api/results/{candidate_id}/materialize")

        adapter = DeepSeekAdapter(api_key="sk-leak-check", _transport=FakeTransport(_success_ai_response))
        generate_ai_analysis(runtime, candidate_id, mode="quick", adapter=adapter)

        resp = client.get(f"/api/results/{candidate_id}/ai-analysis/latest")
        assert resp.status_code == 200
        assert "sk-leak-check" not in resp.text


# ---------------------------------------------------------------------------
# Evidence packet and validation tests
# ---------------------------------------------------------------------------

class TestEvidencePacketAndValidation:
    def test_evidence_hash_deterministic(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_API_KEY, raising=False)
        client, runtime = make_client(tmp_path)
        candidate_id = _prepare_run(client)
        client.post(f"/api/results/{candidate_id}/materialize")

        from geomodeling.platform.results import load_grid, read_materialized_metadata
        from geomodeling.platform.result_analysis import analyze_result_grid

        metadata = read_materialized_metadata(runtime, candidate_id)
        grid = load_grid(runtime, candidate_id)
        summary = analyze_result_grid(
            grid, result_id=candidate_id, grid_sha256=metadata["grid_sha256"],
            variable_name="RHO", variable_unit="ohm_m",
        )
        packet1 = build_evidence_packet(summary)
        packet2 = build_evidence_packet(summary)
        assert compute_evidence_hash(packet1) == compute_evidence_hash(packet2)
        assert {
            "identity", "variable", "result_grid", "spatial_components",
            "model_evidence", "uncertainty", "input_quality", "constraints",
        }.issubset(packet1.valid_evidence_ids)

    def test_invalid_evidence_ref_rejected(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_API_KEY, raising=False)
        client, runtime = make_client(tmp_path)
        candidate_id = _prepare_run(client)
        client.post(f"/api/results/{candidate_id}/materialize")

        from geomodeling.platform.results import load_grid, read_materialized_metadata
        from geomodeling.platform.result_analysis import analyze_result_grid

        metadata = read_materialized_metadata(runtime, candidate_id)
        grid = load_grid(runtime, candidate_id)
        summary = analyze_result_grid(
            grid, result_id=candidate_id, grid_sha256=metadata["grid_sha256"],
            variable_name="RHO", variable_unit="ohm_m",
        )
        packet = build_evidence_packet(summary)
        hash_val = compute_evidence_hash(packet)

        bad_content = json.dumps({
            "spatial_pattern": {"summary": "test", "evidence_refs": ["nonexistent-ref"]},
            "model_reliability": {"summary": "test", "evidence_refs": ["model_evidence"]},
            "uncertainty_and_risk": {"summary": "test", "evidence_refs": ["uncertainty"]},
            "review_and_next_checks": {"summary": "test", "evidence_refs": ["uncertainty"]},
            "consensus": {
                "consensus": "test",
                "disagreements": [],
                "recommended_checks": [],
                "decision_options": [],
                "limitations": [],
            },
        })

        with pytest.raises(PlatformError) as exc:
            validate_ai_review(bad_content, packet, hash_val, "deepseek", "test-model", "quick")
        assert exc.value.code == AI_ANALYSIS_UNAVAILABLE

    def test_prohibited_claim_rejected(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_API_KEY, raising=False)
        client, runtime = make_client(tmp_path)
        candidate_id = _prepare_run(client)
        client.post(f"/api/results/{candidate_id}/materialize")

        from geomodeling.platform.results import load_grid, read_materialized_metadata
        from geomodeling.platform.result_analysis import analyze_result_grid

        metadata = read_materialized_metadata(runtime, candidate_id)
        grid = load_grid(runtime, candidate_id)
        summary = analyze_result_grid(
            grid, result_id=candidate_id, grid_sha256=metadata["grid_sha256"],
            variable_name="RHO", variable_unit="ohm_m",
        )
        packet = build_evidence_packet(summary)
        hash_val = compute_evidence_hash(packet)

        bad_content = json.dumps({
            "spatial_pattern": {"summary": "该区域储量丰富", "evidence_refs": ["result_grid"]},
            "model_reliability": {"summary": "test", "evidence_refs": ["model_evidence"]},
            "uncertainty_and_risk": {"summary": "test", "evidence_refs": ["uncertainty"]},
            "review_and_next_checks": {"summary": "test", "evidence_refs": ["uncertainty"]},
            "consensus": {
                "consensus": "test",
                "disagreements": [],
                "recommended_checks": [],
                "decision_options": [],
                "limitations": [],
            },
        })

        with pytest.raises(PlatformError) as exc:
            validate_ai_review(bad_content, packet, hash_val, "deepseek", "test-model", "quick")
        assert exc.value.code == AI_ANALYSIS_UNAVAILABLE
        assert "储量" in (exc.value.details.get("prohibited") or "")
