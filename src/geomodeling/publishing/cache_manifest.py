"""Pinned remote tile manifest for the published voxel cache.

The manifest pins the cache's relative tile paths and a digest over the
tile bytes. The voxel-cells API verifies the remote file set and content
against it before any parsing, so a wrong/stale/mixed cache publication
fails closed with an explicit diagnostic (including the computed digest,
so an intentional cache regeneration can re-pin the manifest).

Digest algorithm (kept trivially recomputable by hand):

    per tile, sorted by relative path:  sha256(path_utf8 + b"\\x00" + bytes)
    manifest digest:                    sha256("path:hex\\n" joined lines)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .s3mb import S3MBContractError

DEFAULT_MANIFEST_PATH = "config/s3m_cache_manifest.json"


@dataclass(frozen=True)
class CacheManifest:
    cache_data_name: str
    tiles: tuple[str, ...]
    digest_sha256: str

    @property
    def tile_count(self) -> int:
        return len(self.tiles)


def load_manifest(path: str | Path = DEFAULT_MANIFEST_PATH) -> CacheManifest:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return CacheManifest(
        cache_data_name=raw["cache_data_name"],
        tiles=tuple(raw["tiles"]),
        digest_sha256=raw["digest_sha256"],
    )


def compute_manifest_digest(tiles: list[tuple[str, bytes]]) -> str:
    ordered = sorted(tiles, key=lambda item: item[0])
    lines = [
        f"{rel}:{hashlib.sha256(rel.encode('utf-8') + b'\x00' + data).hexdigest()}"
        for rel, data in ordered
    ]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def verify_tile_set(actual_paths: list[str], manifest: CacheManifest) -> None:
    """Fail closed unless the enumerated paths match the pinned set exactly."""

    actual = sorted(actual_paths)
    expected = sorted(manifest.tiles)
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        raise S3MBContractError(
            "远程瓦片清单不符："
            f"期望 {len(expected)} 个，实际 {len(actual)} 个；"
            f"缺失 {missing[:3] or '无'}，多出 {extra[:3] or '无'}"
        )


def verify_manifest_digest(tiles: list[tuple[str, bytes]], manifest: CacheManifest) -> str:
    """Fail closed unless the fetched bytes reproduce the pinned digest."""

    verify_tile_set([rel for rel, _ in tiles], manifest)
    actual = compute_manifest_digest(tiles)
    if actual != manifest.digest_sha256:
        raise S3MBContractError(
            "瓦片 manifest digest 不符："
            f"固定值 {manifest.digest_sha256}，实际计算 {actual}。"
            "缓存被改动或发布错误；若为有意重新生成，请重算并更新 config/s3m_cache_manifest.json"
        )
    return actual
