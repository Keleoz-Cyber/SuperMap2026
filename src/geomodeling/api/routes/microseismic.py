"""v0.5 microseismic multipart import API and safe derivation evidence.

The browser posts the registered DAT bundle as one multipart request; the
server streams the files into a request-specific staging directory under
``microseismic_staging_dir`` (safe-basename validation, hash-while-streaming,
per-file and total byte limits), then hands the directory to the atomic
Task 6 import adapter. The derivation endpoints read the internal report
through a deterministic settings path and answer with a scrubbed whitelist
DTO — public responses never carry local paths, file bodies, or stack traces.

Artifact downloads and diagnostic points are allowlisted by the artifact
identities declared in the validated derivation report (plus
``source_manifest.json``); declared names must be plain basenames resolved
inside the deterministic settings dataset directory, so no client input is
ever concatenated into a filesystem path.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from fastapi import APIRouter, Depends, Query, UploadFile
from fastapi.responses import FileResponse

from geomodeling.api.deps import get_platform_runtime
from geomodeling.microseismic.config import MicroseismicConfig, load_microseismic_config
from geomodeling.microseismic.platform_adapter import (
    SOURCE_KIND,
    MicroseismicImportBundle,
    import_microseismic_dataset,
)
from geomodeling.platform import PlatformRuntime
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.public_dto import public_dataset, public_derivation
from geomodeling.platform.repositories import DatasetRepository
from geomodeling.platform.schemas import DatasetVersionRecord

logger = logging.getLogger("geomodeling.api.microseismic")

router = APIRouter(tags=["v0.5-microseismic"])

ENV_MICROSEISMIC_CONFIG = "GEOMODELING_MICROSEISMIC_CONFIG"
DEFAULT_MICROSEISMIC_CONFIG = "config/microseismic.yaml"

MICROSEISMIC_BUNDLE_INVALID = "MICROSEISMIC_BUNDLE_INVALID"
MICROSEISMIC_UPLOAD_TOO_LARGE = "MICROSEISMIC_UPLOAD_TOO_LARGE"
MICROSEISMIC_DERIVATION_NOT_FOUND = "MICROSEISMIC_DERIVATION_NOT_FOUND"
MICROSEISMIC_ARTIFACT_NOT_FOUND = "MICROSEISMIC_ARTIFACT_NOT_FOUND"
DATASET_NOT_MICROSEISMIC = "DATASET_NOT_MICROSEISMIC"

# 诊断点端点：单次响应的有界上限；decimate 之外的第二道闸。
MAX_POINTS_SERVED = 5_000

# 点图层公开名 → 派生报告 artifacts 中的逻辑工件名。
POINT_LAYER_ARTIFACTS = {
    "accepted": "accepted_modeling",
    "rejected": "rejected_3sigma",
    "aggregated": "aggregated_nodes",
}

# source_manifest.json 住在 source/ 而非 derived/，是白名单上的唯一额外公开名。
SOURCE_MANIFEST_PUBLIC_NAME = "source_manifest.json"

_ARTIFACT_MEDIA_TYPES = {
    ".csv": "text/csv",
    ".json": "application/json",
    ".parquet": "application/octet-stream",
}

# 真实 22 个 DAT 共 66,880 字节；单文件 1 MiB、包总计 10 MiB 是宽松硬上限。
MAX_DAT_FILE_BYTES = 1 << 20
MAX_BUNDLE_BYTES = 10 * (1 << 20)
CHUNK_SIZE = 1 << 20

# Windows 盘符（含 ``C:secret`` 盘符相对）形态的客户端绝对路径。
_DRIVE_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:")


def get_microseismic_config() -> MicroseismicConfig:
    """Resolve the confirmed microseismic contract config (env-overridable).

    Read per request (no cache) so tests and deployments can point
    ``GEOMODELING_MICROSEISMIC_CONFIG`` at another confirmed contract.
    """

    return load_microseismic_config(os.environ.get(ENV_MICROSEISMIC_CONFIG, DEFAULT_MICROSEISMIC_CONFIG))


@dataclass(frozen=True)
class StagedDatFile:
    file_name: str
    size_bytes: int
    sha256: str


def _safe_dat_basename(filename: str | None) -> str:
    """Identify one upload by its safe basename; never trust client paths.

    Benign relative prefixes (directory-picker uploads) are stripped to the
    basename, the only component ever used on disk. Traversal (``..``),
    absolute paths (POSIX root, UNC, drive letter), NUL bytes and empty names
    are rejected outright.
    """

    raw = (filename or "").strip()
    if not raw:
        raise PlatformError(MICROSEISMIC_BUNDLE_INVALID, "上传文件名为空", http_status=422)
    normalized = raw.replace("\\", "/")
    if "\x00" in normalized:
        raise PlatformError(
            MICROSEISMIC_BUNDLE_INVALID,
            "文件名包含非法字符",
            {"filename": raw},
            http_status=422,
        )
    if normalized.startswith("/") or _DRIVE_ABSOLUTE_RE.match(normalized):
        raise PlatformError(
            MICROSEISMIC_BUNDLE_INVALID,
            "文件名不得为绝对路径",
            {"filename": raw},
            http_status=422,
        )
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise PlatformError(
            MICROSEISMIC_BUNDLE_INVALID,
            "文件名包含路径遍历，已拒绝",
            {"filename": raw},
            http_status=422,
        )
    return parts[-1]


async def _stage_uploads(files: list[UploadFile], staging_dir: Path) -> list[StagedDatFile]:
    """Stream every upload into ``staging_dir`` with hashing and size limits.

    Basenames are validated before any byte is written and duplicates are
    rejected; every upload is closed whether or not its stream succeeded.
    Duplicate detection keys on ``os.path.normcase`` so case-only variants
    (``W1.dat`` vs ``w1.dat``) collide exactly the way the hosting filesystem
    would, instead of crashing later in ``open("xb")``.
    """

    staging_dir.mkdir(parents=True, exist_ok=False)
    seen: dict[str, str] = {}
    staged: list[StagedDatFile] = []
    total_bytes = 0
    for upload in files:
        try:
            original = upload.filename or ""
            name = _safe_dat_basename(original)
            key = os.path.normcase(name)
            if key in seen:
                raise PlatformError(
                    MICROSEISMIC_BUNDLE_INVALID,
                    f"重复的 DAT 文件名：{name}",
                    {
                        "file_name": name,
                        "first_client_path": seen[key],
                        "second_client_path": original,
                    },
                    http_status=422,
                )
            seen[key] = original
            digest = hashlib.sha256()
            size = 0
            with (staging_dir / name).open("xb") as handle:
                while True:
                    chunk = await upload.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_DAT_FILE_BYTES:
                        raise PlatformError(
                            MICROSEISMIC_UPLOAD_TOO_LARGE,
                            f"单个 DAT 文件超过上限（{MAX_DAT_FILE_BYTES} 字节）",
                            {
                                "file_name": name,
                                "size_bytes": size,
                                "max_file_bytes": MAX_DAT_FILE_BYTES,
                            },
                            http_status=413,
                        )
                    total_bytes += len(chunk)
                    if total_bytes > MAX_BUNDLE_BYTES:
                        raise PlatformError(
                            MICROSEISMIC_UPLOAD_TOO_LARGE,
                            f"DAT 文件包总大小超过上限（{MAX_BUNDLE_BYTES} 字节）",
                            {"size_bytes": total_bytes, "max_total_bytes": MAX_BUNDLE_BYTES},
                            http_status=413,
                        )
                    digest.update(chunk)
                    handle.write(chunk)
            staged.append(StagedDatFile(file_name=name, size_bytes=size, sha256=digest.hexdigest()))
        finally:
            await upload.close()
    return staged


def _validate_file_set(config: MicroseismicConfig, staged: list[StagedDatFile]) -> None:
    """The bundle must be exactly the registered DAT set — no more, no less."""

    expected = config.expected_file_names()
    expected_set = set(expected)
    actual_set = {entry.file_name for entry in staged}
    missing = [name for name in expected if name not in actual_set]
    unknown = sorted(name for name in actual_set if name not in expected_set)
    if missing or unknown or len(staged) != len(expected):
        raise PlatformError(
            MICROSEISMIC_BUNDLE_INVALID,
            f"DAT 文件集合必须恰好为登记的 {len(expected)} 个文件",
            {
                "expected_count": len(expected),
                "actual_count": len(staged),
                "missing": missing,
                "unknown": unknown,
            },
            http_status=422,
        )


@router.post("/api/cases/{case_id}/microseismic-imports", status_code=201)
async def import_bundle(
    case_id: str,
    files: list[UploadFile],
    runtime: PlatformRuntime = Depends(get_platform_runtime),
    config: MicroseismicConfig = Depends(get_microseismic_config),
) -> dict[str, Any]:
    settings = runtime.settings
    staging_dir = settings.microseismic_staging_dir() / f"upload-{uuid.uuid4().hex}"
    try:
        staged = await _stage_uploads(files, staging_dir)
        _validate_file_set(config, staged)
        record = import_microseismic_dataset(
            runtime,
            case_id,
            MicroseismicImportBundle(config=config, source_dir=staging_dir),
        )
        return public_dataset(record)
    finally:
        for upload in files:
            try:
                await upload.close()
            except Exception:  # noqa: BLE001
                logger.exception("microseismic import: upload close failed: %s", upload.filename)
        try:
            shutil.rmtree(staging_dir)
        except FileNotFoundError:
            pass
        except Exception:  # noqa: BLE001
            logger.exception("microseismic import: request staging cleanup failed: %s", staging_dir)


@router.get("/api/datasets/{dataset_id}/derivation")
def get_derivation(
    dataset_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    """Public derivation evidence for one microseismic-imported dataset."""

    record, report = _load_microseismic_derivation(runtime, dataset_id)
    return public_derivation(record, report)


def _load_microseismic_derivation(
    runtime: PlatformRuntime, dataset_id: str
) -> tuple[DatasetVersionRecord, dict[str, Any]]:
    """Load the dataset row and its validated internal derivation report.

    Shared by every derivation-evidence endpoint: ownership and source kind
    are verified once, and the report is read through the deterministic
    settings path — never through a client-supplied location.
    """

    with runtime.session() as session:
        record = DatasetRepository(session).get(dataset_id)
    if record.profile.get("source_kind") != SOURCE_KIND:
        raise PlatformError(
            DATASET_NOT_MICROSEISMIC,
            "数据集不是微震 DAT 导入，没有派生证据",
            {"dataset_id": dataset_id},
            http_status=409,
        )
    report_path = (
        runtime.settings.microseismic_dataset_dir(record.case_id, record.id)
        / "derived"
        / "derivation_report.json"
    )
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PlatformError(
            MICROSEISMIC_DERIVATION_NOT_FOUND,
            "派生报告缺失，数据集证据不完整",
            {"dataset_id": dataset_id},
            http_status=404,
        ) from exc
    return record, report


def _resolve_declared_artifact(
    runtime: PlatformRuntime,
    record: DatasetVersionRecord,
    report: dict[str, Any],
    artifact_name: str,
) -> Path:
    """Resolve one public artifact name to a file inside the dataset directory.

    The allowlist is the artifact identity set declared by the validated
    derivation report plus ``source_manifest.json``. Declared file names must
    be plain basenames; anything else (separators, ``..``) is rejected rather
    than concatenated into a path.
    """

    dataset_dir = runtime.settings.microseismic_dataset_dir(record.case_id, record.id)
    if artifact_name == SOURCE_MANIFEST_PUBLIC_NAME:
        candidate = dataset_dir / "source" / SOURCE_MANIFEST_PUBLIC_NAME
    else:
        declared = (report.get("artifacts") or {}).get(artifact_name)
        declared_file = declared.get("file") if isinstance(declared, dict) else None
        if (
            not isinstance(declared_file, str)
            or not declared_file
            or declared_file != Path(declared_file).name
        ):
            raise PlatformError(
                MICROSEISMIC_ARTIFACT_NOT_FOUND,
                "未知的派生工件名",
                {"dataset_id": record.id, "artifact_name": artifact_name},
                http_status=404,
            )
        candidate = dataset_dir / "derived" / declared_file
    if not candidate.is_file():
        raise PlatformError(
            MICROSEISMIC_ARTIFACT_NOT_FOUND,
            "声明的派生工件缺失，数据集证据不完整",
            {"dataset_id": record.id, "artifact_name": artifact_name},
            http_status=404,
        )
    return candidate


@router.get("/api/datasets/{dataset_id}/derivation/artifacts/{artifact_name}")
def download_derivation_artifact(
    dataset_id: str,
    artifact_name: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> FileResponse:
    """Download one allowlisted derivation artifact (validated report names only)."""

    record, report = _load_microseismic_derivation(runtime, dataset_id)
    path = _resolve_declared_artifact(runtime, record, report, artifact_name)
    media_type = _ARTIFACT_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type, filename=path.name)


def _numeric_list(frame: pd.DataFrame, column: str) -> list[float]:
    return pd.to_numeric(frame[column]).astype(float).tolist()


@router.get("/api/datasets/{dataset_id}/derivation/points")
def get_derivation_points(
    dataset_id: str,
    layer: Literal["accepted", "rejected", "aggregated"] = Query(...),
    decimate: int = Query(1, ge=1, le=1000),
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    """Bounded, typed diagnostic points for one derivation layer.

    Rows keep their declared source order; ``decimate`` takes every
    decimate-th row and an additional hard cap keeps responses bounded.
    Numeric fields are arrays of numbers, never string-typed records.
    """

    record, report = _load_microseismic_derivation(runtime, dataset_id)
    artifact_name = POINT_LAYER_ARTIFACTS[layer]
    path = _resolve_declared_artifact(runtime, record, report, artifact_name)

    frame = pd.read_csv(path, encoding="utf-8-sig")
    total = len(frame)
    stride = max(decimate, math.ceil(total / MAX_POINTS_SERVED) if total else 1)
    view = frame.iloc[::stride]

    body: dict[str, Any] = {
        "dataset_id": record.id,
        "layer": layer,
        "total": total,
        "returned": len(view),
        "decimate": stride,
        "x": _numeric_list(view, "X_LOCAL_M"),
        "y": _numeric_list(view, "Y_LOCAL_M"),
        "z": _numeric_list(view, "Z_LOCAL_M"),
        "vx": _numeric_list(view, "VX_KM_S"),
    }
    if layer == "aggregated":
        body["sample_count"] = pd.to_numeric(view["SAMPLE_COUNT"]).astype(int).tolist()
        body["source_sample_ids"] = [str(value).split(";") for value in view["SOURCE_SAMPLE_IDS"]]
        body["vx_min"] = _numeric_list(view, "VX_MIN_KM_S")
        body["vx_max"] = _numeric_list(view, "VX_MAX_KM_S")
        body["vx_std"] = [
            float(value) if pd.notna(value) else None for value in view["VX_SAMPLE_STD_KM_S"]
        ]
    else:
        body["sample_id"] = view["SAMPLE_ID"].astype(str).tolist()
        if layer == "rejected":
            body["filter_reason"] = view["FILTER_REASON"].astype(str).tolist()
            body["depth_zscore"] = _numeric_list(view, "DEPTH_ZSCORE")
            body["vx_zscore"] = _numeric_list(view, "VX_ZSCORE")
    return body
