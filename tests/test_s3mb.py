"""Portable tests for the S3MB voxel-tile parser and the voxel-cells API."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from geomodeling.api.app import create_app
from geomodeling.api.deps import ApiSettings, get_app_config, get_iserver_client, get_settings
from geomodeling.api import case_service
from geomodeling.publishing.s3mb import (
    S3MBContractError,
    VoxelCell,
    dedupe_cells,
    parse_s3mb_bytes,
    summarize,
    validate_cache_scp,
    validate_cells,
)
from geomodeling.publishing.s3mb import ParsedTile

from test_api import FakeIServer, make_config


def build_s3mb(cells: list[tuple[float, float, float, float]], *, junk: bytes = b"") -> bytes:
    """Build a synthetic .s3mb: page-index junk, vertex triplets, weight run."""

    blob = bytearray(junk)
    for x, y, z, _w in cells:
        blob += struct.pack("<fff", x, y, z)
    blob += b"\x00" * 24  # gap between geometry and attribute runs
    for _x, _y, _z, w in cells:
        blob += struct.pack("<f", w)
    packed = zlib.compress(bytes(blob))
    return b"\x00\x00\x00@" + struct.pack("<I", len(blob)) + struct.pack("<I", len(packed)) + packed


CELLS = [
    (-160.0, 239.13, -840.0, 3.5),
    (-160.0, 239.13, -820.0, 7.25),
    (-142.857, 258.26, -840.0, 12.0),
    (-142.857, 258.26, -820.0, 42.42),
    (-108.571, 440.0, -400.0, 133.0),
]


def test_parse_s3mb_bytes_reads_vertices_and_weights():
    tile = parse_s3mb_bytes("Tile_2_0", build_s3mb(CELLS, junk=b"\x00" * 96))
    assert tile.lod == 2
    assert len(tile.cells) == len(CELLS)
    first = tile.cells[0]
    assert first.x == pytest.approx(-160.0)
    assert first.y == pytest.approx(239.13, abs=1e-3)
    assert first.z == pytest.approx(-840.0)
    assert first.weight == pytest.approx(3.5)
    summary = summarize(tile.cells)
    assert summary["count"] == 5
    assert summary["value_range"] == [pytest.approx(3.5), pytest.approx(133.0)]


def test_parse_s3mb_bytes_ignores_blocks_without_weight_run():
    # vertex triplets but the following floats are all zero → no weight run
    # → fail-closed contract error instead of silent empty result
    blob = bytearray(b"\x00" * 32)
    for x, y, z, _w in CELLS:
        blob += struct.pack("<fff", x, y, z)
    blob += b"\x00" * 64
    packed = zlib.compress(bytes(blob))
    data = b"\x00\x00\x00@" + struct.pack("<I", len(blob)) + struct.pack("<I", len(packed)) + packed
    with pytest.raises(S3MBContractError, match="解析为空"):
        parse_s3mb_bytes("Tile_1_0", data)


def test_parse_s3mb_bytes_rejects_bad_magic():
    data = b"BAD!" + struct.pack("<I", 10) + struct.pack("<I", 5) + zlib.compress(b"\x00" * 10)
    with pytest.raises(S3MBContractError, match="魔数不符"):
        parse_s3mb_bytes("Tile_1_0", data)


def test_parse_s3mb_bytes_rejects_truncated_file():
    with pytest.raises(S3MBContractError, match="文件过小"):
        parse_s3mb_bytes("Tile_1_0", b"\x00" * 8)


def test_parse_s3mb_bytes_rejects_corrupt_zlib():
    data = b"\x00\x00\x00@" + struct.pack("<I", 10) + struct.pack("<I", 5) + b"not-zlib-at-all"
    with pytest.raises(S3MBContractError, match="解压失败"):
        parse_s3mb_bytes("Tile_1_0", data)


def test_parse_s3mb_bytes_rejects_length_mismatch():
    packed = zlib.compress(b"\x00" * 10)
    data = b"\x00\x00\x00@" + struct.pack("<I", 999) + struct.pack("<I", len(packed)) + packed
    with pytest.raises(S3MBContractError, match="长度 .* 与头部声明"):
        parse_s3mb_bytes("Tile_1_0", data)


VALID_SCP = {
    "version": "2.0",
    "dataType": "BIM",
    "extensions": {"s3m:FileType": "PointCloudFile", "vol": []},
    "wDescript": {"category": "Attribute", "range": {"min": 1.4182828664779663, "max": 133.1461944580078}},
}


def test_validate_cache_scp_accepts_targeted_cache():
    info = validate_cache_scp(VALID_SCP)
    assert info["version"] == "2.0"
    assert info["file_type"] == "PointCloudFile"
    assert info["wdescript_range"][0] == pytest.approx(1.418283, abs=1e-4)
    assert info["wdescript_matches_registry"] is True


def test_validate_cache_scp_rejects_wrong_version():
    bad = dict(VALID_SCP, version="1.0")
    with pytest.raises(S3MBContractError, match="版本不支持"):
        validate_cache_scp(bad)


def test_validate_cache_scp_rejects_wrong_file_type():
    bad = dict(VALID_SCP, extensions={"s3m:FileType": "OsgbFile"})
    with pytest.raises(S3MBContractError, match="文件类型不符"):
        validate_cache_scp(bad)


def test_validate_cache_scp_rejects_missing_wdescript():
    bad = {k: v for k, v in VALID_SCP.items() if k != "wDescript"}
    with pytest.raises(S3MBContractError, match="wDescript"):
        validate_cache_scp(bad)


def test_validate_cache_scp_rejects_non_finite_wdescript():
    bad = dict(VALID_SCP, wDescript={"category": "Attribute", "range": {"min": float("nan"), "max": 10.0}})
    with pytest.raises(S3MBContractError, match="非有限数值"):
        validate_cache_scp(bad)


def test_validate_cache_scp_rejects_inverted_range():
    bad = dict(VALID_SCP, wDescript={"category": "Attribute", "range": {"min": 133.0, "max": 1.4}})
    with pytest.raises(S3MBContractError, match="倒置"):
        validate_cache_scp(bad)


def test_validate_cache_scp_rejects_registry_mismatch_with_both_ranges():
    bad = dict(VALID_SCP, wDescript={"category": "Attribute", "range": {"min": 0.5, "max": 99.0}})
    with pytest.raises(S3MBContractError, match=r"scp=\[0.5, 99.0\].*登记=\[1.418283, 133.146194\]"):
        validate_cache_scp(bad)


def test_validate_cells_rejects_empty():
    with pytest.raises(S3MBContractError, match="为空"):
        validate_cells([], envelope={"x": (-160, -40), "y": (220, 660), "z": (-840, 0)})


def test_validate_cells_rejects_count_outside_ratio():
    cells = [VoxelCell(-100.0, 440.0, -100.0, 5.0)] * 10
    with pytest.raises(S3MBContractError, match="合理区间"):
        validate_cells(cells, envelope={"x": (-160, -40), "y": (220, 660), "z": (-840, 0)}, expected_count=6762)


def test_validate_cells_rejects_non_finite():
    cells = [VoxelCell(-100.0, 440.0, -100.0, float("nan"))] * 7000
    with pytest.raises(S3MBContractError, match="非有限数值"):
        validate_cells(cells, envelope={"x": (-160, -40), "y": (220, 660), "z": (-840, 0)})


def test_validate_cells_rejects_bbox_outside_envelope():
    cells = [VoxelCell(-100.0, 440.0, -100.0, 5.0)] * 6999 + [VoxelCell(999.0, 440.0, -100.0, 5.0)]
    with pytest.raises(S3MBContractError, match="超出登记范围"):
        validate_cells(cells, envelope={"x": (-160, -40), "y": (220, 660), "z": (-840, 0)})


def test_validate_cells_accepts_reasonable_data():
    cells = [VoxelCell(-100.0 + (i % 7), 240.0 + (i % 21) * 20.0, -840.0 + (i % 48) * 17.0, 5.0) for i in range(7000)]
    info = validate_cells(cells, envelope={"x": (-160, -40), "y": (220, 660), "z": (-840, 0)})
    assert info["count"] == 7000
    assert info["bbox"]["x"][0] >= -160.0


def test_dedupe_cells_prefers_deepest_lod():
    low = ParsedTile(name="Tile_1_0", lod=1, cells=[VoxelCell(-160.0, 239.13, -840.0, 50.0)])
    high = ParsedTile(name="Tile_4_0_0", lod=4, cells=[VoxelCell(-160.0, 239.13, -840.0, 5.5)])
    cells = dedupe_cells([low, high])
    assert len(cells) == 1
    assert cells[0].weight == pytest.approx(5.5)


def _settings(tmp_path: Path) -> ApiSettings:
    return ApiSettings(
        config_path=Path("config/default.yaml"),
        metrics_json=None,
        evidence_dir=tmp_path / "evidence",
        frontend_dist=None,
        voxel_cache_dir=tmp_path / "cache",
    )


def test_voxel_cells_endpoint_503_when_cache_missing(tmp_path, monkeypatch):
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: _settings(tmp_path)
    app.dependency_overrides[get_app_config] = make_config
    app.dependency_overrides[get_iserver_client] = lambda: FakeIServer({})
    client = TestClient(app)
    resp = client.get("/api/cases/resistivity/voxel-cells")
    assert resp.status_code == 503
    assert "voxel cache" in resp.json()["detail"]


def test_voxel_cells_endpoint_parses_iserver_tiles(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache" / "Tile_1_0"
    cache_dir.mkdir(parents=True)
    tile_bytes = build_s3mb(CELLS, junk=b"\x00" * 96)
    (cache_dir / "Tile_1_0.s3mb").write_bytes(tile_bytes)

    def fake_cached(cache_dir_arg: str, service_url: str, timeout: float):
        return {
            "cells": case_service.dedupe_cells(
                [case_service.parse_s3mb_bytes("Tile_1_0", tile_bytes)]
            ),
            "tile_files": 1,
            "fetched_bytes": len(tile_bytes),
            "service_url": service_url,
            "summary": {
                "x_range": [-160.0, -108.571],
                "y_range": [239.13, 440.0],
                "z_range": [-840.0, -400.0],
                "value_range": [3.5, 133.0],
            },
            "contract": {
                "scp": {
                    "version": "2.0",
                    "file_type": "PointCloudFile",
                    "data_type": "BIM",
                    "wdescript_range": [1.4182828664779663, 133.1461944580078],
                    "wdescript_matches_registry": True,
                },
                "cells": {"count": 5, "bbox": {"x": [-160.0, -108.571], "y": [239.13, 440.0], "z": [-840.0, -400.0]}},
            },
        }

    monkeypatch.setattr(case_service, "_voxel_cells_cached", fake_cached)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: _settings(tmp_path)
    app.dependency_overrides[get_app_config] = make_config
    app.dependency_overrides[get_iserver_client] = lambda: FakeIServer({})
    client = TestClient(app)
    resp = client.get("/api/cases/resistivity/voxel-cells")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "iserver_s3m_cache"
    assert body["count"] == 5
    assert body["tile_files"] == 1
    assert body["value_range"] == [3.5, 133.0]
    assert body["contract"]["scp"]["wdescript_matches_registry"] is True
    assert "不宣称通用 S3MB 解析" in body["parser_scope"]
    assert body["registry_facts"]["rows_columns_bands"] == [7, 23, 42]
    assert body["registry_facts"]["cell_exact_value_range"] == [1.418283, 133.146194]


def test_voxel_cells_endpoint_contract_failure_is_explicit(tmp_path, monkeypatch):
    def raising_cached(cache_dir_arg: str, service_url: str, timeout: float):
        raise S3MBContractError("S3M 版本不支持：'1.0'（本解析器仅验证过 2.0）")

    monkeypatch.setattr(case_service, "_voxel_cells_cached", raising_cached)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: _settings(tmp_path)
    app.dependency_overrides[get_app_config] = make_config
    app.dependency_overrides[get_iserver_client] = lambda: FakeIServer({})
    client = TestClient(app)
    resp = client.get("/api/cases/resistivity/voxel-cells")
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert "契约校验失败" in detail
    assert "版本不支持" in detail
