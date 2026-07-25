"""v0.5 microseismic multipart import API and safe derivation evidence.

The browser posts the registered DAT bundle as one multipart request; the
server streams the files into a request-specific staging directory under
``microseismic_staging_dir`` (safe-basename validation, hash-while-streaming,
per-file and total byte limits), then hands the directory to the atomic
Task 6 import adapter. The derivation endpoint reads the internal report
through a deterministic settings path and answers with a scrubbed whitelist
DTO — public responses never carry local paths, file bodies, or stack traces.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, UploadFile

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

logger = logging.getLogger("geomodeling.api.microseismic")

router = APIRouter(tags=["v0.5-microseismic"])

ENV_MICROSEISMIC_CONFIG = "GEOMODELING_MICROSEISMIC_CONFIG"
DEFAULT_MICROSEISMIC_CONFIG = "config/microseismic.yaml"

MICROSEISMIC_BUNDLE_INVALID = "MICROSEISMIC_BUNDLE_INVALID"
MICROSEISMIC_UPLOAD_TOO_LARGE = "MICROSEISMIC_UPLOAD_TOO_LARGE"
MICROSEISMIC_DERIVATION_NOT_FOUND = "MICROSEISMIC_DERIVATION_NOT_FOUND"
DATASET_NOT_MICROSEISMIC = "DATASET_NOT_MICROSEISMIC"

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
    """

    staging_dir.mkdir(parents=True, exist_ok=False)
    seen: dict[str, str] = {}
    staged: list[StagedDatFile] = []
    total_bytes = 0
    for upload in files:
        try:
            original = upload.filename or ""
            name = _safe_dat_basename(original)
            if name in seen:
                raise PlatformError(
                    MICROSEISMIC_BUNDLE_INVALID,
                    f"重复的 DAT 文件名：{name}",
                    {
                        "file_name": name,
                        "first_client_path": seen[name],
                        "second_client_path": original,
                    },
                    http_status=422,
                )
            seen[name] = original
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
    return public_derivation(record, report)
