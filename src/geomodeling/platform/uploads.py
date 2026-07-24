"""Atomic, size-bounded upload storage.

Submitted filenames are metadata only: the server generates storage paths
and rejects path-like names outright. Files stream to a ``.part`` path
while being hashed and counted, then move into place with ``os.replace``
so a half-written upload is never registered as a source.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from geomodeling.platform.errors import PlatformError
from geomodeling.platform.settings import PlatformSettings

UPLOAD_TOO_LARGE = "UPLOAD_TOO_LARGE"
UPLOAD_UNSUPPORTED_FORMAT = "UPLOAD_UNSUPPORTED_FORMAT"
UPLOAD_FILENAME_UNSAFE = "UPLOAD_FILENAME_UNSAFE"

ALLOWED_SUFFIXES = frozenset({"csv", "xlsx"})
CHUNK_SIZE = 1 << 20  # 1 MiB


@dataclass(frozen=True)
class UploadReceipt:
    original_filename: str
    suffix: str
    size_bytes: int
    sha256: str
    part_path: Path


def _validate_filename(filename: str) -> str:
    """Reject empty or path-like filenames; return the bare name."""

    name = (filename or "").strip()
    if not name:
        raise PlatformError(UPLOAD_FILENAME_UNSAFE, "文件名为空")
    if name in (".", "..") or "/" in name or "\\" in name or "\x00" in name:
        raise PlatformError(
            UPLOAD_FILENAME_UNSAFE,
            "文件名不允许包含路径分隔符",
            {"filename": name},
        )
    return name


def _validate_suffix(name: str) -> str:
    suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if suffix not in ALLOWED_SUFFIXES:
        raise PlatformError(
            UPLOAD_UNSUPPORTED_FORMAT,
            f"不支持的文件格式：.{suffix or '(无扩展名)'}（仅接受 .csv / .xlsx）",
            {"suffix": suffix},
        )
    return suffix


def store_upload_stream(
    settings: PlatformSettings,
    stream: BinaryIO,
    filename: str,
    *,
    chunk_size: int = CHUNK_SIZE,
) -> UploadReceipt:
    """Stream an upload to a server-generated ``.part`` file.

    The byte limit is enforced while streaming; an oversize upload deletes
    the partial file and raises 413. Nothing is moved into its final
    location here — call :func:`finalize_upload` once the dataset row
    exists.
    """

    name = _validate_filename(filename)
    suffix = _validate_suffix(name)

    part_path = settings.uploads_dir / "_incoming" / f"{uuid.uuid4().hex}.part"
    part_path.parent.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha256()
    size = 0
    try:
        with part_path.open("xb") as handle:
            while True:
                chunk = stream.read(chunk_size)
                if not chunk:
                    break
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise PlatformError(
                        UPLOAD_TOO_LARGE,
                        f"文件超过上传上限（{settings.max_upload_bytes} 字节）",
                        {"size_bytes": size, "max_upload_bytes": settings.max_upload_bytes},
                        http_status=413,
                    )
                digest.update(chunk)
                handle.write(chunk)
    except BaseException:
        part_path.unlink(missing_ok=True)
        raise

    return UploadReceipt(
        original_filename=name,
        suffix=suffix,
        size_bytes=size,
        sha256=digest.hexdigest(),
        part_path=part_path,
    )


def finalize_upload(receipt: UploadReceipt, final_path: Path) -> Path:
    """Move the staged ``.part`` file to its final dataset location."""

    final_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(receipt.part_path, final_path)
    return final_path


def discard_upload(receipt: UploadReceipt) -> None:
    """Best-effort cleanup when the dataset version cannot be registered."""

    receipt.part_path.unlink(missing_ok=True)
