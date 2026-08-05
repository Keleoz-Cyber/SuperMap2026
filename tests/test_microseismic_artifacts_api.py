"""v0.5 领域证据导出包合同（DAT HTTP 导入退出后的服务级回归）。

Uses the synthetic 22-file bundle (45 source records / 44 finite / 1 invalid /
0 rejected / 44 accepted / 44 aggregated nodes) imported through the service
layer (``import_microseismic_dataset``) — v0.7.0 起 DAT 导入/派生 HTTP 端点
退出产品面，通用结果读取与导出不受影响。The microseismic export ZIP extends
the generic seven-file model package with the seven declared domain evidence
files under ``domain_evidence/``; every copied file carries its SHA-256 and
byte size in the ZIP manifest, and missing/tampered declared evidence blocks
the export instead of being silently omitted.
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

from microseismic_fixtures import (
    ALL_NAMES,
    assert_envelope,
    build_synthetic_bundle,
    create_case,
    make_app,
)
from test_public_dto import assert_no_path_leak

from geomodeling.microseismic.config import load_microseismic_config
from geomodeling.microseismic.platform_adapter import (
    MicroseismicImportBundle,
    import_microseismic_dataset,
)

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


def prepare_imported_dataset(
    client: TestClient, config_path: Path, data_dir: Path
) -> tuple[str, str]:
    """服务级 DAT 导入（与 CLI 同一服务函数；不经过已移除的 HTTP 导入端点）。"""

    case_id = create_case(client)
    runtime = client.app.state.platform_runtime
    record = import_microseismic_dataset(
        runtime,
        case_id,
        MicroseismicImportBundle(
            config=load_microseismic_config(config_path), source_dir=data_dir
        ),
    )
    return case_id, record.id


def prepare_succeeded_result(
    client: TestClient, config_path: Path, data_dir: Path
) -> tuple[str, str, str]:
    """Import → quality validation → experiment → run → candidate → result."""

    case_id, dataset_id = prepare_imported_dataset(client, config_path, data_dir)
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


def test_result_metadata_exposes_dataset_version_id(tmp_path, monkeypatch):
    config_path, data_dir = build_synthetic_bundle(tmp_path)
    app = make_app(tmp_path, monkeypatch, config_path)
    with TestClient(app) as client:
        _, dataset_id, candidate_id = prepare_succeeded_result(client, config_path, data_dir)

        resp = client.get(f"/api/results/{candidate_id}")
        assert resp.status_code == 200, resp.text
        metadata = resp.json()
        assert metadata["dataset_version_id"] == dataset_id
        assert_no_path_leak(metadata, "$.result_metadata")


def test_microseismic_export_zip_adds_declared_domain_evidence(tmp_path, monkeypatch):
    config_path, data_dir = build_synthetic_bundle(tmp_path)
    app = make_app(tmp_path, monkeypatch, config_path)
    with TestClient(app) as client:
        case_id, dataset_id, candidate_id = prepare_succeeded_result(
            client, config_path, data_dir
        )

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
        # （派生 HTTP 端点已退出产品面，身份以 ZIP 内派生报告为准）
        report = json.loads(bundle.read("domain_evidence/derivation_report.json"))
        artifacts = report["artifacts"]
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
        assert report["validation_passed"] is True
        assert report["layer_counts"]["accepted_modeling"] == 44
        source_manifest = json.loads(bundle.read("domain_evidence/source_manifest.json"))
        assert [entry["file_name"] for entry in source_manifest] == ALL_NAMES


def test_export_blocked_when_declared_evidence_missing(tmp_path, monkeypatch):
    config_path, data_dir = build_synthetic_bundle(tmp_path)
    app = make_app(tmp_path, monkeypatch, config_path)
    with TestClient(app) as client:
        case_id, dataset_id, candidate_id = prepare_succeeded_result(
            client, config_path, data_dir
        )
        derived = tmp_path / "data" / "datasets" / case_id / dataset_id / "derived"
        target = derived / "accepted_modeling_44.csv"
        assert target.is_file()
        target.unlink()

        # 导出被阻断，而不是悄悄省略缺失证据
        resp = client.post(f"/api/results/{candidate_id}/exports")
        assert resp.status_code == 409, resp.text
        error = assert_envelope(resp.json())
        assert error["code"] == "DOMAIN_EVIDENCE_MISSING"
        assert error["details"]["file"] == "accepted_modeling_44.csv"
        assert_no_path_leak(resp.json(), "$.export_blocked")


def test_export_blocked_when_declared_evidence_hash_mismatches(tmp_path, monkeypatch):
    """篡改已登记的领域证据：实际字节哈希与派生报告声明不符 → fail-closed 409。"""

    config_path, data_dir = build_synthetic_bundle(tmp_path)
    app = make_app(tmp_path, monkeypatch, config_path)
    with TestClient(app) as client:
        case_id, dataset_id, candidate_id = prepare_succeeded_result(
            client, config_path, data_dir
        )
        derived = tmp_path / "data" / "datasets" / case_id / dataset_id / "derived"
        target = derived / "accepted_modeling_44.csv"
        assert target.is_file()
        original_sha = hashlib.sha256(target.read_bytes()).hexdigest()
        with target.open("ab") as handle:
            handle.write(b"        0.060000        0.500000\r\n")
        assert hashlib.sha256(target.read_bytes()).hexdigest() != original_sha

        # 哈希不匹配必须阻断导出，绝不打包被篡改的证据
        resp = client.post(f"/api/results/{candidate_id}/exports")
        assert resp.status_code == 409, resp.text
        error = assert_envelope(resp.json())
        assert error["code"] == "DOMAIN_EVIDENCE_HASH_MISMATCH"
