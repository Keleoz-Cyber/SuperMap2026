"""Merge-blocker 1: public responses must never leak internal filesystem paths.

Every dataset/export/publication response uses whitelist DTOs; nested
free-form payloads (profile/evidence/manifest) are scrubbed recursively.
The assertion helper fails on denylisted keys *and* on any absolute-path
string value at any depth.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from test_experiment_api import CSV_2D, MAPPING_2D
from test_platform_results import make_client

PATH_KEYS = {
    "source_path",
    "standardized_path",
    "grid_path",
    "package_path",
    "predictions_path",
    # v0.6：内部 manifest 的 directory 绝对路径同样绝不外传
    "directory",
}


def assert_no_path_leak(value: Any, trail: str = "$") -> None:
    """递归断言：无路径键名、无绝对路径形态字符串值。"""

    if isinstance(value, dict):
        for key, item in value.items():
            assert key not in PATH_KEYS, f"{trail}.{key} 泄露内部路径键"
            assert_no_path_leak(item, f"{trail}.{key}")
    elif isinstance(value, (list, tuple)):
        for idx, item in enumerate(value):
            assert_no_path_leak(item, f"{trail}[{idx}]")
    elif isinstance(value, str):
        head = value[:2]
        assert not (len(value) >= 2 and value[1] == ":" and value[0].isalpha()), f"{trail} 泄露盘符路径：{value!r}"
        is_download_url = value.startswith("/api/")
        assert is_download_url or not value.startswith(("\\\\", "/")), f"{trail} 泄露绝对路径：{value!r}"
        assert head != "~" or not value.startswith("~/"), f"{trail} 泄露用户目录：{value!r}"


def prepare_validated_dataset(client) -> tuple[str, str]:
    case_id = client.post("/api/cases", json={"name": "DTO 案例"}).json()["id"]
    upload = client.post(
        f"/api/cases/{case_id}/datasets/uploads",
        files={"file": ("data.csv", io.BytesIO(CSV_2D.encode()), "application/octet-stream")},
    )
    assert upload.status_code == 201, upload.text
    dataset_id = upload.json()["id"]
    assert_no_path_leak(upload.json(), "$.upload")
    assert client.post(f"/api/datasets/{dataset_id}/mapping", json=MAPPING_2D).status_code == 200
    assert client.post(f"/api/datasets/{dataset_id}/validate").status_code == 200
    return case_id, dataset_id


def test_dataset_endpoints_use_whitelist_dto(tmp_path):
    client, _ = make_client(tmp_path)
    case_id, dataset_id = prepare_validated_dataset(client)

    mapping = client.post(f"/api/datasets/{dataset_id}/mapping", json=MAPPING_2D)
    assert mapping.status_code == 200
    assert_no_path_leak(mapping.json(), "$.mapping")

    get_resp = client.get(f"/api/datasets/{dataset_id}")
    assert get_resp.status_code == 200
    assert_no_path_leak(get_resp.json(), "$.get_dataset")

    inspection = client.get(f"/api/datasets/{dataset_id}/inspection")
    assert inspection.status_code == 200
    assert_no_path_leak(inspection.json(), "$.inspection")

    listing = client.get(f"/api/cases/{case_id}/datasets")
    assert listing.status_code == 200
    assert_no_path_leak(listing.json(), "$.case_datasets")

    points = client.get(f"/api/datasets/{dataset_id}/points")
    assert points.status_code == 200
    assert_no_path_leak(points.json(), "$.points")


def test_export_and_publication_responses_have_no_internal_paths(tmp_path):
    import time

    client, _ = make_client(tmp_path)
    case_id, dataset_id = prepare_validated_dataset(client)
    experiment = client.post("/api/experiments", json={
        "case_id": case_id,
        "name": "DTO 实验",
        "algorithm": "idw",
        "dataset_version_id": dataset_id,
        "search_mode": "manual",
        "parameters": {"power": 2.0, "neighbor_count": 4},
        "validation": {"method": "spatial_kfold", "folds": 3, "seed": 1, "holdout_fraction": 0.2},
    })
    experiment_id = experiment.json()["id"]
    run_id = client.post(f"/api/experiments/{experiment_id}/runs").json()["id"]
    deadline = time.time() + 30
    while time.time() < deadline:
        body = client.get(f"/api/runs/{run_id}").json()
        if body["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.1)
    assert body["status"] == "succeeded"
    candidate = client.get(f"/api/experiments/{experiment_id}/candidates").json()["candidates"][0]

    materialized = client.get(f"/api/results/{candidate['id']}")
    assert materialized.status_code == 200, materialized.text
    assert_no_path_leak(materialized.json(), "$.result_metadata")

    export = client.post(f"/api/results/{candidate['id']}/exports")
    assert export.status_code == 201, export.text
    assert_no_path_leak(export.json(), "$.export")

    publication = client.post(f"/api/results/{candidate['id']}/publications")
    assert publication.status_code == 201, publication.text
    body = publication.json()
    assert_no_path_leak(body, "$.publication")
    # 发布证据只能给资源 ID 或下载 URL，不给服务器文件路径
    assert body["evidence"]["download_url"] == f"/api/exports/{body['export_id']}/download"
    assert "package" not in body["evidence"]


def test_microseismic_profile_and_derivation_dtos_never_leak_paths():
    """v0.5: public_dataset / public_derivation 对微震 profile 与派生报告递归脱敏。"""

    from types import SimpleNamespace

    from geomodeling.platform.public_dto import public_dataset, public_derivation

    record = SimpleNamespace(
        id="ds-1",
        case_id="case-1",
        version=1,
        status="mapped",
        created_at="2026-07-25T00:00:00+00:00",
        profile={
            "source_kind": "microseismic_dat_bundle",
            "dimension": "3d",
            "mapping": {"dimension": "3d", "value": "VX_KM_S", "value_unit": "km/s"},
            "rule_version": "microseismic_api_synthetic_v0.5",
            "layer_counts": {"source_records": 45, "aggregated_nodes": 44},
            "golden": {"passed": True, "checks": []},
            "standardized_path": "D:/abs/standardized.parquet",
            "source_files": [
                {
                    "file_name": "W1.dat",
                    "sha256": "a" * 64,
                    "point_id": "W1",
                    "line_id": "L1",
                    "source_record_count": 2,
                    "note": "C:/tmp/W1.dat",
                },
                {
                    "file_name": "W2.dat",
                    "sha256": "b" * 64,
                    "point_id": "W2",
                    "line_id": "L1",
                    "source_record_count": 3,
                },
            ],
            "derivation_report": "derived/derivation_report.json",
        },
    )

    dataset_body = public_dataset(record)
    assert_no_path_leak(dataset_body, "$.microseismic_dataset")
    assert "standardized_path" not in dataset_body["profile"]
    assert dataset_body["profile"]["source_files"][0]["note"] == "<redacted-path>"

    report = {
        "rule_version": "microseismic_api_synthetic_v0.5",
        "adapter_version": "0.5.0",
        "aggregation_method": "arithmetic_mean_exact_xyz",
        "layer_counts": {"source_records": 45, "accepted_modeling": 44, "aggregated_nodes": 44},
        "three_sigma": {"threshold": 3.0, "ddof": 1},
        "aggregation": {"conflict_group_count": 0, "conflict_row_count": 0, "collapsed_row_count": 0},
        "coordinates": {"vx_unit": "km/s", "evidence": "D:/abs/evidence.txt"},
        "golden": {
            "passed": True,
            "checks": [
                {
                    "name": "accepted_count",
                    "passed": True,
                    "expected": 44,
                    "actual": 44,
                    "grid_path": "/tmp/internal/grid.npz",
                }
            ],
        },
        "validation_passed": True,
        "downstream_gates": {"geometry_blocked": False},
        "artifacts": {
            "accepted_modeling": {
                "file": "accepted_modeling_44.csv",
                "rows": 44,
                "sha256": "c" * 64,
                "package_path": "C:/pkg/internal.zip",
            }
        },
        # 非白名单顶层键（含路径键与服务器目录）不得出现在公开 DTO
        "output_dir": "D:/should/not/appear",
        "source_path": "/internal/source_manifest.json",
    }

    body = public_derivation(record, report)
    assert_no_path_leak(body, "$.public_derivation")
    assert body["dataset_id"] == "ds-1"
    assert body["case_id"] == "case-1"
    assert body["status"] == "mapped"
    assert body["line_counts"] == {"L1": 5}
    assert "output_dir" not in body
    assert "source_path" not in body
    assert body["golden"]["checks"][0] == {
        "name": "accepted_count",
        "passed": True,
        "expected": 44,
        "actual": 44,
    }
    assert body["coordinates"]["evidence"] == "<redacted-path>"
    assert body["artifacts"]["accepted_modeling"]["file"] == "accepted_modeling_44.csv"
    assert "package_path" not in body["artifacts"]["accepted_modeling"]


def test_legacy_resistivity_responses_have_no_absolute_paths(tmp_path, monkeypatch):
    """Merge-blocker 4: legacy points/detail/voxel 响应也不得含本机绝对路径。"""

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from geomodeling.api.app import create_app
    from geomodeling.api.deps import ApiSettings, get_app_config, get_iserver_client, get_settings
    from geomodeling.api import case_service
    from test_api import FakeIServer, make_config

    fixture_csv = Path("tests/fixtures/rho_tiny_validation.csv").resolve()
    config = make_config(standardized=fixture_csv)

    settings = ApiSettings(
        config_path=Path("config/default.yaml"),
        metrics_json=(tmp_path / "m.json"),
        evidence_dir=tmp_path / "evidence",
        frontend_dist=None,
        voxel_cache_dir=tmp_path / "cache",
    )
    (tmp_path / "m.json").write_text('{"summaries": {}}', encoding="utf-8")

    # voxel 取数路径 mock 掉（契约细节由 test_s3mb 覆盖），这里只查路径泄露
    monkeypatch.setattr(
        case_service,
        "_voxel_cells_cached",
        lambda service_url, contract, manifest, timeout: {
            "cells": [],
            "tile_files": 0,
            "fetched_bytes": 0,
            "service_url": service_url,
            "summary": {"x_range": [0, 1], "y_range": [0, 1], "z_range": [0, 1], "value_range": [0, 1]},
            "contract": {"scp": {}, "cells": {}, "manifest": {}},
        },
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_app_config] = lambda: config
    app.dependency_overrides[get_iserver_client] = lambda: FakeIServer({})
    from geomodeling.platform import PlatformRuntime

    runtime = PlatformRuntime(tmp_path / "data")
    runtime.initialize()
    app.state.platform_runtime = runtime
    client = TestClient(app)

    points = client.get("/api/cases/resistivity/points")
    assert points.status_code == 200, points.text
    body = points.json()
    assert "source_path" not in body
    assert body["source_label"] == fixture_csv.name
    assert_no_path_leak(body, "$.legacy_points")

    detail = client.get("/api/cases/resistivity")
    assert detail.status_code == 200
    assert_no_path_leak(detail.json(), "$.legacy_detail")

    voxel = client.get("/api/cases/resistivity/voxel-cells")
    assert voxel.status_code == 200, voxel.text
    voxel_body = voxel.json()
    assert "local_cache_dir" not in voxel_body
    assert_no_path_leak(voxel_body, "$.legacy_voxel")

    created = client.post("/api/cases", json={"name": "DTO 案例"})
    assert created.status_code == 201
    assert_no_path_leak(created.json(), "$.create_case")


def test_scrub_nested_drops_directory_keys_recursively():
    """v0.6：内部 manifest 的 ``directory`` 绝对路径键在任意深度都被剔除。"""

    from geomodeling.platform.public_dto import scrub_nested

    body = scrub_nested(
        {"manifest": {"directory": "D:/abs", "items": [{"directory": "/var/x", "keep": 1}]}}
    )
    assert body == {"manifest": {"items": [{"keep": 1}]}}


def test_professional_dtos_never_leak_paths():
    """v0.6 Task 17：专业白名单 DTO 递归脱敏。

    diagnosis/job/confirmation/professional result/folds/residuals/anomaly/
    comparison 全部只暴露逻辑身份（工件逻辑名、行数、大小、SHA-256），
    manifest 内部的 ``directory`` 绝对路径与路径键一律剔除，绝对路径形态
    的字符串值替换为占位符；legacy 候选明确 ``LEGACY_RESULT_NOT_COMPUTED``
    且绝不伪造零值指标或能力。
    """

    import json
    from types import SimpleNamespace

    from geomodeling.modeling.comparison import CandidateComparison
    from geomodeling.platform.public_dto import (
        public_analysis_job,
        public_anomaly_extraction,
        public_comparison,
        public_confirmation,
        public_fold_evidence,
        public_manifest_summary,
        public_professional_diagnosis,
        public_professional_result,
        public_residuals,
        public_variogram_evidence,
    )
    from geomodeling.platform.tables import RunStatus

    manifest = {
        "version": 1,
        "fingerprint": "f" * 64,
        "directory": "D:/abs/professional",  # 内部绝对路径——必须剔除
        "artifacts": {
            "omnidirectional": {
                "file": "omnidirectional.csv",
                "sha256": "a" * 64,
                "bytes": 128,
                "grid_path": "D:/abs/internal.npz",  # 路径键——必须剔除
            }
        },
        "summary": {"min_sse_model": "gaussian", "evidence": "C:/abs/evidence.json"},
        "created_at": "2026-07-26T00:00:00+00:00",
    }

    summary = public_manifest_summary(manifest)
    assert_no_path_leak(summary, "$.manifest_summary")
    assert "directory" not in summary
    assert summary["artifacts"]["omnidirectional"] == {
        "file": "omnidirectional.csv",
        "sha256": "a" * 64,
        "bytes": 128,
    }
    assert summary["summary"]["min_sse_model"] == "gaussian"
    assert summary["summary"]["evidence"] == "<redacted-path>"

    diagnosis = SimpleNamespace(
        id="diag-1",
        dataset_version_id="ds-1",
        status="succeeded",
        config={"variogram": {"notes": "D:/cfg.txt"}},
        fingerprint="f" * 64,
        manifest=manifest,
        error=None,
        created_at="t0",
        updated_at="t1",
        finished_at="t2",
    )
    body = public_professional_diagnosis(diagnosis)
    assert_no_path_leak(body, "$.diagnosis")
    assert body["status"] == "succeeded"
    assert body["config"]["variogram"]["notes"] == "<redacted-path>"
    assert "directory" not in json.dumps(body)

    failed = SimpleNamespace(**{**diagnosis.__dict__, "manifest": {}, "error": {"code": "X"}})
    failed_body = public_professional_diagnosis(failed)
    assert failed_body["manifest"] is None
    assert_no_path_leak(failed_body, "$.diagnosis_failed")

    job = SimpleNamespace(
        id="job-1",
        job_kind="professional_diagnosis",
        subject_type="professional_diagnostic",
        subject_id="diag-1",
        request_fingerprint="q" * 64,
        status=RunStatus.QUEUED,
        retry_of_job_id=None,
        progress={"phase": "empirical_variogram", "staging": "D:/staging"},
        error=None,
        created_at="t0",
        updated_at="t1",
        started_at=None,
        finished_at=None,
    )
    job_body = public_analysis_job(job)
    assert_no_path_leak(job_body, "$.job")
    assert job_body["status"] == "queued"
    assert job_body["progress"]["staging"] == "<redacted-path>"

    confirmation = SimpleNamespace(
        id="conf-1",
        diagnostic_id="diag-1",
        config={"anisotropy": {"reference": "C:/evidence.json"}},
        fingerprint="c" * 64,
        note="采纳",
        created_at="t0",
    )
    confirmation_body = public_confirmation(confirmation)
    assert_no_path_leak(confirmation_body, "$.confirmation")
    assert confirmation_body["config"]["anisotropy"]["reference"] == "<redacted-path>"
    assert confirmation_body["fingerprint"] == "c" * 64

    result_body = public_professional_result(
        "result-1",
        algorithm="ordinary_kriging",
        confirmation_id="conf-1",
        capabilities={"native_kriging_std": "supported", "notes": {"ref": "D:/notes"}},
        parameter_provenance={"final": {"origin": "final_full_data_fit", "tmp": "D:/tmp"}},
        manifest=manifest,
    )
    assert_no_path_leak(result_body, "$.professional_result")
    assert result_body["available"] is True
    assert result_body["parameter_provenance"]["final"]["tmp"] == "<redacted-path>"
    assert "directory" not in json.dumps(result_body)

    legacy = public_professional_result(
        "result-legacy",
        algorithm="idw",
        confirmation_id=None,
        capabilities=None,
        parameter_provenance=None,
        manifest=None,
    )
    # legacy 候选：明确不可用原因，绝不伪造零值指标或能力
    assert legacy == {
        "result_id": "result-legacy",
        "available": False,
        "reason": "LEGACY_RESULT_NOT_COMPUTED",
        "algorithm": "idw",
    }
    assert_no_path_leak(legacy, "$.professional_legacy")

    extraction = SimpleNamespace(
        id="ext-1",
        candidate_result_id="result-1",
        status="succeeded",
        config={"threshold": 1.0, "workdir": "/var/tmp"},
        fingerprint="e" * 64,
        manifest=manifest,
        error=None,
        created_at="t0",
    )
    extraction_body = public_anomaly_extraction(
        extraction,
        components={"total": 1, "returned": 1, "rows": [{"component_id": 1, "debug": "D:/dbg"}]},
    )
    assert_no_path_leak(extraction_body, "$.extraction")
    assert extraction_body["components"]["rows"][0]["debug"] == "<redacted-path>"
    assert "directory" not in json.dumps(extraction_body)

    comparison_body = public_comparison(
        CandidateComparison(
            first_result_id="r1",
            second_result_id="r2",
            compatible=True,
            mismatches=[],
            common_valid_count=10,
            metric_deltas={"rmse": 0.1},
            grid_difference_available=False,
            grid_difference=None,
            comparison_fingerprint="9" * 64,
        )
    )
    assert_no_path_leak(comparison_body, "$.comparison")
    assert comparison_body["comparison_fingerprint"] == "9" * 64
    assert comparison_body["common_valid_count"] == 10

    folds_body = public_fold_evidence(
        "result-1",
        fold_count=1,
        leakage_detected=False,
        folds=[{"fold_index": 0, "validation_groups": [3], "trace": "D:/trace"}],
        download_url="/api/professional-artifacts/result:result-1:fold_assignments/download",
    )
    assert_no_path_leak(folds_body, "$.folds")
    assert folds_body["folds"][0]["trace"] == "<redacted-path>"
    assert folds_body["download_url"].startswith("/api/")

    residuals_body = public_residuals(
        "result-1",
        total=2,
        returned=2,
        decimate=1,
        columns={"source_row": [1, 2], "residual": [0.1, None], "label": ["D:/a", "b"]},
        download_url="/api/professional-artifacts/result:result-1:out_of_fold_predictions/download",
    )
    assert_no_path_leak(residuals_body, "$.residuals")
    assert residuals_body["label"][0] == "<redacted-path>"
    assert residuals_body["total"] == 2

    variogram_body = public_variogram_evidence(
        "diag-1",
        omnidirectional={
            "total": 1,
            "returned": 1,
            "decimate": 1,
            "rows": [{"bin_index": 0, "src": "D:/s"}],
        },
        directional={"total": 0, "returned": 0, "decimate": 1, "rows": []},
        fitted_models={"models": [], "min_sse_model": "gaussian"},
        anisotropy_candidates={"candidates": []},
        sampling={"seed": 1, "dump": "/tmp/dump"},
        downloads={
            "omnidirectional": "/api/professional-artifacts/diagnosis:diag-1:omnidirectional/download"
        },
    )
    assert_no_path_leak(variogram_body, "$.variogram")
    assert variogram_body["omnidirectional"]["rows"][0]["src"] == "<redacted-path>"
    assert variogram_body["fitted_models"]["min_sse_model"] == "gaussian"
    assert variogram_body["sampling"]["dump"] == "<redacted-path>"
