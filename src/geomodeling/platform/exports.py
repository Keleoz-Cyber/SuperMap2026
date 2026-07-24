"""Evidence export bundles (ZIP) for formal results.

The package always contains the manifest, result metadata, public and
per-candidate metrics, the dataset quality report, formal-selection
history, failed-candidate evidence, and the full grid as CSV. Files are
written to a temporary directory, hashed, then atomically replaced.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from geomodeling.platform import tables
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.settings import PlatformSettings


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_export(runtime: PlatformRuntime, result_id: str) -> dict[str, Any]:
    """Build the evidence ZIP for one materialized result."""

    with runtime.session() as session:
        candidate = session.get(tables.CandidateResult, result_id)
        if candidate is None:
            raise PlatformError("CANDIDATE_NOT_FOUND", "成果不存在", {"result_id": result_id}, http_status=404)
        run = session.get(tables.Run, candidate.run_id)
        experiment = session.get(tables.Experiment, run.experiment_id)
        experiment_params = tables.loads_canonical(experiment.params_json)
        dataset = session.get(tables.DatasetVersion, experiment_params["dataset_version_id"])
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
                    package_path=str(package_path),
                    manifest_json=tables.dumps_canonical(manifest),
                )
            )
            session.commit()
        for leftover in tmp_dir.iterdir():
            leftover.unlink()
        tmp_dir.rmdir()
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
