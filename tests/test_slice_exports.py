"""v0.7.0 Batch 2 Task 5：权威剖面分析 ZIP 导出（原子封包 + 清理合同）。"""

from __future__ import annotations

import hashlib
import io
import json
import struct
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from test_public_dto import assert_no_path_leak
from test_rendering_api import (
    make_app,
    prepare_materialized_candidate,
    register_legacy_grid,
)


def _png(width: int = 8, height: int = 8) -> bytes:
    """最小合法 PNG（真实 IHDR；像素内容为纯色，测试只关心结构合同）。"""

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", _crc(body))

    def _crc(data: bytes) -> int:
        import zlib

        return zlib.crc32(data) & 0xFFFFFFFF

    import zlib

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    idat = zlib.compress(raw)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )


def _post_export(client, asset_id: str, axis="z", index=1, image: bytes | None = None, mime="image/png"):
    files = {
        "axis": (None, axis),
        "index": (None, str(index)),
        "image": ("slice.png", image if image is not None else _png(), mime),
    }
    return client.post(f"/api/render-assets/{asset_id}/slice-exports", files=files)


def _create_candidate_asset(client) -> dict:
    candidate_id = prepare_materialized_candidate(client)
    resp = client.post(f"/api/results/{candidate_id}/render-assets/netcdf")
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def test_candidate_slice_export_zip_contract(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        asset = _create_candidate_asset(client)

        resp = _post_export(client, asset["id"])
        assert resp.status_code == 201, resp.text
        export = resp.json()
        assert export["case_id"]
        assert export["candidate_result_id"] == asset["source_id"]

        download = client.get(f"/api/exports/{export['id']}/download")
        assert download.status_code == 200
        assert "slice-analysis.zip" in download.headers.get("content-disposition", "")
        archive = zipfile.ZipFile(io.BytesIO(download.content))
        assert set(archive.namelist()) == {
            "slice.csv",
            "statistics.json",
            "slice.png",
            "manifest.json",
        }

        csv_text = archive.read("slice.csv").decode("utf-8")
        lines = csv_text.splitlines()
        assert lines[0] == "x,y,z,value,is_nodata"
        assert len(lines) > 1

        stats = json.loads(archive.read("statistics.json"))
        api = client.get(
            f"/api/render-assets/{asset['id']}/slice-analysis?axis=z&index=1"
        ).json()
        assert stats == api["statistics"]

        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["format_version"] == "slice-analysis/v1"
        assert manifest["image_provenance"] == "client_echarts_canvas"
        assert manifest["export_kind"] == "slice_analysis"
        assert manifest["asset_identity"]["asset_id"] == asset["id"]
        assert manifest["asset_identity"]["grid_sha256"] == asset["grid_sha256"]
        assert manifest["asset_identity"]["netcdf_sha256"] == asset["netcdf_sha256"]
        assert manifest["slice"]["fixed_axis"] == "z"
        assert manifest["slice"]["index"] == 1
        assert manifest["slice"]["coordinate"] == api["slice"]["coordinate"]
        assert manifest["files"]["slice.csv"]["sha256"] == hashlib.sha256(
            archive.read("slice.csv")
        ).hexdigest()
        assert manifest["files"]["statistics.json"]["sha256"] == hashlib.sha256(
            archive.read("statistics.json")
        ).hexdigest()
        assert manifest["files"]["slice.png"]["sha256"] == hashlib.sha256(
            archive.read("slice.png")
        ).hexdigest()
        assert manifest["statistics_contract"]["std"] == "population(ddof=0)"
        assert manifest["statistics_contract"]["quantiles"] == "numpy-linear"
        assert_no_path_leak(manifest, "$.slice_export_manifest")


def test_slice_export_csv_row_major_and_nodata_blank(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        asset = _create_candidate_asset(client)
        resp = _post_export(client, asset["id"], axis="x", index=0)
        assert resp.status_code == 201
        download = client.get(f"/api/exports/{resp.json()['id']}/download")
        archive = zipfile.ZipFile(io.BytesIO(download.content))
        api = client.get(
            f"/api/render-assets/{asset['id']}/slice-analysis?axis=x&index=0"
        ).json()
        lines = archive.read("slice.csv").decode("utf-8").splitlines()
        # 列必须按真实轴名标注（设计 §6.2：x,y,z 列序 + 固定轴坐标每行重复）：
        # 行优先遍历不变，但每个坐标值必须落在自己轴的列里
        fixed_axis = api["slice"]["fixed_axis"]
        row_axis = api["slice"]["row_axis"]
        col_axis = api["slice"]["column_axis"]
        fixed_coord = api["slice"]["coordinate"]
        row_coords = api["slice"]["row_coordinates"]
        col_coords = api["slice"]["column_coordinates"]
        values = api["slice"]["values"]
        mask = api["slice"]["nodata_mask"]
        expected = ["x,y,z,value,is_nodata"]
        for r, rc in enumerate(row_coords):
            for c, cc in enumerate(col_coords):
                coords = {fixed_axis: fixed_coord, row_axis: rc, col_axis: cc}
                xyz = f"{coords['x']},{coords['y']},{coords['z']}"
                if mask[r][c]:
                    expected.append(f"{xyz},,true")
                else:
                    expected.append(f"{xyz},{values[r][c]},false")
        assert lines == expected


def test_slice_export_csv_true_axis_columns_for_y_slice(tmp_path, monkeypatch):
    """y 轴剖面同样按真实轴名落列：x=列坐标、y=固定坐标、z=行坐标。"""

    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        asset = _create_candidate_asset(client)
        resp = _post_export(client, asset["id"], axis="y", index=0)
        assert resp.status_code == 201, resp.text
        download = client.get(f"/api/exports/{resp.json()['id']}/download")
        archive = zipfile.ZipFile(io.BytesIO(download.content))
        api = client.get(
            f"/api/render-assets/{asset['id']}/slice-analysis?axis=y&index=0"
        ).json()
        assert api["slice"]["row_axis"] == "z"
        assert api["slice"]["column_axis"] == "x"
        lines = archive.read("slice.csv").decode("utf-8").splitlines()
        assert lines[0] == "x,y,z,value,is_nodata"
        # 首行数据：r=0/c=0 → x=col[0]、y=固定坐标、z=row[0]
        first = lines[1].split(",")
        assert first[0] == str(api["slice"]["column_coordinates"][0])
        assert first[1] == str(api["slice"]["coordinate"])
        assert first[2] == str(api["slice"]["row_coordinates"][0])


def test_legacy_slice_export_has_no_candidate(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        register_legacy_grid(runtime)
        asset = client.post("/api/cases/resistivity/render-assets/netcdf").json()

        resp = _post_export(client, asset["id"], axis="z", index=0)
        assert resp.status_code == 201, resp.text
        export = resp.json()
        assert export["case_id"] == "resistivity"
        assert export["candidate_result_id"] is None
        download = client.get(f"/api/exports/{export['id']}/download")
        manifest = json.loads(
            zipfile.ZipFile(io.BytesIO(download.content)).read("manifest.json")
        )
        assert manifest["asset_identity"]["source_kind"] == "builtin_legacy"
        assert manifest["asset_identity"]["source_id"] == "resistivity"


def test_result_package_download_name_unchanged(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        candidate_id = prepare_materialized_candidate(client)
        export = client.post(f"/api/results/{candidate_id}/exports").json()
        download = client.get(f"/api/exports/{export['id']}/download")
        assert download.status_code == 200
        assert "result-package.zip" in download.headers.get("content-disposition", "")


def test_slice_export_rejects_invalid_image(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        asset = _create_candidate_asset(client)

        resp = _post_export(client, asset["id"], image=b"not-a-png")
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "SLICE_EXPORT_IMAGE_INVALID"

        resp = _post_export(client, asset["id"], image=_png(), mime="image/jpeg")
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "SLICE_EXPORT_IMAGE_INVALID"

        big = _png(1, 1) + b"\x00" * (5 * 1024 * 1024 + 1)
        resp = _post_export(client, asset["id"], image=big)
        assert resp.status_code in (413, 422)

        resp = _post_export(client, asset["id"], image=_png(5000, 8))
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "SLICE_EXPORT_IMAGE_INVALID"


def test_slice_export_non_ready_asset_409(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        resp = _post_export(client, "no-such-asset")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "RENDER_ASSET_NOT_FOUND"


def test_slice_export_db_failure_cleans_everything(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        asset = _create_candidate_asset(client)

        from geomodeling.platform import tables

        def boom(self, **kwargs):
            raise RuntimeError("injected export insert failure")

        monkeypatch.setattr(tables.Export, "__init__", boom)
        with pytest.raises(RuntimeError):
            _post_export(client, asset["id"])
        with runtime.session() as session:
            assert session.query(tables.Export).count() == 0
        staging = list(runtime.settings.exports_dir.rglob("*slice-export*"))
        assert staging == []
        final = runtime.settings.exports_dir
        assert not any(final.glob("*/slice-analysis.zip"))
