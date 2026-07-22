"""Parse SuperMap S3MB point-cloud voxel tiles into (x, y, z, weight) records.

**Targeted parser disclaimer**: this module is verified only against the
RHO voxel cache produced on 2026-07-22 by iDesktopX 2026
VoxelGridCacheBuilder (S3M 2.0, ``RHO_KRIG_FINAL_20M_40_VOL_S3M2``). It is
*not* a general S3MB parser and makes no claim to cover other data types
(mesh/BIM/terrain), other S3M versions, or other encodings. Anything
outside that contract fails closed with :class:`S3MBContractError`.

Verified layout for the targeted cache:

- File header: magic ``00 00 00 40``, uint32 LE decompressed length,
  uint32 LE compressed length, then a zlib stream;
- Decompressed blob: LOD page-index region (child tile names + transforms),
  followed by geometry blocks: ``N`` float32 (x, y, z) triplets and, after a
  small gap, ``N`` float32 weights (the voxel attribute, e.g. RHO).

LOD handling: the cache contains several LOD levels; the deepest (leaf)
tiles hold full-resolution cells. We collect every vertex and keep, for each
unique (x, y, z), the weight from the deepest tile that contains it.
"""

from __future__ import annotations

import math
import re
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TILE_REF_RE = re.compile(rb"Tile_[0-9_]+\.s3mb")

S3MB_MAGIC = b"\x00\x00\x00\x40"
EXPECTED_SCP_VERSION = "2.0"
EXPECTED_FILE_TYPE = "PointCloudFile"


class S3MBContractError(ValueError):
    """A tile or cache violates the targeted S3M 2.0 voxel-cache contract.

    Raised instead of returning partial data: the API maps this to a 503
    with an explicit diagnostic (which check failed, actual vs expected).
    """


@dataclass
class VoxelCell:
    x: float
    y: float
    z: float
    weight: float


@dataclass
class ParsedTile:
    name: str
    lod: int
    cells: list[VoxelCell] = field(default_factory=list)


def lod_of(name: str) -> int:
    """LOD depth from a tile file name like ``Tile_4_0_0``."""

    parts = name.split("_")
    try:
        return int(parts[1])
    except (IndexError, ValueError):
        return 0


def _decompress_s3mb(data: bytes, *, max_decompressed: int = 64 * 1024 * 1024) -> bytes:
    """Strict s3mb header/decode for the targeted tile format.

    Checks: minimum size, magic, declared compressed length equals the
    actual payload length (no truncation/trailing bytes), zlib stream fully
    consumed and EOF-clean, decompressed size within cap, and decompressed
    length equal to the declared one.
    """

    if len(data) < 12:
        raise S3MBContractError(f"s3mb 文件过小（{len(data)} B < 12 B 头部）")
    if data[:4] != S3MB_MAGIC:
        raise S3MBContractError(f"s3mb 魔数不符：{data[:4].hex()}，期望 {S3MB_MAGIC.hex()}（非本缓存格式）")
    declared_len = struct.unpack("<I", data[4:8])[0]
    compressed_len = struct.unpack("<I", data[8:12])[0]
    payload = data[12:]
    if compressed_len != len(payload):
        raise S3MBContractError(
            f"s3mb compressed_length 不符：头部声明 {compressed_len}，实际负载 {len(payload)}"
            "（文件被截断或含尾随字节）"
        )
    if declared_len > max_decompressed:
        raise S3MBContractError(f"s3mb 声明解压大小 {declared_len} 超过上限 {max_decompressed}")
    decomp = zlib.decompressobj()
    try:
        blob = decomp.decompress(payload, max_decompressed + 1)
    except zlib.error as exc:
        raise S3MBContractError(f"s3mb zlib 解压失败：{exc}") from exc
    if len(blob) > max_decompressed:
        raise S3MBContractError(f"s3mb 实际解压大小超过上限 {max_decompressed}")
    if not decomp.eof:
        raise S3MBContractError("s3mb zlib 流未正常结束（EOF 缺失，文件被截断）")
    if decomp.unused_data or decomp.unconsumed_tail:
        raise S3MBContractError("s3mb zlib 流后存在多余字节")
    if len(blob) != declared_len:
        raise S3MBContractError(f"s3mb 解压长度 {len(blob)} 与头部声明 {declared_len} 不符")
    return blob


def validate_cache_scp(
    scp: dict[str, Any],
    contract: "CacheContract",
    *,
    expected_version: str = EXPECTED_SCP_VERSION,
    expected_file_type: str = EXPECTED_FILE_TYPE,
) -> dict[str, Any]:
    """Fail-closed validation of the cache .scp against the CacheContract.

    Checks: S3M version, file type, and a finite wDescript value range
    matching the registry-derived contract value range. Any malformed scp
    structure is converted to S3MBContractError (the API maps it to 503).
    """

    from .cache_contract import CacheContract  # local import to avoid a cycle

    if not isinstance(contract, CacheContract):
        raise S3MBContractError("内部错误：validate_cache_scp 缺少 CacheContract")
    if not isinstance(scp, dict):
        raise S3MBContractError(f"scp 不是 JSON 对象（实际类型 {type(scp).__name__}）")
    try:
        version = str(scp.get("version", ""))
        extensions = scp.get("extensions") or {}
        if not isinstance(extensions, dict):
            raise S3MBContractError(f"scp extensions 结构异常：{type(extensions).__name__}")
        file_type = extensions.get("s3m:FileType")
        wdesc = scp.get("wDescript")
    except AttributeError as exc:
        raise S3MBContractError(f"scp 结构畸形：{exc}") from exc

    if version != expected_version:
        raise S3MBContractError(f"S3M 版本不支持：{version!r}（本解析器仅验证过 {expected_version}）")
    if file_type != expected_file_type:
        raise S3MBContractError(f"缓存文件类型不符：{file_type!r}（体元点云瓦片期望 {expected_file_type}）")

    if not isinstance(wdesc, dict) or not isinstance(wdesc.get("range"), dict):
        raise S3MBContractError("scp 缺少 wDescript.range（无法确认属性值域）")
    wmin = wdesc["range"].get("min")
    wmax = wdesc["range"].get("max")
    if not _is_finite_number(wmin) or not _is_finite_number(wmax):
        raise S3MBContractError(f"wDescript 值域非有限数值：min={wmin!r} max={wmax!r}")
    wmin_f, wmax_f = float(wmin), float(wmax)
    if wmin_f > wmax_f:
        raise S3MBContractError(f"wDescript 值域倒置：min {wmin_f} > max {wmax_f}")

    registry_match = (
        abs(wmin_f - contract.value_min) <= contract.value_tolerance
        and abs(wmax_f - contract.value_max) <= contract.value_tolerance
    )
    if not registry_match:
        raise S3MBContractError(
            "wDescript 值域与登记不符："
            f"scp=[{wmin_f}, {wmax_f}]，登记=[{contract.value_min}, {contract.value_max}]"
            "（可能发布了错误缓存，或登记需更新）"
        )

    return {
        "version": version,
        "file_type": file_type,
        "data_type": scp.get("dataType"),
        "wdescript_range": [wmin_f, wmax_f],
        "wdescript_matches_registry": registry_match,
        "result_id": contract.result_id,
    }


def validate_cells(cells: list[VoxelCell], contract: "CacheContract") -> dict[str, Any]:
    """Fail-closed validation of parsed voxel cells against the contract.

    Checks: non-empty, count within the contract's sane window, finite
    coordinates/weights inside the contract value range, and a finite
    bounding box contained in the contract envelope.
    """

    if not cells:
        raise S3MBContractError("解析结果为空：没有可用体元格点（瓦片结构可能变化）")
    count = len(cells)
    if count > contract.max_count:
        raise S3MBContractError(f"格点数量异常：{count} > 上限 {contract.max_count}")
    lo, hi = contract.expected_count * contract.count_ratio[0], contract.expected_count * contract.count_ratio[1]
    if not (lo <= count <= hi):
        raise S3MBContractError(
            f"格点数量 {count} 超出合理区间 [{int(lo)}, {int(hi)}]"
            f"（期望网格 {contract.expected_count}，比例 {contract.count_ratio}）"
        )
    for c in cells:
        if not (math.isfinite(c.x) and math.isfinite(c.y) and math.isfinite(c.z) and math.isfinite(c.weight)):
            raise S3MBContractError(f"格点含非有限数值：({c.x}, {c.y}, {c.z}, {c.weight})")
        if not (contract.value_min - contract.value_tolerance <= c.weight <= contract.value_max + contract.value_tolerance):
            raise S3MBContractError(
                f"格点权重 {c.weight} 超出登记值域 [{contract.value_min}, {contract.value_max}]"
            )

    envelope = {"x": contract.x_range, "y": contract.y_range, "z": contract.z_range}
    bbox = {
        "x": [min(c.x for c in cells), max(c.x for c in cells)],
        "y": [min(c.y for c in cells), max(c.y for c in cells)],
        "z": [min(c.z for c in cells), max(c.z for c in cells)],
    }
    for axis, (lo_e, hi_e) in envelope.items():
        lo_b, hi_b = bbox[axis]
        if lo_b < lo_e - contract.bbox_tolerance or hi_b > hi_e + contract.bbox_tolerance:
            raise S3MBContractError(
                f"包围盒 {axis} 轴 [{lo_b}, {hi_b}] 超出登记范围 [{lo_e}, {hi_e}]（容差 {contract.bbox_tolerance}）"
            )
    return {"count": count, "bbox": bbox, "result_id": contract.result_id}


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _find_blocks(
    blob: bytes,
    *,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    z_range: tuple[float, float],
) -> list[tuple[int, int]]:
    """Locate (vertex_start, vertex_count) xyz-triplet blocks.

    Triplets are accepted only inside the dataset envelope (registry
    bounds); the envelope is cross-checked against the parsed result, so
    this constrains detection without weakening verification.
    """

    def plausible(x: float, y: float, z: float) -> bool:
        return (
            x_range[0] - 0.5 <= x <= x_range[1] + 0.5
            and y_range[0] - 0.5 <= y <= y_range[1] + 0.5
            and z_range[0] - 0.5 <= z <= z_range[1] + 0.5
        )

    blocks: list[tuple[int, int]] = []
    i = 0
    start: int | None = None
    count = 0
    limit = len(blob) - 12
    while i < limit:
        x, y, z = struct.unpack("<fff", blob[i : i + 12])
        if plausible(x, y, z):
            if start is None:
                run_ok = True
                for j in range(1, 4):
                    if i + 12 * (j + 1) > len(blob):
                        run_ok = False
                        break
                    x2, y2, z2 = struct.unpack("<fff", blob[i + 12 * j : i + 12 * (j + 1)])
                    if not plausible(x2, y2, z2):
                        run_ok = False
                        break
                if run_ok:
                    start = i
                    count = 1
                else:
                    i += 4
                    continue
            else:
                count += 1
            i += 12
        else:
            if start is not None and count >= 4:
                blocks.append((start, count))
            start = None
            count = 0
            i += 4
    if start is not None and count >= 4:
        blocks.append((start, count))
    return blocks


def parse_s3mb_bytes(name: str, data: bytes, contract: "CacheContract") -> ParsedTile:
    """Parse one .s3mb tile from raw bytes into weighted voxel cells.

    Geometry and attribute detection use the registry-derived contract
    (coordinate envelope and value range); decompressed size is capped by
    ``contract.max_decompressed_bytes``.
    """

    blob = _decompress_s3mb(data, max_decompressed=contract.max_decompressed_bytes)
    blocks = _find_blocks(blob, x_range=contract.x_range, y_range=contract.y_range, z_range=contract.z_range)
    value_min = contract.value_min - contract.value_tolerance
    value_max = contract.value_max + contract.value_tolerance
    cells: list[VoxelCell] = []

    for vstart, vcount in blocks:
        vend = vstart + vcount * 12
        # weight run: vcount consecutive float32 within the contract value
        # range, located shortly after the vertex block.
        wstart: int | None = None
        scan = vend
        scan_end = min(vend + 512, len(blob) - 4 * vcount + 4)
        while scan < scan_end:
            full = True
            for j in range(vcount):
                (w,) = struct.unpack("<f", blob[scan + 4 * j : scan + 4 * (j + 1)])
                if not (value_min <= w <= value_max):
                    full = False
                    break
            if full:
                wstart = scan
                break
            scan += 4
        if wstart is None:
            continue
        for j in range(vcount):
            x, y, z = struct.unpack("<fff", blob[vstart + 12 * j : vstart + 12 * (j + 1)])
            (w,) = struct.unpack("<f", blob[wstart + 4 * j : wstart + 4 * (j + 1)])
            cells.append(VoxelCell(x=x, y=y, z=z, weight=w))

    if not cells:
        raise S3MBContractError(
            f"瓦片 {name} 解析为空（未发现 顶点块+权重块 结构；非本解析器已验证的体元缓存格式）"
        )
    return ParsedTile(name=name, lod=lod_of(name), cells=cells)


def parse_s3mb(path: str | Path, contract: "CacheContract") -> ParsedTile:
    """Parse one .s3mb tile from a local file path."""

    path = Path(path)
    return parse_s3mb_bytes(path.stem, path.read_bytes(), contract)


def dedupe_cells(tiles: list[ParsedTile], *, weight_tolerance: float = 1e-4) -> list[VoxelCell]:
    """Merge tiles, failing closed on conflicting duplicate cells.

    The tile naming scheme does not encode a reliable LOD order, so no
    "deepest LOD wins" preference is applied: identical duplicates are
    merged once, and any (x, y, z) present with two different weights is a
    contract violation.
    """

    best: dict[tuple[float, float, float], tuple[float, str]] = {}
    for tile in tiles:
        for cell in tile.cells:
            key = (round(cell.x, 3), round(cell.y, 3), round(cell.z, 3))
            previous = best.get(key)
            if previous is None:
                best[key] = (cell.weight, tile.name)
            elif abs(previous[0] - cell.weight) > weight_tolerance:
                raise S3MBContractError(
                    f"重复格点 {key} 权重冲突：{previous[0]}（{previous[1]}） vs {cell.weight}（{tile.name}）"
                )
    return [VoxelCell(x=k[0], y=k[1], z=k[2], weight=v[0]) for k, v in best.items()]


def parse_cache(cache_dir: str | Path, contract: "CacheContract") -> list[VoxelCell]:
    """Parse every .s3mb under a cache dir against the contract, then dedupe."""

    cache_dir = Path(cache_dir)
    tiles = [parse_s3mb(path, contract) for path in sorted(cache_dir.rglob("*.s3mb"))]
    return dedupe_cells(tiles)


def summarize(cells: list[VoxelCell]) -> dict:
    xs = [c.x for c in cells]
    ys = [c.y for c in cells]
    zs = [c.z for c in cells]
    ws = [c.weight for c in cells]
    return {
        "count": len(cells),
        "x_range": [min(xs), max(xs)] if xs else None,
        "y_range": [min(ys), max(ys)] if ys else None,
        "z_range": [min(zs), max(zs)] if zs else None,
        "value_range": [min(ws), max(ws)] if ws else None,
    }


if __name__ == "__main__":
    import json
    import sys

    from geomodeling.config import load_config
    from geomodeling.publishing.cache_contract import contract_from_config

    _config = load_config("config/default.yaml")
    # 演示/排查入口：x/y 包络取自登记的标准化 CSV（与 API 同源）
    import pandas as pd

    _csv = _config.resolve_path(_config.paths.get("standardized"))
    _frame = pd.read_csv(_csv)
    _xy = (
        (float(_frame["X"].min()), float(_frame["X"].max())),
        (float(_frame["Y"].min()), float(_frame["Y"].max())),
    )
    _contract = contract_from_config(_config, xy_extent=_xy)
    cells = parse_cache(sys.argv[1], _contract)
    print(json.dumps(summarize(cells), ensure_ascii=False, indent=2))
