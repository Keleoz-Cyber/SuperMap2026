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
    VoxelCell,
    dedupe_cells,
    parse_s3mb_bytes,
    summarize,
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
    blob = bytearray(b"\x00" * 32)
    for x, y, z, _w in CELLS:
        blob += struct.pack("<fff", x, y, z)
    blob += b"\x00" * 64
    packed = zlib.compress(bytes(blob))
    data = b"\x00\x00\x00@" + struct.pack("<I", len(blob)) + struct.pack("<I", len(packed)) + packed
    tile = parse_s3mb_bytes("Tile_1_0", data)
    assert tile.cells == []


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
    assert body["registry_facts"]["rows_columns_bands"] == [7, 23, 42]
    assert body["registry_facts"]["cell_exact_value_range"] == [1.418283, 133.146194]
