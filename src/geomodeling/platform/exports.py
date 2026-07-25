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
"""

from __future__ import annotations

import hashlib
import json
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

DOMAIN_EVIDENCE_MISSING = "DOMAIN_EVIDENCE_MISSING"
DOMAIN_EVIDENCE_HASH_MISMATCH = "DOMAIN_EVIDENCE_HASH_MISMATCH"
DOMAIN_EVIDENCE_DIR = "domain_evidence"

# 导出契约固定的五个分层 CSV（parquet 溯源表不进入导出包）。
_DOMAIN_EVIDENCE_LAYERS = (
    "source_records",
    "invalid_records",
    "rejected_3sigma",
    "accepted_modeling",
    "aggregated_nodes",
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
        # tmp_dir 可能含 domain_evidence/ 子目录，整体递归清理。
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except BaseException:
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
