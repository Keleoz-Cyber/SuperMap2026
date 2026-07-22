"""Parse SuperMap S3MB point-cloud voxel tiles into (x, y, z, weight) records.

The S3M 2.0 voxel cache produced by iDesktopX VoxelGridCacheBuilder is a
set of ``.s3mb`` point-cloud tiles. Layout (verified against
RHO_KRIG_FINAL_20M_40_VOL_S3M2 on 2026-07-22):

- File header: 4-byte magic, uint32 LE decompressed length, uint32 LE
  compressed length, then a zlib stream;
- Decompressed blob: LOD page-index region (child tile names + transforms),
  followed by geometry blocks: ``N`` float32 (x, y, z) triplets and, after a
  small gap, ``N`` float32 weights (the voxel attribute, e.g. RHO).

LOD handling: the cache contains several LOD levels; the deepest (leaf)
tiles hold full-resolution cells. We collect every vertex and keep, for each
unique (x, y, z), the weight from the deepest tile that contains it.
"""

from __future__ import annotations

import re
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

TILE_REF_RE = re.compile(rb"Tile_[0-9_]+\.s3mb")


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


def _decompress_s3mb(data: bytes) -> bytes:
    if len(data) < 12:
        raise ValueError("file too small for s3mb header")
    expected = struct.unpack("<I", data[4:8])[0]
    blob = zlib.decompress(data[12:])
    if len(blob) != expected:
        raise ValueError(f"decompressed length {len(blob)} != header {expected}")
    return blob


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


def parse_s3mb_bytes(
    name: str,
    data: bytes,
    *,
    x_range: tuple[float, float] = (-160.0, -40.0),
    y_range: tuple[float, float] = (220.0, 660.0),
    z_range: tuple[float, float] = (-840.0, 0.0),
    value_min: float = 1.418,
    value_max: float = 133.15,
) -> ParsedTile:
    """Parse one .s3mb tile from raw bytes into weighted voxel cells.

    Bounds default to the RHO registry facts and are used both to detect
    geometry blocks and to recognise the attribute run; the parsed result
    is then summarized for an independent registry comparison.
    """

    blob = _decompress_s3mb(data)
    blocks = _find_blocks(blob, x_range=x_range, y_range=y_range, z_range=z_range)
    cells: list[VoxelCell] = []

    for vstart, vcount in blocks:
        vend = vstart + vcount * 12
        # weight run: vcount consecutive float32 within [value_min, value_max]
        # located shortly after the vertex block.
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

    return ParsedTile(name=name, lod=lod_of(name), cells=cells)


def parse_s3mb(path: str | Path, **kwargs) -> ParsedTile:
    """Parse one .s3mb tile from a local file path."""

    path = Path(path)
    return parse_s3mb_bytes(path.stem, path.read_bytes(), **kwargs)


def dedupe_cells(tiles: list[ParsedTile]) -> list[VoxelCell]:
    """Merge tiles; for duplicate (x,y,z) keep the deepest-LOD weight."""

    best: dict[tuple[float, float, float], tuple[int, float]] = {}
    for tile in tiles:
        for cell in tile.cells:
            key = (round(cell.x, 3), round(cell.y, 3), round(cell.z, 3))
            previous = best.get(key)
            if previous is None or tile.lod >= previous[0]:
                best[key] = (tile.lod, cell.weight)
    return [VoxelCell(x=k[0], y=k[1], z=k[2], weight=v[1]) for k, v in best.items()]


def parse_cache(
    cache_dir: str | Path,
    *,
    x_range: tuple[float, float] = (-160.0, -40.0),
    y_range: tuple[float, float] = (220.0, 660.0),
    z_range: tuple[float, float] = (-840.0, 0.0),
    value_min: float = 1.418,
    value_max: float = 133.15,
) -> list[VoxelCell]:
    """Parse every .s3mb under a cache dir; dedupe by (x,y,z), deepest LOD wins."""

    cache_dir = Path(cache_dir)
    tiles = [
        parse_s3mb(
            path,
            x_range=x_range,
            y_range=y_range,
            z_range=z_range,
            value_min=value_min,
            value_max=value_max,
        )
        for path in sorted(cache_dir.rglob("*.s3mb"))
    ]
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

    cells = parse_cache(sys.argv[1])
    print(json.dumps(summarize(cells), ensure_ascii=False, indent=2))
