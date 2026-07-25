"""Task 10: domain evidence downloads, diagnostic points and export package.

Uses the Task 7 synthetic 22-file bundle (45 source records / 44 finite /
1 invalid / 0 rejected / 44 accepted / 44 aggregated nodes). The download
allowlist is the artifact identity set declared by the validated derivation
report plus ``source_manifest.json`` — declared file names (which embed the
fixture's own counts) are resolved only inside the deterministic settings
dataset directory, never by concatenating an arbitrary client path.

The microseismic export ZIP extends the generic seven-file model package
with the seven declared domain evidence files under ``domain_evidence/``;
every copied file carries its SHA-256 and byte size in the ZIP manifest, and
missing declared evidence blocks the export instead of being silently
omitted.
"""

from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from test_microseismic_api import (
    ALL_NAMES,
    build_synthetic_bundle,
    create_case,
    import_bundle,
    make_app,
    assert_envelope,
)
from test_public_dto import assert_no_path_leak

# 通用模型证据包（七文件，回归锁定；通用数据集 ZIP 不得多出任何文件）。
STANDARD_PACKAGE_FILES = {
    "manifest.json",
    "metadata.json",
    "metrics.json",
    "quality.json",
    "formal_selections.json",
    "failed_evidence.json",
    "grid.csv",
}

# 夹具派生报告声明的七个领域证据文件（文件名嵌入夹具自身计数，
# 绝不冒称真实数据的 2006/1925/80/1911 口径）。
FIXTURE_EVIDENCE_FILES = {
    "domain_evidence/source_manifest.json",
    "domain_evidence/derivation_report.json",
    "domain_evidence/source_records_45.csv",
    "domain_evidence/invalid_records_1.csv",
    "domain_evidence/rejected_3sigma_0.csv",
    "domain_evidence/accepted_modeling_44.csv",
    "domain_evidence/aggregated_nodes_44.csv",
}

LAYER_TO_ARCNAME = {
    "source_records": "domain_evidence/source_records_45.csv",
    "invalid_records": "domain_evidence/invalid_records_1.csv",
    "rejected_3sigma": "domain_evidence/rejected_3sigma_0.csv",
    "accepted_modeling": "domain_evidence/accepted_modeling_44.csv",
    "aggregated_nodes": "domain_evidence/aggregated_nodes_44.csv",
}


def prepare_imported_dataset(client: TestClient, data_dir: Path) -> tuple[str, str]:
    case_id = create_case(client)
    dataset_id = import_bundle(client, case_id, data_dir)["id"]
    return case_id, dataset_id


def prepare_succeeded_result(client: TestClient, data_dir: Path) -> tuple[str, str, str]:
    """Import → quality validation → experiment → run → candidate → result."""

    case_id, dataset_id = prepare_imported_dataset(client, data_dir)
    # 通用三维质量门禁（实验创建的前置）在导入后显式执行。
    resp = client.post(f"/api/datasets/{dataset_id}/validate")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "passed", resp.json()
    resp = client.post(
        "/api/experiments",
        json={
            "case_id": case_id,
            "name": "微震建模实验",
            "algorithm": "idw",
            "dataset_version_id": dataset_id,
            "search_mode": "manual",
            "parameters": {"power": 2.0, "neighbor_count": 8},
            "validation": {"method": "spatial_kfold", "folds": 3, "seed": 1, "holdout_fraction": 0.2},
        },
    )
    assert resp.status_code == 201, resp.text
    experiment_id = resp.json()["id"]
    run_id = client.post(f"/api/experiments/{experiment_id}/runs").json()["id"]
    deadline = time.time() + 60
    body = {}
    while time.time() < deadline:
        body = client.get(f"/api/runs/{run_id}").json()
        if body["status"] in ("succeeded", "failed", "canceled"):
            break
        time.sleep(0.1)
    assert body["status"] == "succeeded", body
    candidates = client.get(f"/api/experiments/{experiment_id}/candidates").json()["candidates"]
    candidate_id = next(c["id"] for c in candidates if c["status"] == "succeeded")
    resp = client.post(f"/api/results/{candidate_id}/materialize")
    assert resp.status_code in (200, 201), resp.text
    return case_id, dataset_id, candidate_id


# ---------------------------------------------------------------------------
# Artifact downloads (allowlisted identities only)
# ---------------------------------------------------------------------------


def test_artifact_downloads_are_allowlisted_and_byte_identical(tmp_path, monkeypatch):
    config_path, data_dir = build_synthetic_bundle(tmp_path)
    app = make_app(tmp_path, monkeypatch, config_path)
    with TestClient(app) as client:
        _, dataset_id = prepare_imported_dataset(client, data_dir)
        derivation = client.get(f"/api/datasets/{dataset_id}/derivation").json()
        artifacts = derivation["artifacts"]
        assert set(artifacts) == {
            "source_records",
            "invalid_records",
            "rejected_3sigma",
            "accepted_modeling",
            "aggregated_nodes",
            "modeling_provenance",
        }

        for logical_name, declared in artifacts.items():
            resp = client.get(f"/api/datasets/{dataset_id}/derivation/artifacts/{logical_name}")
            assert resp.status_code == 200, f"{logical_name}: {resp.text}"
            assert hashlib.sha256(resp.content).hexdigest() == declared["sha256"]
            disposition = resp.headers.get("content-disposition", "")
            assert declared["file"] in disposition

        # source_manifest.json 是白名单上的唯一额外公开名
        resp = client.get(f"/api/datasets/{dataset_id}/derivation/artifacts/source_manifest.json")
        assert resp.status_code == 200, resp.text
        manifest = json.loads(resp.content)
        assert [entry["file_name"] for entry in manifest] == ALL_NAMES


@pytest.mark.parametrize(
    "bad_name",
    [
        "not_an_artifact",
        "accepted_modeling_44.csv",  # 声明的文件名不是公开逻辑名
        "modeling_provenance.parquet",
        "standardized.parquet",  # 内部文件绝不暴露
        "derivation_report.json",  # 报告本体不在下载白名单
        "source_manifest",  # 缺扩展名不匹配
        "W1.dat",  # 原始 DAT 不经此端点
        "platform.sqlite3",
    ],
)
def test_artifact_download_rejects_non_allowlisted_names(tmp_path, monkeypatch, bad_name):
    config_path, data_dir = build_synthetic_bundle(tmp_path)
    app = make_app(tmp_path, monkeypatch, config_path)
    with TestClient(app) as client:
        _, dataset_id = prepare_imported_dataset(client, data_dir)
        resp = client.get(f"/api/datasets/{dataset_id}/derivation/artifacts/{bad_name}")
        assert resp.status_code == 404, resp.text
        error = assert_envelope(resp.json())
        assert error["code"] == "MICROSEISMIC_ARTIFACT_NOT_FOUND"
        assert_no_path_leak(resp.json(), "$.artifact_rejected")


@pytest.mark.parametrize(
    "probe",
    [
        "..%2F..%2Fplatform.sqlite3",  # 解码后含 /，路由失配或白名单拒绝
        "..%5C..%5Cplatform.sqlite3",  # 反斜杠分隔符
        "%2E%2E%2Fderivation_report.json",
    ],
)
def test_artifact_download_rejects_traversal_probes(tmp_path, monkeypatch, probe):
    config_path, data_dir = build_synthetic_bundle(tmp_path)
    app = make_app(tmp_path, monkeypatch, config_path)
    with TestClient(app) as client:
        _, dataset_id = prepare_imported_dataset(client, data_dir)
        resp = client.get(f"/api/datasets/{dataset_id}/derivation/artifacts/{probe}")
        assert resp.status_code == 404, resp.text
        assert_no_path_leak(resp.json(), "$.artifact_traversal")


def test_artifact_and_points_require_microseismic_dataset(tmp_path, monkeypatch):
    from test_experiment_api import CSV_2D

    config_path, _ = build_synthetic_bundle(tmp_path)
    app = make_app(tmp_path, monkeypatch, config_path)
    with TestClient(app) as client:
        case_id = create_case(client, "普通上传案例")
        upload = client.post(
            f"/api/cases/{case_id}/datasets/uploads",
            files={"file": ("data.csv", io.BytesIO(CSV_2D.encode()), "application/octet-stream")},
        )
        assert upload.status_code == 201, upload.text
        dataset_id = upload.json()["id"]

        for url in (
            f"/api/datasets/{dataset_id}/derivation/artifacts/accepted_modeling",
            f"/api/datasets/{dataset_id}/derivation/points?layer=accepted",
        ):
            resp = client.get(url)
            assert resp.status_code == 409, resp.text
            error = assert_envelope(resp.json())
            assert error["code"] == "DATASET_NOT_MICROSEISMIC"
            assert_no_path_leak(resp.json(), "$.not_microseismic")

        ghost = "00000000-0000-0000-0000-000000000000"
        resp = client.get(f"/api/datasets/{ghost}/derivation/artifacts/accepted_modeling")
        assert resp.status_code == 404
        assert assert_envelope(resp.json())["code"] == "DATASET_NOT_FOUND"
        resp = client.get(f"/api/datasets/{ghost}/derivation/points?layer=accepted")
        assert resp.status_code == 404
        assert assert_envelope(resp.json())["code"] == "DATASET_NOT_FOUND"


# ---------------------------------------------------------------------------
# Diagnostic point layers (bounded, typed numeric arrays)
# ---------------------------------------------------------------------------


def test_points_accepted_layer_returns_bounded_typed_arrays(tmp_path, monkeypatch):
    config_path, data_dir = build_synthetic_bundle(tmp_path)
    app = make_app(tmp_path, monkeypatch, config_path)
    with TestClient(app) as client:
        _, dataset_id = prepare_imported_dataset(client, data_dir)

        resp = client.get(f"/api/datasets/{dataset_id}/derivation/points?layer=accepted")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert_no_path_leak(body, "$.points.accepted")
        assert body["dataset_id"] == dataset_id
        assert body["layer"] == "accepted"
        assert body["total"] == 44
        assert body["returned"] == 44
        assert body["decimate"] == 1
        for key in ("x", "y", "z", "vx"):
            values = body[key]
            assert isinstance(values, list) and len(values) == 44, key
            assert all(type(v) in (int, float) for v in values), key
        assert len(body["sample_id"]) == 44
        assert all(type(s) is str for s in body["sample_id"])
        # 首行 = W1 的第一条有限样本（夹具坐标 + 确认的 Z 规则）
        assert body["sample_id"][0] == "W1:2"
        assert body["x"][0] == pytest.approx(400.0)
        assert body["y"][0] == pytest.approx(220.0)
        assert body["z"][0] == pytest.approx(-50.0)
        assert body["vx"][0] == pytest.approx(0.524804)


def test_points_rejected_layer_exposes_filter_diagnostics(tmp_path, monkeypatch):
    config_path, data_dir = build_synthetic_bundle(tmp_path)
    app = make_app(tmp_path, monkeypatch, config_path)
    with TestClient(app) as client:
        _, dataset_id = prepare_imported_dataset(client, data_dir)

        resp = client.get(f"/api/datasets/{dataset_id}/derivation/points?layer=rejected")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["layer"] == "rejected"
        assert body["total"] == 0
        assert body["returned"] == 0
        # 夹具无 3σ 剔除：诊断键必须存在且为空数组（类型化契约）
        for key in ("x", "y", "z", "vx", "sample_id", "filter_reason", "depth_zscore", "vx_zscore"):
            assert body[key] == [], key


def test_points_aggregated_layer_exposes_provenance_and_stats(tmp_path, monkeypatch):
    config_path, data_dir = build_synthetic_bundle(tmp_path)
    app = make_app(tmp_path, monkeypatch, config_path)
    with TestClient(app) as client:
        _, dataset_id = prepare_imported_dataset(client, data_dir)

        resp = client.get(f"/api/datasets/{dataset_id}/derivation/points?layer=aggregated")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert_no_path_leak(body, "$.points.aggregated")
        assert body["layer"] == "aggregated"
        assert body["total"] == 44
        assert body["returned"] == 44
        for key in ("x", "y", "z", "vx", "vx_min", "vx_max"):
            assert len(body[key]) == 44, key
            assert all(type(v) in (int, float) for v in body[key]), key
        assert all(type(v) is int and v == 1 for v in body["sample_count"])
        assert len(body["source_sample_ids"]) == 44
        assert all(type(ids) is list for ids in body["source_sample_ids"])
        assert all(type(s) is str for ids in body["source_sample_ids"] for s in ids)
        assert body["source_sample_ids"][0] == ["W1:2"]
        # 单样本组：min=max=vx，样本标准差为 null
        assert body["vx_min"][0] == pytest.approx(0.524804)
        assert body["vx_max"][0] == pytest.approx(0.524804)
        assert body["vx_std"][0] is None


def test_points_decimate_strides_and_stays_bounded(tmp_path, monkeypatch):
    config_path, data_dir = build_synthetic_bundle(tmp_path)
    app = make_app(tmp_path, monkeypatch, config_path)
    with TestClient(app) as client:
        _, dataset_id = prepare_imported_dataset(client, data_dir)
        base_url = f"/api/datasets/{dataset_id}/derivation/points?layer=accepted"

        full = client.get(base_url).json()
        resp = client.get(f"{base_url}&decimate=2")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["decimate"] == 2
        assert body["total"] == 44
        assert body["returned"] == 22
        assert body["x"] == full["x"][::2]
        assert body["vx"] == full["vx"][::2]
        assert body["sample_id"] == full["sample_id"][::2]

        top = client.get(f"{base_url}&decimate=1000").json()
        assert top["decimate"] == 1000
        assert top["total"] == 44
        assert top["returned"] == 1
        assert top["sample_id"] == ["W1:2"]


def test_points_reject_invalid_layer_and_decimate(tmp_path, monkeypatch):
    config_path, data_dir = build_synthetic_bundle(tmp_path)
    app = make_app(tmp_path, monkeypatch, config_path)
    with TestClient(app) as client:
        _, dataset_id = prepare_imported_dataset(client, data_dir)
        base_url = f"/api/datasets/{dataset_id}/derivation/points"

        resp = client.get(base_url)  # layer 必填
        assert resp.status_code == 422
        resp = client.get(f"{base_url}?layer=unknown")
        assert resp.status_code == 422
        for decimate in ("0", "-3", "1001", "1.5", "abc"):
            resp = client.get(f"{base_url}?layer=accepted&decimate={decimate}")
            assert resp.status_code == 422, decimate


# ---------------------------------------------------------------------------
# Result dataset identity
# ---------------------------------------------------------------------------


def test_result_metadata_exposes_dataset_version_id(tmp_path, monkeypatch):
    config_path, data_dir = build_synthetic_bundle(tmp_path)
    app = make_app(tmp_path, monkeypatch, config_path)
    with TestClient(app) as client:
        _, dataset_id, candidate_id = prepare_succeeded_result(client, data_dir)

        resp = client.get(f"/api/results/{candidate_id}")
        assert resp.status_code == 200, resp.text
        metadata = resp.json()
        assert metadata["dataset_version_id"] == dataset_id
        assert_no_path_leak(metadata, "$.result_metadata")


# ---------------------------------------------------------------------------
# Export package extended by source kind
# ---------------------------------------------------------------------------


def test_microseismic_export_zip_adds_declared_domain_evidence(tmp_path, monkeypatch):
    config_path, data_dir = build_synthetic_bundle(tmp_path)
    app = make_app(tmp_path, monkeypatch, config_path)
    with TestClient(app) as client:
        case_id, dataset_id, candidate_id = prepare_succeeded_result(client, data_dir)
        derivation = client.get(f"/api/datasets/{dataset_id}/derivation").json()

        resp = client.post(f"/api/results/{candidate_id}/exports")
        assert resp.status_code == 201, resp.text
        export = resp.json()
        assert export["file_count"] == len(STANDARD_PACKAGE_FILES) + len(FIXTURE_EVIDENCE_FILES)

        download = client.get(f"/api/exports/{export['id']}/download")
        assert download.status_code == 200
        bundle = zipfile.ZipFile(io.BytesIO(download.content))
        names = set(bundle.namelist())
        assert names == STANDARD_PACKAGE_FILES | FIXTURE_EVIDENCE_FILES
        # ZIP 内路径安全：无绝对路径、无遍历段
        for name in names:
            assert not name.startswith(("/", "\\"))
            assert ".." not in name.split("/")

        manifest = json.loads(bundle.read("manifest.json"))
        assert manifest["candidate_result_id"] == candidate_id
        assert manifest["case_id"] == case_id
        evidence = manifest["domain_evidence"]
        assert len(evidence) == len(FIXTURE_EVIDENCE_FILES)
        by_arcname = {entry["arcname"]: entry for entry in evidence}
        assert set(by_arcname) == FIXTURE_EVIDENCE_FILES
        # 每个证据文件的哈希与字节数固定在 ZIP manifest 中，且与 ZIP 字节一致
        for arcname, entry in by_arcname.items():
            payload = bundle.read(arcname)
            assert hashlib.sha256(payload).hexdigest() == entry["sha256"], arcname
            assert len(payload) == entry["size_bytes"], arcname
        # 分层 CSV 与派生报告声明的身份（文件名/行数/哈希）完全一致
        artifacts = derivation["artifacts"]
        for key, arcname in LAYER_TO_ARCNAME.items():
            assert by_arcname[arcname]["sha256"] == artifacts[key]["sha256"], key
            assert by_arcname[arcname]["rows"] == artifacts[key]["rows"], key
        assert artifacts["source_records"]["rows"] == 45
        assert artifacts["accepted_modeling"]["rows"] == 44
        assert artifacts["aggregated_nodes"]["rows"] == 44

        # 原有七文件内容不变语义：元数据带数据集身份，候选指标含分组诊断
        metadata = json.loads(bundle.read("metadata.json"))
        assert metadata["dataset_version_id"] == dataset_id
        assert metadata["dimension"] == "3d"
        metrics = json.loads(bundle.read("metrics.json"))
        assert "group_diagnostics" in metrics["candidate"]
        report = json.loads(bundle.read("domain_evidence/derivation_report.json"))
        assert report["validation_passed"] is True
        assert report["layer_counts"]["accepted_modeling"] == 44
        source_manifest = json.loads(bundle.read("domain_evidence/source_manifest.json"))
        assert [entry["file_name"] for entry in source_manifest] == ALL_NAMES


def test_export_blocked_when_declared_evidence_missing(tmp_path, monkeypatch):
    config_path, data_dir = build_synthetic_bundle(tmp_path)
    app = make_app(tmp_path, monkeypatch, config_path)
    with TestClient(app) as client:
        case_id, dataset_id, candidate_id = prepare_succeeded_result(client, data_dir)
        derived = tmp_path / "data" / "datasets" / case_id / dataset_id / "derived"
        target = derived / "accepted_modeling_44.csv"
        assert target.is_file()
        target.unlink()

        # 声明过的工件缺失：下载与点端点同样 404，绝不静默
        resp = client.get(f"/api/datasets/{dataset_id}/derivation/artifacts/accepted_modeling")
        assert resp.status_code == 404, resp.text
        assert assert_envelope(resp.json())["code"] == "MICROSEISMIC_ARTIFACT_NOT_FOUND"
        resp = client.get(f"/api/datasets/{dataset_id}/derivation/points?layer=accepted")
        assert resp.status_code == 404, resp.text

        # 导出被阻断，而不是悄悄省略缺失证据
        resp = client.post(f"/api/results/{candidate_id}/exports")
        assert resp.status_code == 409, resp.text
        error = assert_envelope(resp.json())
        assert error["code"] == "DOMAIN_EVIDENCE_MISSING"
        assert error["details"]["file"] == "accepted_modeling_44.csv"
        assert_no_path_leak(resp.json(), "$.export_blocked")
