"""Portable tests for the S3MB voxel-tile parser, contract, and manifest."""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from geomodeling.api.app import create_app
from geomodeling.api.deps import ApiSettings, get_app_config, get_iserver_client, get_settings
from geomodeling.api import case_service
from geomodeling.publishing.cache_contract import CacheContract, contract_from_config
from geomodeling.publishing.cache_manifest import (
    CacheManifest,
    compute_manifest_digest,
    verify_manifest_digest,
    verify_tile_set,
)
from geomodeling.publishing.s3mb import (
    S3MBContractError,
    ParsedTile,
    VoxelCell,
    dedupe_cells,
    parse_s3mb_bytes,
    summarize,
    validate_cache_scp,
    validate_cells,
)

from test_api import FakeIServer, make_config

CONTRACT = CacheContract.build(
    result_id="RHO_KRIG_FINAL_20M_40",
    value_min=1.418283,
    value_max=133.146194,
    rows=7,
    columns=23,
    bands=42,
    x_range=(-160.0, -40.0),
    y_range=(220.0, 660.0),
    z_range=(-840.0, 0.0),
)


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


# ------------------------------------------------------------------ parsing


def test_parse_s3mb_bytes_reads_vertices_and_weights():
    tile = parse_s3mb_bytes("Tile_2_0", build_s3mb(CELLS, junk=b"\x00" * 96), CONTRACT)
    assert tile.lod == 2
    assert len(tile.cells) == len(CELLS)
    first = tile.cells[0]
    assert first.x == pytest.approx(-160.0)
    assert first.y == pytest.approx(239.13, abs=1e-3)
    assert first.z == pytest.approx(-840.0)
    summary = summarize(tile.cells)
    assert summary["count"] == 5
    assert summary["value_range"] == [pytest.approx(3.5), pytest.approx(133.0)]


def test_parse_s3mb_bytes_rejects_missing_weight_run():
    blob = bytearray(b"\x00" * 32)
    for x, y, z, _w in CELLS:
        blob += struct.pack("<fff", x, y, z)
    blob += b"\x00" * 64
    packed = zlib.compress(bytes(blob))
    data = b"\x00\x00\x00@" + struct.pack("<I", len(blob)) + struct.pack("<I", len(packed)) + packed
    with pytest.raises(S3MBContractError, match="解析为空"):
        parse_s3mb_bytes("Tile_1_0", data, CONTRACT)


def test_parse_s3mb_bytes_rejects_bad_magic():
    data = b"BAD!" + struct.pack("<I", 10) + struct.pack("<I", 5) + zlib.compress(b"\x00" * 10)
    with pytest.raises(S3MBContractError, match="魔数不符"):
        parse_s3mb_bytes("Tile_1_0", data, CONTRACT)


def test_parse_s3mb_bytes_rejects_truncated_file():
    with pytest.raises(S3MBContractError, match="文件过小"):
        parse_s3mb_bytes("Tile_1_0", b"\x00" * 8, CONTRACT)


def test_parse_s3mb_bytes_rejects_corrupt_zlib():
    data = b"\x00\x00\x00@" + struct.pack("<I", 10) + struct.pack("<I", 15) + b"not-zlib-at-all"
    with pytest.raises(S3MBContractError, match="解压失败"):
        parse_s3mb_bytes("Tile_1_0", data, CONTRACT)


def test_parse_s3mb_bytes_rejects_compressed_length_mismatch():
    packed = zlib.compress(b"\x00" * 10)
    data = b"\x00\x00\x00@" + struct.pack("<I", 10) + struct.pack("<I", len(packed) + 1) + packed
    with pytest.raises(S3MBContractError, match="compressed_length 不符"):
        parse_s3mb_bytes("Tile_1_0", data, CONTRACT)


def test_parse_s3mb_bytes_rejects_trailing_bytes():
    packed = zlib.compress(b"\x00" * 10)
    data = b"\x00\x00\x00@" + struct.pack("<I", 10) + struct.pack("<I", len(packed)) + packed + b"XX"
    with pytest.raises(S3MBContractError, match="compressed_length 不符"):
        parse_s3mb_bytes("Tile_1_0", data, CONTRACT)


def test_parse_s3mb_bytes_rejects_length_mismatch():
    packed = zlib.compress(b"\x00" * 10)
    data = b"\x00\x00\x00@" + struct.pack("<I", 999) + struct.pack("<I", len(packed)) + packed
    with pytest.raises(S3MBContractError, match="长度 .* 与头部声明"):
        parse_s3mb_bytes("Tile_1_0", data, CONTRACT)


def test_parse_s3mb_bytes_rejects_oversize_decompressed():
    import dataclasses

    packed = zlib.compress(b"\x00" * 1024)
    tiny = dataclasses.replace(CONTRACT, max_decompressed_bytes=512)
    data = b"\x00\x00\x00@" + struct.pack("<I", 1024) + struct.pack("<I", len(packed)) + packed
    with pytest.raises(S3MBContractError, match="超过上限"):
        parse_s3mb_bytes("Tile_1_0", data, tiny)


def test_dedupe_cells_merges_identical_duplicates():
    a = ParsedTile(name="Tile_1_0", lod=1, cells=[VoxelCell(-160.0, 239.13, -840.0, 5.0)])
    b = ParsedTile(name="Tile_4_0_0", lod=4, cells=[VoxelCell(-160.0, 239.13, -840.0, 5.0)])
    cells = dedupe_cells([a, b])
    assert len(cells) == 1


def test_dedupe_cells_fails_closed_on_conflict():
    a = ParsedTile(name="Tile_1_0", lod=1, cells=[VoxelCell(-160.0, 239.13, -840.0, 50.0)])
    b = ParsedTile(name="Tile_4_0_0", lod=4, cells=[VoxelCell(-160.0, 239.13, -840.0, 5.5)])
    with pytest.raises(S3MBContractError, match="权重冲突"):
        dedupe_cells([a, b])


# ------------------------------------------------------------------ scp


VALID_SCP = {
    "version": "2.0",
    "dataType": "BIM",
    "extensions": {"s3m:FileType": "PointCloudFile", "vol": []},
    "wDescript": {"category": "Attribute", "range": {"min": 1.4182828664779663, "max": 133.1461944580078}},
}


def test_validate_cache_scp_accepts_targeted_cache():
    info = validate_cache_scp(VALID_SCP, CONTRACT)
    assert info["version"] == "2.0"
    assert info["file_type"] == "PointCloudFile"
    assert info["wdescript_matches_registry"] is True
    assert info["result_id"] == "RHO_KRIG_FINAL_20M_40"


def test_validate_cache_scp_rejects_non_dict():
    with pytest.raises(S3MBContractError, match="不是 JSON 对象"):
        validate_cache_scp(["not", "a", "dict"], CONTRACT)


def test_validate_cache_scp_rejects_wrong_version():
    with pytest.raises(S3MBContractError, match="版本不支持"):
        validate_cache_scp(dict(VALID_SCP, version="1.0"), CONTRACT)


def test_validate_cache_scp_rejects_wrong_file_type():
    bad = dict(VALID_SCP, extensions={"s3m:FileType": "OsgbFile"})
    with pytest.raises(S3MBContractError, match="文件类型不符"):
        validate_cache_scp(bad, CONTRACT)


def test_validate_cache_scp_rejects_missing_wdescript():
    bad = {k: v for k, v in VALID_SCP.items() if k != "wDescript"}
    with pytest.raises(S3MBContractError, match="wDescript"):
        validate_cache_scp(bad, CONTRACT)


def test_validate_cache_scp_rejects_non_finite_wdescript():
    bad = dict(VALID_SCP, wDescript={"category": "Attribute", "range": {"min": float("nan"), "max": 10.0}})
    with pytest.raises(S3MBContractError, match="非有限数值"):
        validate_cache_scp(bad, CONTRACT)


def test_validate_cache_scp_rejects_inverted_range():
    bad = dict(VALID_SCP, wDescript={"category": "Attribute", "range": {"min": 133.0, "max": 1.4}})
    with pytest.raises(S3MBContractError, match="倒置"):
        validate_cache_scp(bad, CONTRACT)


def test_validate_cache_scp_rejects_registry_mismatch_with_both_ranges():
    bad = dict(VALID_SCP, wDescript={"category": "Attribute", "range": {"min": 0.5, "max": 99.0}})
    with pytest.raises(S3MBContractError, match="登记不符"):
        validate_cache_scp(bad, CONTRACT)


# ------------------------------------------------------------------ cells


def test_validate_cells_rejects_empty():
    with pytest.raises(S3MBContractError, match="为空"):
        validate_cells([], CONTRACT)


def test_validate_cells_rejects_count_outside_ratio():
    cells = [VoxelCell(-100.0, 440.0, -100.0, 5.0)] * 10
    with pytest.raises(S3MBContractError, match="合理区间"):
        validate_cells(cells, CONTRACT)


def test_validate_cells_rejects_non_finite():
    cells = [VoxelCell(-100.0, 440.0, -100.0, float("nan"))] * 7000
    with pytest.raises(S3MBContractError, match="非有限数值"):
        validate_cells(cells, CONTRACT)


def test_validate_cells_rejects_weight_outside_value_range():
    cells = [VoxelCell(-100.0, 440.0, -100.0, 5.0)] * 6999 + [VoxelCell(-100.0, 440.0, -100.0, 999.0)]
    with pytest.raises(S3MBContractError, match="超出登记值域"):
        validate_cells(cells, CONTRACT)


def test_validate_cells_rejects_bbox_outside_envelope():
    cells = [VoxelCell(-100.0, 440.0, -100.0, 5.0)] * 6999 + [VoxelCell(999.0, 440.0, -100.0, 5.0)]
    with pytest.raises(S3MBContractError, match="超出登记范围"):
        validate_cells(cells, CONTRACT)


def test_validate_cells_accepts_reasonable_data():
    cells = [VoxelCell(-100.0 + (i % 7), 240.0 + (i % 21) * 20.0, -840.0 + (i % 48) * 17.0, 5.0) for i in range(7000)]
    info = validate_cells(cells, CONTRACT)
    assert info["count"] == 7000
    assert info["result_id"] == "RHO_KRIG_FINAL_20M_40"


# ------------------------------------------------------------------ contract


def test_contract_from_config_derives_registry_facts():
    config = make_config()
    contract = contract_from_config(config, xy_extent=((-160.0, -40.0), (220.0, 660.0)))
    assert contract.result_id == "RHO_KRIG_FINAL_20M_40"
    assert contract.expected_count == 7 * 23 * 42
    assert (contract.value_min, contract.value_max) == (1.418283, 133.146194)
    assert contract.z_range == (-840.0, 0.0)


# ------------------------------------------------------------------ manifest


def test_manifest_digest_stable_and_verifies():
    tiles = [("Tile_1_0/Tile_1_0.s3mb", build_s3mb(CELLS)), ("Tile_2_0/Tile_2_0.s3mb", build_s3mb(CELLS[:2]))]
    digest = compute_manifest_digest(tiles)
    assert digest == compute_manifest_digest(list(reversed(tiles)))
    manifest = CacheManifest("X", tuple(sorted(rel for rel, _ in tiles)), digest)
    assert verify_manifest_digest(tiles, manifest) == digest


def test_verify_tile_set_rejects_mismatch():
    manifest = CacheManifest("X", ("a.s3mb", "b.s3mb"), "x")
    with pytest.raises(S3MBContractError, match="清单不符"):
        verify_tile_set(["a.s3mb"], manifest)


def test_verify_manifest_digest_reports_computed_digest():
    tiles = [("a.s3mb", b"aaa")]
    manifest = CacheManifest("X", ("a.s3mb",), "0" * 64)
    with pytest.raises(S3MBContractError, match=compute_manifest_digest(tiles)):
        verify_manifest_digest(tiles, manifest)


# ------------------------------------------------------------------ endpoint


def _settings(tmp_path: Path) -> ApiSettings:
    return ApiSettings(
        config_path=Path("config/default.yaml"),
        metrics_json=None,
        evidence_dir=tmp_path / "evidence",
        frontend_dist=None,
        voxel_cache_dir=tmp_path / "cache",
    )


def _client(tmp_path: Path, config=None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: _settings(tmp_path)
    app.dependency_overrides[get_app_config] = lambda: (config or make_config())
    app.dependency_overrides[get_iserver_client] = lambda: FakeIServer({})
    return TestClient(app)


def test_voxel_cells_endpoint_503_when_remote_unavailable(tmp_path, monkeypatch):
    """远程服务不可达（全部取数失败）→ 503 且指明 iServer 取数失败。"""

    class DeadRemote:
        def __init__(self, base_url, timeout=10.0, **_kw):
            self.base_url = base_url

        def get_json(self, path, *, use_token=False):
            return _Resp(False, error="connection refused")

        def get_bytes(self, path):
            return _Resp(False, error="connection refused")

        def close(self):
            return None

    monkeypatch.setattr("geomodeling.publishing.IServerClient", DeadRemote)
    case_service._voxel_cells_cached.cache_clear()
    config = make_config(standardized=Path("tests/fixtures/rho_tiny_validation.csv"))
    resp = _client(tmp_path, config).get("/api/cases/resistivity/voxel-cells")
    assert resp.status_code == 503
    assert "iServer" in resp.json()["error"]["message"]


def test_voxel_cells_endpoint_parses_iserver_tiles(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache" / "Tile_1_0"
    cache_dir.mkdir(parents=True)
    tile_bytes = build_s3mb(CELLS, junk=b"\x00" * 96)
    (cache_dir / "Tile_1_0.s3mb").write_bytes(tile_bytes)

    def fake_cached(service_url, contract, manifest, timeout):
        return {
            "cells": dedupe_cells([parse_s3mb_bytes("Tile_1_0", tile_bytes, CONTRACT)]),
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
                "scp": {"version": "2.0", "file_type": "PointCloudFile", "wdescript_matches_registry": True},
                "cells": {"count": 5, "bbox": {"x": [-160.0, -108.571], "y": [239.13, 440.0], "z": [-840.0, -400.0]}},
                "manifest": {"tile_count": 1, "digest_sha256": "pinned", "pinned": True},
            },
        }

    monkeypatch.setattr(case_service, "_voxel_cells_cached", fake_cached)
    config = make_config(standardized=Path("tests/fixtures/rho_tiny_validation.csv"))
    resp = _client(tmp_path, config).get("/api/cases/resistivity/voxel-cells")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "iserver_s3m_cache"
    assert body["count"] == 5
    assert body["contract"]["scp"]["wdescript_matches_registry"] is True
    assert body["contract"]["manifest"]["pinned"] is True
    assert "不宣称通用 S3MB 解析" in body["parser_scope"]
    assert body["registry_facts"]["rows_columns_bands"] == [7, 23, 42]


def test_voxel_cells_endpoint_contract_failure_is_explicit(tmp_path, monkeypatch):
    def raising_cached(service_url, contract, manifest, timeout):
        raise S3MBContractError("S3M 版本不支持：'1.0'（本解析器仅验证过 2.0）")

    monkeypatch.setattr(case_service, "_voxel_cells_cached", raising_cached)
    config = make_config(standardized=Path("tests/fixtures/rho_tiny_validation.csv"))
    resp = _client(tmp_path, config).get("/api/cases/resistivity/voxel-cells")
    assert resp.status_code == 503
    detail = resp.json()["error"]["message"]
    assert "契约校验失败" in detail
    assert "版本不支持" in detail


# ----------------------------------------------------- manifest-driven fetch


def _envelope_csv(tmp_path: Path) -> Path:
    csv = tmp_path / "standardized_envelope.csv"
    csv.write_text(
        "X,Y,Z,RHO\n-160,220,-10,5\n-40,660,-20,10\n-100,440,-30,15\n",
        encoding="utf-8",
    )
    return csv


def _synthetic_cells_per_tile(seed: int) -> list[tuple[float, float, float, float]]:
    cells = []
    for i in range(12):
        for j in range(12):
            x = -160.0 + seed * 4.0 + i * 0.05
            y = 230.0 + (j % 21) * 20.0
            z = -840.0 + ((i * 12 + j) % 48) * 17.0
            w = 2.0 + ((seed * 31 + i * 13 + j * 7) % 120) + 0.5
            cells.append((x, y, z, w))
    return cells


def _synthetic_manifest(tag: str = "it") -> tuple[CacheManifest, dict[str, bytes]]:
    tiles: dict[str, bytes] = {}
    for idx in range(26):
        rel = f"Tile_{idx // 7 + 1}_0/Tile_{idx}_{tag}.s3mb"
        tiles[rel] = build_s3mb(_synthetic_cells_per_tile(idx))
    manifest = CacheManifest(
        cache_data_name=case_service.VOLUME_CACHE_DATA_NAME,
        tiles=tuple(sorted(tiles)),
        digest_sha256=compute_manifest_digest(list(tiles.items())),
    )
    return manifest, tiles


class _Resp:
    def __init__(self, ok, data=None, error=None, status=200):
        self.ok = ok
        self.data = data
        self.error = error
        self.status_code = status


def _fake_iserver_factory(tiles: dict[str, bytes], scp: dict):
    class FakeRemote:
        def __init__(self, base_url, timeout=10.0, **_kw):
            self.base_url = base_url

        def get_json(self, path, *, use_token=False):
            if path.endswith("/config"):
                return _Resp(True, data=scp)
            return _Resp(False, error=f"unexpected json path {path}")

        def get_bytes(self, path):
            for rel, data in tiles.items():
                if path.endswith(f"/data/path/{rel}"):
                    return _Resp(True, data=data)
            return _Resp(False, error=f"unexpected tile path {path}")

        def close(self):
            return None

    return FakeRemote


def test_voxel_cells_integration_remote_complete_without_local_cache(tmp_path, monkeypatch):
    """没有本地缓存目录：只要远程服务 + manifest 完整，端点必须成功。"""

    manifest, tiles = _synthetic_manifest("int")
    monkeypatch.setattr("geomodeling.publishing.IServerClient", _fake_iserver_factory(tiles, VALID_SCP))
    monkeypatch.setattr(case_service, "load_manifest", lambda _path=None: manifest)
    case_service._voxel_cells_cached.cache_clear()

    config = make_config(standardized=_envelope_csv(tmp_path))
    settings = ApiSettings(
        config_path=Path("config/default.yaml"),
        metrics_json=None,
        evidence_dir=tmp_path / "evidence",
        frontend_dist=None,
        voxel_cache_dir=tmp_path / "does-not-exist",
    )
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_app_config] = lambda: config
    app.dependency_overrides[get_iserver_client] = lambda: FakeIServer({})
    resp = TestClient(app).get("/api/cases/resistivity/voxel-cells")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] > 3000
    assert body["tile_files"] == 26
    assert body["local_cache_present"] is False
    assert body["contract"]["manifest"]["pinned"] is True


def test_voxel_cells_integration_manifest_data_name_mismatch(tmp_path, monkeypatch):
    manifest, tiles = _synthetic_manifest("mm")
    bad = CacheManifest(
        cache_data_name="OTHER_CACHE_NAME",
        tiles=manifest.tiles,
        digest_sha256=manifest.digest_sha256,
    )
    monkeypatch.setattr("geomodeling.publishing.IServerClient", _fake_iserver_factory(tiles, VALID_SCP))
    monkeypatch.setattr(case_service, "load_manifest", lambda _path=None: bad)
    case_service._voxel_cells_cached.cache_clear()

    config = make_config(standardized=_envelope_csv(tmp_path))
    resp = _client(tmp_path, config).get("/api/cases/resistivity/voxel-cells")
    assert resp.status_code == 503
    assert "cache_data_name 不符" in resp.json()["error"]["message"]


def test_voxel_cells_refresh_clears_both_caches(tmp_path, monkeypatch):
    manifest, tiles = _synthetic_manifest("rf")
    calls = {"bytes": 0}

    class CountingRemote(_fake_iserver_factory(tiles, VALID_SCP)):
        def get_bytes(self, path):
            calls["bytes"] += 1
            return super().get_bytes(path)

    monkeypatch.setattr("geomodeling.publishing.IServerClient", CountingRemote)
    monkeypatch.setattr(case_service, "load_manifest", lambda _path=None: manifest)
    case_service._voxel_cells_cached.cache_clear()

    config = make_config(standardized=_envelope_csv(tmp_path))
    client = _client(tmp_path, config)
    assert client.get("/api/cases/resistivity/voxel-cells").status_code == 200
    first = calls["bytes"]
    assert first == 26

    # 第二次不带 refresh：命中缓存，不再取瓦片
    assert client.get("/api/cases/resistivity/voxel-cells").status_code == 200
    assert calls["bytes"] == first

    # refresh=true：重新拉取
    assert client.get("/api/cases/resistivity/voxel-cells?refresh=true").status_code == 200
    assert calls["bytes"] == first * 2
