"""Evidence export bundles (ZIP) for formal results.

The package always contains the manifest, result metadata, public and
per-candidate metrics, the dataset quality report, formal-selection
history, failed-candidate evidence, and the full grid as CSV. Files are
written to a temporary directory, hashed, then atomically replaced.

When the dataset profile declares ``microseismic_dat_bundle``, the seven
domain evidence files declared by the validated derivation report (source
manifest, derivation report, and the five layered CSVs whose names embed
the run's own row counts) are added under ``domain_evidence/``. Every
copied file carries its SHA-256 and byte size in the ZIP manifest; missing
or corrupted declared evidence blocks the export instead of being silently
omitted. Generic datasets keep the seven-file package unchanged.

When the candidate owns a registered professional artifact set
(``ProfessionalResultArtifacts.manifest_json``), capability-aware
professional evidence is added under ``professional/`` (设计 §16/§17):
the linked diagnosis (variogram CSVs, fitted models, diagnosis metadata)
plus the immutable confirmation snapshot, the neighborhood summary, fold
assignments and out-of-fold predictions converted from parquet to CSV, a
bounded residual summary recomputed from the OOF table, uncertainty-grid
metadata (the large ``.npz`` arrays themselves stay in the registered
compressed artifacts), and every successfully saved anomaly extraction.
Artifact identity is read only from the registered manifests; every
declared artifact is re-hashed before anything is written, and any missing
or hash-mismatched declared file aborts the whole export with
``PROFESSIONAL_EVIDENCE_HASH_MISMATCH`` (fail-closed: no Export row, no
downloadable ZIP). IDW's missing native Kriging variance is not a failure:
``professional/manifest.json`` records the ``not_applicable`` capability
and no Kriging standard deviation metadata file is emitted. Legacy
candidates (no professional artifact row) keep the export byte-identical
to the current behavior.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from geomodeling.microseismic.platform_adapter import SOURCE_KIND
from geomodeling.platform import tables
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.settings import PlatformSettings

logger = logging.getLogger("geomodeling.platform.exports")

DOMAIN_EVIDENCE_MISSING = "DOMAIN_EVIDENCE_MISSING"
DOMAIN_EVIDENCE_HASH_MISMATCH = "DOMAIN_EVIDENCE_HASH_MISMATCH"
DOMAIN_EVIDENCE_DIR = "domain_evidence"

PROFESSIONAL_EVIDENCE_HASH_MISMATCH = "PROFESSIONAL_EVIDENCE_HASH_MISMATCH"
PROFESSIONAL_EVIDENCE_DIR = "professional"

# 导出契约固定的五个分层 CSV（parquet 溯源表不进入导出包）。
_DOMAIN_EVIDENCE_LAYERS = (
    "source_records",
    "invalid_records",
    "rejected_3sigma",
    "accepted_modeling",
    "aggregated_nodes",
)

# ---------------------------------------------------------------------------
# 专业证据固定逻辑名映射（设计 §16）：只读已登记 manifest，按映射复制/转换
# ---------------------------------------------------------------------------

# 候选专业 manifest 逻辑名 → ZIP 文件名（逐位复制）
_PROFESSIONAL_COPY_MAP = {
    "neighborhood_summary": "neighborhood.json",
}
# 候选专业 manifest 逻辑名（parquet）→ ZIP CSV（转换导出可控表）
_PROFESSIONAL_PARQUET_MAP = {
    "fold_assignments": "fold_assignments.csv",
    "out_of_fold_predictions": "out_of_fold_predictions.csv",
}
# 诊断 manifest 逻辑名 → ZIP 文件名（逐位复制；经确认快照关联成功诊断）
_PROFESSIONAL_DIAGNOSIS_MAP = {
    "metadata": "diagnosis.json",
    "omnidirectional": "variogram_omnidirectional.csv",
    "directional": "variogram_directional.csv",
    "fitted_models": "fitted_models.json",
}
# 不确定性网格逻辑名 → 元数据文件名：大数组不进 ZIP，只导出登记身份与能力
_PROFESSIONAL_UNCERTAINTY_METADATA_MAP = {
    "empirical_error_scale": "empirical_error_scale_metadata.json",
    "kriging_standard_deviation": "kriging_standard_deviation_metadata.json",
}
# 异常提取 manifest 逻辑名 → anomaly_extractions/<id>/ 文件名（逐位复制）
_PROFESSIONAL_ANOMALY_MAP = {
    "components": "components.csv",
    "summary": "summary.json",
    "mask": "mask.npz",
}
# 导出必须能从候选专业 manifest 解析的最低工件集合（物化完成态）
_PROFESSIONAL_REQUIRED_ARTIFACTS = frozenset(
    {
        "metadata",
        "empirical_error_scale",
        *_PROFESSIONAL_COPY_MAP,
        *_PROFESSIONAL_PARQUET_MAP,
    }
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_domain_evidence(
    settings: PlatformSettings, case_id: str, dataset_id: str, tmp_dir: Path
) -> list[dict[str, Any]]:
    """Copy the declared microseismic domain evidence into ``tmp_dir``.

    File identities come from the validated derivation report (layered names
    embed the run's own row counts), resolved only inside the deterministic
    settings dataset directory. Every copied file is hashed and size-pinned;
    a missing or hash-mismatched declared file blocks the whole export.
    """

    dataset_dir = settings.microseismic_dataset_dir(case_id, dataset_id)
    report_path = dataset_dir / "derived" / "derivation_report.json"
    if not report_path.is_file():
        raise PlatformError(
            DOMAIN_EVIDENCE_MISSING,
            "微震派生报告缺失，领域证据导出已阻断",
            {"file": "derivation_report.json"},
            http_status=409,
        )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    artifacts = report.get("artifacts") or {}

    planned: list[tuple[str, Path, dict[str, Any] | None]] = [
        ("source_manifest.json", dataset_dir / "source" / "source_manifest.json", None),
        ("derivation_report.json", report_path, None),
    ]
    for key in _DOMAIN_EVIDENCE_LAYERS:
        declared = artifacts.get(key)
        declared_file = declared.get("file") if isinstance(declared, dict) else None
        if (
            not isinstance(declared_file, str)
            or not declared_file
            or declared_file != Path(declared_file).name
        ):
            raise PlatformError(
                DOMAIN_EVIDENCE_MISSING,
                "派生报告未声明该分层工件的安全文件名，领域证据导出已阻断",
                {"artifact": key},
                http_status=409,
            )
        planned.append((declared_file, dataset_dir / "derived" / declared_file, declared))

    evidence_dir = tmp_dir / DOMAIN_EVIDENCE_DIR
    evidence_dir.mkdir()
    entries: list[dict[str, Any]] = []
    for file_name, source, declared in planned:
        if not source.is_file():
            raise PlatformError(
                DOMAIN_EVIDENCE_MISSING,
                "声明的领域证据文件缺失，导出已阻断（不静默省略）",
                {"file": file_name},
                http_status=409,
            )
        digest = _sha256(source)
        if declared is not None and declared.get("sha256") != digest:
            raise PlatformError(
                DOMAIN_EVIDENCE_HASH_MISMATCH,
                "领域证据哈希与派生报告声明不符，导出已阻断",
                {"file": file_name},
                http_status=409,
            )
        shutil.copy2(source, evidence_dir / file_name)
        entry: dict[str, Any] = {
            "file": file_name,
            "arcname": f"{DOMAIN_EVIDENCE_DIR}/{file_name}",
            "size_bytes": source.stat().st_size,
            "sha256": digest,
        }
        if declared is not None and "rows" in declared:
            entry["rows"] = declared["rows"]
        entries.append(entry)
    return entries


# ---------------------------------------------------------------------------
# 专业证据装配（设计 §16/§17）：声明先全量校验（fail-closed），再复制/转换
# ---------------------------------------------------------------------------


def _professional_evidence_error(artifact: str) -> PlatformError:
    """声明的专业证据缺失或哈希不符：整体导出 409 fail-closed（不静默省略）。"""

    return PlatformError(
        PROFESSIONAL_EVIDENCE_HASH_MISMATCH,
        "声明的专业证据缺失或哈希不符，导出已阻断（不静默省略）",
        {"artifact": artifact},
        http_status=409,
    )


def _verify_declared_artifacts(
    manifest: dict[str, Any], *, owner: str
) -> dict[str, tuple[Path, str, int]]:
    """重算 manifest 声明的每件工件 SHA-256 与大小，返回 逻辑名 → (路径, 哈希, 字节)。

    任何缺失、大小或哈希不匹配都以 ``PROFESSIONAL_EVIDENCE_HASH_MISMATCH``
    结构化失败（与 ``verify_manifest`` 同款 fail-closed 语义）；登记
    ``file`` 必须是纯基名，绝不接受携带目录的身份。
    """

    artifacts = manifest.get("artifacts") if isinstance(manifest, dict) else None
    directory = manifest.get("directory") if isinstance(manifest, dict) else None
    if not isinstance(artifacts, dict) or not artifacts or not directory:
        raise _professional_evidence_error(owner)
    base = Path(directory)
    verified: dict[str, tuple[Path, str, int]] = {}
    for logical, entry in artifacts.items():
        file_name = entry.get("file") if isinstance(entry, dict) else None
        if not isinstance(file_name, str) or not file_name or file_name != Path(file_name).name:
            raise _professional_evidence_error(logical)
        path = base / file_name
        if not path.is_file():
            raise _professional_evidence_error(logical)
        digest = _sha256(path)
        size = path.stat().st_size
        if digest != entry.get("sha256") or size != entry.get("bytes"):
            raise _professional_evidence_error(logical)
        verified[logical] = (path, digest, size)
    return verified


def _copy_verified_entry(
    verified: tuple[Path, str, int], dest: Path, arcname: str
) -> dict[str, Any]:
    """逐位复制已校验工件并返回 root manifest 条目（哈希用校验时身份）。"""

    source, digest, size = verified
    shutil.copy2(source, dest)
    return {"file": dest.name, "arcname": arcname, "size_bytes": size, "sha256": digest}


def _write_generated_entry(dest: Path, arcname: str, data: bytes) -> dict[str, Any]:
    """落盘导出期生成的文件（转换 CSV/摘要 JSON）并返回 root manifest 条目。"""

    dest.write_bytes(data)
    return {
        "file": dest.name,
        "arcname": arcname,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _json_export_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _residual_summary_payload(oof: pd.DataFrame, *, source_sha256: str) -> dict[str, Any]:
    """从 OOF 计算有界残差摘要：count/mean/std/min/max/abs 分位数、NoData 计数。

    这是摘要而非全表（全表走 out_of_fold_predictions.csv）；NoData 行为
    ``is_nodata`` 或残差非有限的记录。
    """

    residuals = oof["residual"].to_numpy(dtype="float64")
    nodata_mask = oof["is_nodata"].to_numpy(dtype=bool) | ~np.isfinite(residuals)
    valid = residuals[~nodata_mask]
    summary: dict[str, Any] = {
        "source_artifact": "out_of_fold_predictions",
        "source_sha256": source_sha256,
        "row_count": int(residuals.size),
        "count": int(valid.size),
        "nodata_count": int(nodata_mask.sum()),
        "mean": None,
        "std": None,
        "min": None,
        "max": None,
        "abs_quantiles": None,
    }
    if valid.size:
        abs_residuals = np.abs(valid)
        summary.update(
            mean=float(valid.mean()),
            std=float(valid.std()),
            min=float(valid.min()),
            max=float(valid.max()),
            abs_quantiles={
                f"p{quantile}": float(np.quantile(abs_residuals, quantile / 100.0))
                for quantile in (50, 90, 95, 99)
            },
        )
    return summary


def _load_professional_export_context(session, result_id: str) -> dict[str, Any] | None:
    """读取候选的专业证据登记身份（纯 DB 读取，不做任何 filesystem 校验）。

    只读 ``ProfessionalResultArtifacts.manifest_json``、经确认关联的诊断与
    已成功保存的异常提取 manifest；legacy 候选（无工件行）返回 ``None``，
    导出行为与现状完全一致。
    """

    artifacts_row = (
        session.query(tables.ProfessionalResultArtifacts)
        .filter(tables.ProfessionalResultArtifacts.candidate_result_id == result_id)
        .one_or_none()
    )
    if artifacts_row is None:
        return None

    confirmation = None
    diagnosis = None
    if artifacts_row.confirmation_id:
        confirmation_row = session.get(
            tables.ProfessionalConfirmation, artifacts_row.confirmation_id
        )
        if confirmation_row is not None:
            confirmation = {
                "confirmation_id": confirmation_row.id,
                "diagnosis_id": confirmation_row.diagnostic_id,
                "fingerprint": confirmation_row.fingerprint,
                "note": confirmation_row.note,
                "config": tables.loads_canonical(confirmation_row.config_json),
                "created_at": confirmation_row.created_at,
            }
            diagnosis_row = session.get(
                tables.ProfessionalDiagnostic, confirmation_row.diagnostic_id
            )
            if diagnosis_row is not None:
                diagnosis = {
                    "id": diagnosis_row.id,
                    "status": diagnosis_row.status,
                    "manifest": tables.loads_canonical(diagnosis_row.manifest_json),
                }

    anomaly_rows = (
        session.query(tables.AnomalyExtraction)
        .filter(
            tables.AnomalyExtraction.candidate_result_id == result_id,
            tables.AnomalyExtraction.status == "succeeded",
        )
        .order_by(tables.AnomalyExtraction.created_at.asc(), tables.AnomalyExtraction.id.asc())
        .all()
    )
    return {
        "manifest": tables.loads_canonical(artifacts_row.manifest_json),
        "confirmation_id": artifacts_row.confirmation_id,
        "confirmation": confirmation,
        "diagnosis": diagnosis,
        "anomalies": [
            {"extraction_id": row.id, "manifest": tables.loads_canonical(row.manifest_json)}
            for row in anomaly_rows
        ],
    }


def _copy_professional_evidence(
    tmp_dir: Path,
    *,
    algorithm: str,
    context: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """把已登记的专业证据复制/转换为 ``tmp_dir/professional/``。

    工件身份只来自 ``ProfessionalResultArtifacts.manifest_json``、经确认关
    联的成功诊断 manifest 与已成功保存的异常提取 manifest。任何声明工件
    缺失或哈希不符 → 409 ``PROFESSIONAL_EVIDENCE_HASH_MISMATCH``
    fail-closed；IDW 缺 Kriging 方差不视为失败（capability 记录
    ``not_applicable``，不生成对应元数据文件）。返回逐文件条目（写入
    root manifest 的 size/SHA-256）与专业节元数据。
    """

    manifest = context.get("manifest")
    if not isinstance(manifest, dict) or not manifest:
        raise _professional_evidence_error("candidate_result_artifacts")
    capabilities = manifest.get("capabilities") or {}

    # 1) 全部声明先校验（fail-closed），再写任何文件
    pro_verified = _verify_declared_artifacts(manifest, owner="candidate_result_artifacts")
    required = set(_PROFESSIONAL_REQUIRED_ARTIFACTS)
    if capabilities.get("native_kriging_std") == "supported":
        required.add("kriging_standard_deviation")
    for logical in sorted(required - pro_verified.keys()):
        raise _professional_evidence_error(logical)

    confirmation = None
    diag_verified: dict[str, tuple[Path, str, int]] = {}
    if context.get("confirmation_id"):
        confirmation = context.get("confirmation")
        if confirmation is None:
            raise _professional_evidence_error("anisotropy_confirmation")
        diagnosis = context.get("diagnosis")
        if (
            not isinstance(diagnosis, dict)
            or diagnosis.get("status") != "succeeded"
            or not diagnosis.get("manifest")
        ):
            raise _professional_evidence_error("diagnosis")
        diag_verified = _verify_declared_artifacts(diagnosis["manifest"], owner="diagnosis")
        for logical in sorted(set(_PROFESSIONAL_DIAGNOSIS_MAP) - diag_verified.keys()):
            raise _professional_evidence_error(logical)

    anomaly_verified: list[tuple[str, dict[str, tuple[Path, str, int]]]] = []
    for item in context.get("anomalies") or []:
        extraction_id = item.get("extraction_id")
        verified = _verify_declared_artifacts(
            item.get("manifest") or {}, owner=f"anomaly_extraction:{extraction_id}"
        )
        for logical in sorted(set(_PROFESSIONAL_ANOMALY_MAP) - verified.keys()):
            raise _professional_evidence_error(logical)
        anomaly_verified.append((extraction_id, verified))

    # 2) 复制/转换（顺序即设计 §16 树顺序，也是 root manifest 条目顺序）
    evidence_dir = tmp_dir / PROFESSIONAL_EVIDENCE_DIR
    evidence_dir.mkdir()
    entries: list[dict[str, Any]] = []

    def _arcname(name: str) -> str:
        return f"{PROFESSIONAL_EVIDENCE_DIR}/{name}"

    # 诊断证据（逐位复制）+ 不可变确认快照
    if confirmation is not None:
        for logical, name in _PROFESSIONAL_DIAGNOSIS_MAP.items():
            entries.append(
                _copy_verified_entry(diag_verified[logical], evidence_dir / name, _arcname(name))
            )
        entries.append(
            _write_generated_entry(
                evidence_dir / "anisotropy_confirmation.json",
                _arcname("anisotropy_confirmation.json"),
                _json_export_bytes(confirmation),
            )
        )

    # 邻域摘要（逐位复制）
    for logical, name in _PROFESSIONAL_COPY_MAP.items():
        entries.append(
            _copy_verified_entry(pro_verified[logical], evidence_dir / name, _arcname(name))
        )

    # 折分/OOF：parquet → CSV 转换导出（可控表；登记哈希已在上方校验）
    for logical, name in _PROFESSIONAL_PARQUET_MAP.items():
        frame = pd.read_parquet(pro_verified[logical][0])
        dest = evidence_dir / name
        frame.to_csv(dest, index=False)
        entries.append(
            {
                "file": name,
                "arcname": _arcname(name),
                "size_bytes": dest.stat().st_size,
                "sha256": _sha256(dest),
            }
        )

    # 残差摘要：从已校验的 OOF 重算的有界统计，不是全表
    oof_path, oof_sha256, _ = pro_verified["out_of_fold_predictions"]
    entries.append(
        _write_generated_entry(
            evidence_dir / "residual_summary.json",
            _arcname("residual_summary.json"),
            _json_export_bytes(
                _residual_summary_payload(
                    pd.read_parquet(oof_path), source_sha256=oof_sha256
                )
            ),
        )
    )

    # 不确定性网格：只导出元数据（能力/覆盖率/登记身份），大数组留在原压缩工件
    pro_metadata = json.loads(pro_verified["metadata"][0].read_text(encoding="utf-8"))
    for logical, name in _PROFESSIONAL_UNCERTAINTY_METADATA_MAP.items():
        if logical not in pro_verified:
            # capability not_applicable（IDW 原生标准差）：不生成文件，不算失败
            continue
        path, digest, size = pro_verified[logical]
        payload = {
            "artifact": path.name,
            **((pro_metadata.get("artifacts") or {}).get(logical) or {}),
            "file": path.name,
            "sha256": digest,
            "bytes": size,
            "grid": pro_metadata.get("grid"),
            "transform_fingerprint": pro_metadata.get("transform_fingerprint"),
        }
        entries.append(
            _write_generated_entry(evidence_dir / name, _arcname(name), _json_export_bytes(payload))
        )

    # 已成功保存的异常提取：每次提取的 components/summary/mask 逐位复制
    for extraction_id, verified in anomaly_verified:
        extraction_dir = evidence_dir / "anomaly_extractions" / extraction_id
        extraction_dir.mkdir(parents=True)
        for logical, name in _PROFESSIONAL_ANOMALY_MAP.items():
            entries.append(
                _copy_verified_entry(
                    verified[logical],
                    extraction_dir / name,
                    f"{_arcname('anomaly_extractions')}/{extraction_id}/{name}",
                )
            )

    # 专业 manifest：记录算法适用性；服务器目录绝不进入导出包
    sanitized = {key: value for key, value in manifest.items() if key != "directory"}
    entries.append(
        _write_generated_entry(
            evidence_dir / "manifest.json",
            _arcname("manifest.json"),
            _json_export_bytes(sanitized),
        )
    )

    section = {
        "algorithm": algorithm,
        "capabilities": capabilities,
        "confirmation_id": confirmation["confirmation_id"] if confirmation else None,
        "diagnosis_id": confirmation["diagnosis_id"] if confirmation else None,
        "anomaly_extractions": [extraction_id for extraction_id, _ in anomaly_verified],
    }
    return entries, section


def build_export(runtime: PlatformRuntime, result_id: str) -> dict[str, Any]:
    """Build the evidence ZIP for one materialized result."""

    with runtime.session() as session:
        candidate = session.get(tables.CandidateResult, result_id)
        if candidate is None:
            raise PlatformError("CANDIDATE_NOT_FOUND", "成果不存在", {"result_id": result_id}, http_status=404)
        run = session.get(tables.Run, candidate.run_id)
        if run is None:
            raise PlatformError(
                "RUN_NOT_FOUND",
                "成果所属运行缺失，归属链不完整",
                {"result_id": result_id, "run_id": candidate.run_id},
                http_status=409,
            )
        experiment = session.get(tables.Experiment, run.experiment_id)
        if experiment is None:
            raise PlatformError(
                "EXPERIMENT_NOT_FOUND",
                "成果所属实验缺失，归属链不完整",
                {"result_id": result_id},
                http_status=409,
            )
        experiment_params = tables.loads_canonical(experiment.params_json)
        dataset = session.get(tables.DatasetVersion, experiment_params["dataset_version_id"])
        if dataset is None:
            raise PlatformError(
                "DATASET_NOT_FOUND",
                "成果所属数据版本缺失，归属链不完整",
                {"result_id": result_id, "dataset_version_id": experiment_params["dataset_version_id"]},
                http_status=409,
            )
        selections = (
            session.query(tables.FormalSelection)
            .filter(tables.FormalSelection.case_id == experiment.case_id)
            .order_by(tables.FormalSelection.created_at.asc())
            .all()
        )
        siblings = (
            session.query(tables.CandidateResult)
            .filter(tables.CandidateResult.run_id == run.id)
            .all()
        )
        dataset_profile = tables.loads_canonical(dataset.profile_json)
        candidate_metrics = tables.loads_canonical(candidate.metrics_json)
        run_metrics = tables.loads_canonical(run.metrics_json)
        # 专业候选证据上下文（只读登记身份；filesystem 校验在打包阶段进行）。
        # legacy 候选无 ProfessionalResultArtifacts 行 → 保持现状导出。
        professional_context = _load_professional_export_context(session, result_id)

    grid_path = runtime.settings.result_grid(result_id)
    if not grid_path.exists():
        raise PlatformError(
            "RESULT_NOT_MATERIALIZED", "成果尚未生成", {"result_id": result_id}, http_status=409
        )
    metadata = json.loads((grid_path.parent / "metadata.json").read_text(encoding="utf-8"))

    export_id = str(uuid.uuid4())
    package_path = runtime.settings.export_package(export_id)
    package_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="export-", dir=package_path.parent))

    try:
        manifest = {
            "export_id": export_id,
            "candidate_result_id": result_id,
            "run_id": run.id,
            "experiment_id": experiment.id,
            "case_id": experiment.case_id,
            "source_sha256": dataset_profile.get("source_sha256"),
            "standardized_sha256": dataset_profile.get("standardized_sha256"),
            "grid_sha256": metadata.get("grid_sha256"),
            "created_at": tables.utc_now_iso(),
            "files": [],
        }
        files: dict[str, Any] = {
            "metadata.json": metadata,
            "metrics.json": {
                "candidate": candidate_metrics,
                "public_metrics": run_metrics.get("public_metrics", {}),
                "run_progress": {k: v for k, v in run_metrics.items() if k != "public_metrics"},
            },
            "quality.json": dataset_profile.get("quality", {}),
            "formal_selections.json": [
                {
                    "id": s.id,
                    "candidate_result_id": s.candidate_result_id,
                    "selected_by": s.selected_by,
                    "note": s.note,
                    "created_at": s.created_at,
                }
                for s in selections
            ],
            "failed_evidence.json": [
                {
                    "id": row.id,
                    "fingerprint": row.fingerprint,
                    "parameters": tables.loads_canonical(row.params_json),
                    "status": row.status,
                    "error": tables.loads_canonical(row.error_json) if row.error_json else None,
                }
                for row in siblings
                if row.status == "failed"
            ],
        }
        for name, payload in files.items():
            (tmp_dir / name).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            manifest["files"].append(name)

        with np.load(grid_path, allow_pickle=True) as bundle:
            axes = [np.asarray(a, dtype=float) for a in bundle["axes"]]
            values = bundle["values"]
            nodata = bundle["is_nodata"]
        coords = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, len(axes))
        grid_frame = pd.DataFrame(
            {
                "x": coords[:, 0],
                "y": coords[:, 1],
                **({"z": coords[:, 2]} if metadata["dimension"] == "3d" else {}),
                "value": values.reshape(-1),
                "is_nodata": nodata.reshape(-1),
            }
        )
        grid_frame.to_csv(tmp_dir / "grid.csv", index=False)
        manifest["files"].append("grid.csv")

        # 微震导入的数据集：按派生报告声明追加领域证据（缺失即阻断）。
        if dataset_profile.get("source_kind") == SOURCE_KIND:
            evidence_entries = _copy_domain_evidence(
                runtime.settings, experiment.case_id, dataset.id, tmp_dir
            )
            manifest["domain_evidence"] = evidence_entries
            manifest["files"].extend(entry["arcname"] for entry in evidence_entries)

        # 专业候选：按 capability 追加已登记专业证据（声明缺失/哈希不符即
        # 整体 409 fail-closed）；legacy 候选无工件行，导出与现状一致。
        if professional_context is not None:
            professional_entries, professional_section = _copy_professional_evidence(
                tmp_dir,
                algorithm=experiment_params.get("algorithm"),
                context=professional_context,
            )
            professional_section["files"] = professional_entries
            manifest["professional"] = professional_section
            manifest["files"].extend(entry["arcname"] for entry in professional_entries)

        (tmp_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        manifest["files"].append("manifest.json")

        tmp_zip = tmp_dir / "package.zip"
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in manifest["files"]:
                archive.write(tmp_dir / name, arcname=name)
        package_sha = _sha256(tmp_zip)
        os.replace(tmp_zip, package_path)

        with runtime.session() as session:
            session.add(
                tables.Export(
                    id=export_id,
                    case_id=experiment.case_id,
                    candidate_result_id=result_id,
                    package_path=str(package_path),
                    manifest_json=tables.dumps_canonical(manifest),
                )
            )
            session.commit()
        # tmp_dir 可能含 domain_evidence/ 与 professional/ 子目录，整体递归清理。
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except BaseException:
        # 任一导出阶段失败后同样清理暂存目录；清理异常只记日志（含堆栈），
        # 绝不覆盖最初的业务异常（与 platform_adapter 补偿同款模式）。
        try:
            shutil.rmtree(tmp_dir)
        except Exception:  # noqa: BLE001
            logger.exception("export staging cleanup failed: %s", tmp_dir)
        raise

    return {
        "id": export_id,
        "candidate_result_id": result_id,
        "case_id": experiment.case_id,
        "package_sha256": package_sha,
        "file_count": len(manifest["files"]),
        "files": manifest["files"],
        "manifest": manifest,
    }
