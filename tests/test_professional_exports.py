"""Task 19: capability-aware professional evidence export tests.

设计 §16/§17：专业候选的证据 ZIP 在通用七文件（与微震 domain_evidence）
之上按 capability 追加 ``professional/`` 目录——登记诊断、全向/方向变异
函数、确认快照、邻域摘要、折分与折外预测（parquet→CSV）、有界残差摘要、
经验误差尺度与原生标准差的元数据（大数组不进 ZIP）、已成功保存的异常提
取。导出只包含已成功、已登记且哈希吻合的工件；声明存在但缺失或哈希不
符 → 整体 409 ``PROFESSIONAL_EVIDENCE_HASH_MISMATCH`` fail-closed（不
产生 Export 行、无可下载 ZIP、无暂存目录残留）。IDW 缺 Kriging 方差不
视为失败：professional/manifest.json 以 ``not_applicable`` 记录算法适用
性，ZIP 不含 kriging_standard_deviation_metadata.json。legacy 候选（无
ProfessionalResultArtifacts 行）导出与现状逐位一致。
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from geomodeling.platform import tables
from test_microseismic_api import assert_envelope
from test_professional_api import (
    DIAGNOSIS_CONFIG,
    _auto_confirm_body,
    _experiment_body,
    _make_app,
    _prepare_dataset,
    _run_experiment,
    _wait_job,
)
from test_public_dto import assert_no_path_leak

GENERIC_PACKAGE_FILES = {
    "manifest.json",
    "metadata.json",
    "metrics.json",
    "quality.json",
    "formal_selections.json",
    "failed_evidence.json",
    "grid.csv",
}

# 设计 §16 固定逻辑名映射（Kriging + 确认 + 一次异常提取的全量集合）
PROFESSIONAL_BASE_FILES = {
    "professional/neighborhood.json",
    "professional/fold_assignments.csv",
    "professional/out_of_fold_predictions.csv",
    "professional/residual_summary.json",
    "professional/empirical_error_scale_metadata.json",
    "professional/manifest.json",
}
PROFESSIONAL_DIAGNOSIS_FILES = {
    "professional/diagnosis.json",
    "professional/variogram_omnidirectional.csv",
    "professional/variogram_directional.csv",
    "professional/fitted_models.json",
    "professional/anisotropy_confirmation.json",
}
PROFESSIONAL_KRIGING_ONLY_FILES = {"professional/kriging_standard_deviation_metadata.json"}


def _anomaly_files(extraction_id: str) -> set[str]:
    return {
        f"professional/anomaly_extractions/{extraction_id}/{name}"
        for name in ("components.csv", "summary.json", "mask.npz")
    }


def _drive_diagnosis_and_confirmation(client: TestClient, dataset_id: str) -> tuple[str, str]:
    """真实 worker 路径：诊断到成功 → 自动策略不可变确认。"""

    created = client.post(
        f"/api/datasets/{dataset_id}/professional-diagnostics", json=DIAGNOSIS_CONFIG
    )
    assert created.status_code == 202, created.text
    diagnosis_id = created.json()["diagnosis_id"]
    job = _wait_job(client, created.json()["job_id"], {"succeeded", "failed"})
    assert job["status"] == "succeeded", job
    diagnosis = client.get(f"/api/professional-diagnostics/{diagnosis_id}")
    assert diagnosis.status_code == 200, diagnosis.text
    fitted_sha = diagnosis.json()["manifest"]["artifacts"]["fitted_models"]["sha256"]
    confirmed = client.post(
        f"/api/professional-diagnostics/{diagnosis_id}/confirm",
        json=_auto_confirm_body(fitted_sha, note="采纳自动候选"),
    )
    assert confirmed.status_code == 201, confirmed.text
    return diagnosis_id, confirmed.json()["id"]


def _drive_anomaly_extraction(client: TestClient, result_id: str, value_range: list) -> str:
    """真实 worker 路径：一次成功异常提取（阈值取值域低端，保证连通区非空）。"""

    threshold = value_range[0] + 0.1 * (value_range[1] - value_range[0])
    created = client.post(
        f"/api/results/{result_id}/anomaly-extractions",
        json={"direction": "high", "threshold": threshold},
    )
    assert created.status_code == 202, created.text
    extraction_id = created.json()["extraction_id"]
    job = _wait_job(client, created.json()["job_id"], {"succeeded", "failed"})
    assert job["status"] == "succeeded", job
    return extraction_id


def _build_chain(client: TestClient, ns: SimpleNamespace) -> None:
    """全链路：数据集 → 诊断+确认 → Kriging/IDW 专业候选（物化）→ 异常提取。"""

    ns.case_id, ns.dataset_id = _prepare_dataset(client, "专业导出案例")
    ns.diagnosis_id, ns.confirmation_id = _drive_diagnosis_and_confirmation(
        client, ns.dataset_id
    )

    ns.kriging_result_id = _run_experiment(
        client,
        _experiment_body(
            ns.case_id,
            ns.dataset_id,
            name="Kriging 自动",
            algorithm="ordinary_kriging",
            parameters={"neighbor_count": 8},
            confirmation_id=ns.confirmation_id,
        ),
    )
    metadata = client.post(f"/api/results/{ns.kriging_result_id}/materialize")
    assert metadata.status_code == 200, metadata.text
    ns.kriging_metadata = metadata.json()

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

    ns.extraction_id = _drive_anomaly_extraction(
        client, ns.kriging_result_id, ns.kriging_metadata["value_range"]
    )


@pytest.fixture(scope="class")
def export_api(tmp_path_factory):
    """只读全链路夹具：Kriging（确认+异常提取）与 IDW 专业候选均已物化。"""

    tmp_path = tmp_path_factory.mktemp("prof_export_api")
    with pytest.MonkeyPatch.context() as monkeypatch:
        app = _make_app(tmp_path, monkeypatch)
        with TestClient(app) as client:
            ns = SimpleNamespace(client=client, runtime=app.state.platform_runtime)
            _build_chain(client, ns)
            # legacy IDW 候选（无专业上下文，物化）：导出行为必须与现状一致
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
            legacy = client.post(f"/api/results/{ns.legacy_result_id}/materialize")
            assert legacy.status_code == 200, legacy.text
            assert "professional" not in legacy.json()
            yield ns


def _download_bundle(client: TestClient, export_id: str) -> zipfile.ZipFile:
    download = client.get(f"/api/exports/{export_id}/download")
    assert download.status_code == 200, download.text
    assert download.headers["content-type"] == "application/zip"
    return zipfile.ZipFile(io.BytesIO(download.content))


# ---------------------------------------------------------------------------
# Kriging 全量专业证据
# ---------------------------------------------------------------------------


class TestKrigingProfessionalExport:
    def test_zip_includes_registered_professional_evidence(self, export_api):
        ns = export_api
        resp = ns.client.post(f"/api/results/{ns.kriging_result_id}/exports")
        assert resp.status_code == 201, resp.text
        export = resp.json()
        assert_no_path_leak(export, "$.export")

        expected_professional = (
            PROFESSIONAL_BASE_FILES
            | PROFESSIONAL_DIAGNOSIS_FILES
            | PROFESSIONAL_KRIGING_ONLY_FILES
            | _anomaly_files(ns.extraction_id)
        )
        bundle = _download_bundle(ns.client, export["id"])
        names = set(bundle.namelist())
        # 通用七文件逐位保留，专业证据整体追加
        assert names == GENERIC_PACKAGE_FILES | expected_professional
        assert export["file_count"] == len(names)
        # ZIP 内路径安全：无绝对路径、无遍历段
        for name in names:
            assert not name.startswith(("/", "\\"))
            assert ".." not in name.split("/")
        # 大网格 npz 不另塞 professional/（仍走原压缩成果工件机制）
        assert "professional/empirical_error_scale.npz" not in names
        assert "professional/kriging_standard_deviation.npz" not in names

        manifest = json.loads(bundle.read("manifest.json"))
        assert_no_path_leak(manifest, "$.manifest")
        section = manifest["professional"]
        assert section["algorithm"] == "ordinary_kriging"
        assert section["capabilities"]["native_kriging_std"] == "supported"
        assert section["capabilities"]["empirical_error_scale"] == "supported"
        assert section["confirmation_id"] == ns.confirmation_id
        assert section["diagnosis_id"] == ns.diagnosis_id
        assert section["anomaly_extractions"] == [ns.extraction_id]
        # 逐文件 size/SHA-256 固定在 root manifest，且与 ZIP 字节一致
        by_arcname = {entry["arcname"]: entry for entry in section["files"]}
        assert set(by_arcname) == expected_professional
        for arcname, entry in by_arcname.items():
            payload = bundle.read(arcname)
            assert hashlib.sha256(payload).hexdigest() == entry["sha256"], arcname
            assert len(payload) == entry["size_bytes"], arcname

        # 诊断证据与成功诊断 manifest 声明逐位一致
        diagnosis = ns.client.get(f"/api/professional-diagnostics/{ns.diagnosis_id}").json()
        diag_declared = diagnosis["manifest"]["artifacts"]
        for logical, arcname in (
            ("metadata", "professional/diagnosis.json"),
            ("omnidirectional", "professional/variogram_omnidirectional.csv"),
            ("directional", "professional/variogram_directional.csv"),
            ("fitted_models", "professional/fitted_models.json"),
        ):
            assert by_arcname[arcname]["sha256"] == diag_declared[logical]["sha256"], logical
        diag_payload = json.loads(bundle.read("professional/diagnosis.json"))
        assert diag_payload["diagnosis_id"] == ns.diagnosis_id
        assert diag_payload["sampling"]["total_pair_count"] > 0
        fitted = json.loads(bundle.read("professional/fitted_models.json"))
        assert fitted["min_sse_model"] in {m["model"] for m in fitted["models"]}
        assert "best_model" not in fitted

        # 确认快照：不可变确认身份、指纹与各向异性选择
        confirmation = json.loads(bundle.read("professional/anisotropy_confirmation.json"))
        assert confirmation["confirmation_id"] == ns.confirmation_id
        assert confirmation["diagnosis_id"] == ns.diagnosis_id
        assert len(confirmation["fingerprint"]) == 64
        assert confirmation["note"] == "采纳自动候选"
        assert confirmation["config"]["anisotropy"]["keep_isotropic"] is True
        assert confirmation["config"]["parameter_strategy"] == "automatic_candidate"

        # 候选专业证据与已登记工件 manifest 声明一致
        professional = ns.client.get(
            f"/api/results/{ns.kriging_result_id}/professional"
        ).json()
        pro_declared = professional["manifest"]["artifacts"]
        assert (
            by_arcname["professional/neighborhood.json"]["sha256"]
            == pro_declared["neighborhood_summary"]["sha256"]
        )

        # parquet → CSV 转换导出：可控表行数与登记 parquet 一致
        pro_dir = ns.runtime.settings.professional_result_dir(ns.kriging_result_id)
        assignments = pd.read_parquet(pro_dir / "fold_assignments.parquet")
        oof = pd.read_parquet(pro_dir / "out_of_fold_predictions.parquet")
        fold_csv = bundle.read("professional/fold_assignments.csv").decode("utf-8")
        assert len(fold_csv.strip().splitlines()) == len(assignments) + 1
        assert "leakage_detected" in fold_csv.splitlines()[0]
        oof_csv = bundle.read("professional/out_of_fold_predictions.csv").decode("utf-8")
        assert len(oof_csv.strip().splitlines()) == len(oof) + 1
        assert "residual" in oof_csv.splitlines()[0]

        # 残差摘要：从 OOF 计算的有界统计（count/mean/std/min/max/abs 分位数、
        # NoData 计数），不是全表
        summary = json.loads(bundle.read("professional/residual_summary.json"))
        assert_no_path_leak(summary, "$.residual_summary")
        residuals_all = oof["residual"].to_numpy(dtype="float64")
        nodata_mask = oof["is_nodata"].to_numpy(dtype=bool) | ~np.isfinite(residuals_all)
        valid = residuals_all[~nodata_mask]
        assert summary["row_count"] == len(oof)
        assert summary["count"] == int(valid.size)
        assert summary["nodata_count"] == int(nodata_mask.sum())
        assert summary["mean"] == pytest.approx(float(valid.mean()))
        assert summary["std"] == pytest.approx(float(valid.std()))
        assert summary["min"] == pytest.approx(float(valid.min()))
        assert summary["max"] == pytest.approx(float(valid.max()))
        abs_residuals = np.abs(valid)
        for quantile in ("p50", "p90", "p95", "p99"):
            assert summary["abs_quantiles"][quantile] == pytest.approx(
                float(np.quantile(abs_residuals, int(quantile[1:]) / 100.0))
            )
        assert (
            summary["source_sha256"] == pro_declared["out_of_fold_predictions"]["sha256"]
        )

        # 不确定性元数据：能力/覆盖率与登记身份；大数组本体不入 ZIP
        empirical_meta = json.loads(
            bundle.read("professional/empirical_error_scale_metadata.json")
        )
        assert empirical_meta["capability"] == "supported"
        assert empirical_meta["available"] is True
        assert 0.0 <= empirical_meta["coverage"] <= 1.0
        assert (
            empirical_meta["sha256"] == pro_declared["empirical_error_scale"]["sha256"]
        )
        assert empirical_meta["bytes"] == pro_declared["empirical_error_scale"]["bytes"]
        std_meta = json.loads(
            bundle.read("professional/kriging_standard_deviation_metadata.json")
        )
        assert std_meta["capability"] == "supported"
        assert std_meta["available"] is True
        assert (
            std_meta["sha256"] == pro_declared["kriging_standard_deviation"]["sha256"]
        )
        assert std_meta["bytes"] == pro_declared["kriging_standard_deviation"]["bytes"]

        # 专业 manifest：记录算法适用性，绝不泄露服务器目录
        pro_manifest = json.loads(bundle.read("professional/manifest.json"))
        assert_no_path_leak(pro_manifest, "$.professional_manifest")
        assert pro_manifest["capabilities"]["native_kriging_std"] == "supported"
        assert (
            pro_manifest["artifacts"]["kriging_standard_deviation"]["sha256"]
            == pro_declared["kriging_standard_deviation"]["sha256"]
        )

        # 异常提取：每次成功提取的 components/summary/mask 与提取 manifest 声明一致
        extraction = ns.client.get(f"/api/anomaly-extractions/{ns.extraction_id}").json()
        ext_declared = extraction["manifest"]["artifacts"]
        for logical, arcname in (
            ("components", f"professional/anomaly_extractions/{ns.extraction_id}/components.csv"),
            ("summary", f"professional/anomaly_extractions/{ns.extraction_id}/summary.json"),
            ("mask", f"professional/anomaly_extractions/{ns.extraction_id}/mask.npz"),
        ):
            assert by_arcname[arcname]["sha256"] == ext_declared[logical]["sha256"], logical
        ext_summary = json.loads(
            bundle.read(f"professional/anomaly_extractions/{ns.extraction_id}/summary.json")
        )
        assert ext_summary["diagnostics"]["component_count"] >= 1

    def test_professional_file_hashes_are_deterministic_across_exports(self, export_api):
        ns = export_api
        first = ns.client.post(f"/api/results/{ns.kriging_result_id}/exports")
        assert first.status_code == 201, first.text
        second = ns.client.post(f"/api/results/{ns.kriging_result_id}/exports")
        assert second.status_code == 201, second.text
        first_hashes = {
            entry["arcname"]: entry["sha256"]
            for entry in first.json()["manifest"]["professional"]["files"]
        }
        second_hashes = {
            entry["arcname"]: entry["sha256"]
            for entry in second.json()["manifest"]["professional"]["files"]
        }
        # parquet→CSV 与残差摘要等派生文件同样逐位确定
        assert first_hashes == second_hashes


# ---------------------------------------------------------------------------
# IDW：原生标准差 capability not_applicable，不视为失败
# ---------------------------------------------------------------------------


class TestIDWProfessionalExport:
    def test_idw_omits_native_std_with_capability_not_applicable(self, export_api):
        ns = export_api
        resp = ns.client.post(f"/api/results/{ns.idw_result_id}/exports")
        assert resp.status_code == 201, resp.text
        export = resp.json()
        assert_no_path_leak(export, "$.export_idw")

        # IDW 无确认/诊断证据、无原生标准差元数据；其余专业证据照常
        expected_professional = set(PROFESSIONAL_BASE_FILES)
        bundle = _download_bundle(ns.client, export["id"])
        names = set(bundle.namelist())
        assert names == GENERIC_PACKAGE_FILES | expected_professional
        assert export["file_count"] == len(names)

        manifest = json.loads(bundle.read("manifest.json"))
        section = manifest["professional"]
        assert section["algorithm"] == "idw"
        assert section["capabilities"]["native_kriging_std"] == "not_applicable"
        assert section["capabilities"]["empirical_error_scale"] == "supported"
        assert section["confirmation_id"] is None
        assert section["diagnosis_id"] is None
        assert section["anomaly_extractions"] == []

        # professional/manifest.json 记录算法适用性：缺 Kriging 方差不视为失败
        pro_manifest = json.loads(bundle.read("professional/manifest.json"))
        assert_no_path_leak(pro_manifest, "$.idw_professional_manifest")
        assert pro_manifest["capabilities"]["native_kriging_std"] == "not_applicable"
        assert "kriging_standard_deviation" not in pro_manifest["artifacts"]

        # 经验误差尺度元数据照常导出且与登记身份一致
        professional = ns.client.get(f"/api/results/{ns.idw_result_id}/professional").json()
        pro_declared = professional["manifest"]["artifacts"]
        empirical_meta = json.loads(
            bundle.read("professional/empirical_error_scale_metadata.json")
        )
        assert empirical_meta["capability"] == "supported"
        assert empirical_meta["sha256"] == pro_declared["empirical_error_scale"]["sha256"]


# ---------------------------------------------------------------------------
# legacy 候选：无 ProfessionalResultArtifacts 行，导出与现状逐位一致
# ---------------------------------------------------------------------------


class TestLegacyExportUnchanged:
    def test_legacy_candidate_export_has_no_professional_section(self, export_api):
        ns = export_api
        resp = ns.client.post(f"/api/results/{ns.legacy_result_id}/exports")
        assert resp.status_code == 201, resp.text
        export = resp.json()
        assert export["file_count"] == len(GENERIC_PACKAGE_FILES)

        bundle = _download_bundle(ns.client, export["id"])
        assert set(bundle.namelist()) == GENERIC_PACKAGE_FILES
        manifest = json.loads(bundle.read("manifest.json"))
        assert "professional" not in manifest
        assert "domain_evidence" not in manifest


# ---------------------------------------------------------------------------
# 篡改注入：每一类已声明专业工件缺失/哈希不符 → 409 fail-closed
# ---------------------------------------------------------------------------


def _tamper_targets(ns: SimpleNamespace) -> dict[str, object]:
    settings = ns.runtime.settings
    diagnosis_dir = settings.professional_diagnosis_dir(
        ns.case_id, ns.dataset_id, ns.diagnosis_id
    )
    professional_dir = settings.professional_result_dir(ns.kriging_result_id)
    extraction_dir = settings.anomaly_extraction_dir(ns.kriging_result_id, ns.extraction_id)
    return {
        "diagnosis_metadata": diagnosis_dir / "metadata.json",
        "diagnosis_omnidirectional": diagnosis_dir / "omnidirectional.csv",
        "diagnosis_directional": diagnosis_dir / "directional.csv",
        "diagnosis_fitted_models": diagnosis_dir / "fitted_models.json",
        "diagnosis_anisotropy_candidates": diagnosis_dir / "anisotropy_candidates.json",
        "fold_assignments": professional_dir / "fold_assignments.parquet",
        "out_of_fold_predictions": professional_dir / "out_of_fold_predictions.parquet",
        "prediction_diagnostics": professional_dir / "prediction_diagnostics.json",
        "neighborhood_summary": professional_dir / "neighborhood_summary.json",
        "professional_metadata": professional_dir / "metadata.json",
        "empirical_error_scale": professional_dir / "empirical_error_scale.npz",
        "kriging_standard_deviation": professional_dir
        / "kriging_standard_deviation.npz",
        "anomaly_components": extraction_dir / "components.csv",
        "anomaly_summary": extraction_dir / "summary.json",
        "anomaly_mask": extraction_dir / "mask.npz",
    }


TAMPER_TARGET_IDS = [
    "diagnosis_metadata",
    "diagnosis_omnidirectional",
    "diagnosis_directional",
    "diagnosis_fitted_models",
    "diagnosis_anisotropy_candidates",
    "fold_assignments",
    "out_of_fold_predictions",
    "prediction_diagnostics",
    "neighborhood_summary",
    "professional_metadata",
    "empirical_error_scale",
    "kriging_standard_deviation",
    "anomaly_components",
    "anomaly_summary",
    "anomaly_mask",
]


@pytest.fixture()
def tamper_api(tmp_path, monkeypatch):
    """函数级全链路夹具：每个篡改注入都在隔离 runtime 上进行。"""

    app = _make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        ns = SimpleNamespace(client=client, runtime=app.state.platform_runtime)
        _build_chain(client, ns)
        yield ns


class TestProfessionalExportTamper:
    @pytest.mark.parametrize("target", TAMPER_TARGET_IDS)
    def test_tampered_declared_artifact_blocks_export(self, tamper_api, target):
        """篡改任何一类已声明专业工件：导出 409，绝无 Export 行或可下载 ZIP。"""

        ns = tamper_api
        path = _tamper_targets(ns)[target]
        assert path.is_file(), target
        original_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        with path.open("ab") as handle:
            handle.write(b"\ntampered-evidence")
        assert hashlib.sha256(path.read_bytes()).hexdigest() != original_sha

        resp = ns.client.post(f"/api/results/{ns.kriging_result_id}/exports")
        assert resp.status_code == 409, resp.text
        error = assert_envelope(resp.json())
        assert error["code"] == "PROFESSIONAL_EVIDENCE_HASH_MISMATCH"
        assert_no_path_leak(resp.json(), "$.export_tampered")

        # fail-closed：仓储中无导出记录，盘上无任何 zip 包与暂存目录
        with ns.runtime.session() as session:
            assert session.query(tables.Export).all() == []
        assert list(ns.runtime.settings.exports_dir.rglob("*.zip")) == []
        assert list(ns.runtime.settings.exports_dir.rglob("export-*")) == []

    @pytest.mark.parametrize("target", TAMPER_TARGET_IDS)
    def test_missing_declared_artifact_blocks_export(self, tamper_api, target):
        """删除任何一类已声明专业工件：与篡改同码 409，绝不静默省略。"""

        ns = tamper_api
        path = _tamper_targets(ns)[target]
        assert path.is_file(), target
        path.unlink()

        resp = ns.client.post(f"/api/results/{ns.kriging_result_id}/exports")
        assert resp.status_code == 409, resp.text
        error = assert_envelope(resp.json())
        assert error["code"] == "PROFESSIONAL_EVIDENCE_HASH_MISMATCH"
        assert_no_path_leak(resp.json(), "$.export_missing")

        with ns.runtime.session() as session:
            assert session.query(tables.Export).all() == []
        assert list(ns.runtime.settings.exports_dir.rglob("*.zip")) == []
        assert list(ns.runtime.settings.exports_dir.rglob("export-*")) == []
