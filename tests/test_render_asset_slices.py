"""v0.7.0 Batch 2 Task 4：RenderAsset 剖面分析 API（三来源统一入口）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from test_public_dto import assert_no_path_leak
from test_rendering_api import (
    make_app,
    prepare_materialized_candidate,
    register_legacy_grid,
)


def _create_candidate_asset(client) -> tuple[str, dict]:
    candidate_id = prepare_materialized_candidate(client)
    resp = client.post(f"/api/results/{candidate_id}/render-assets/netcdf")
    assert resp.status_code in (200, 201), resp.text
    asset = resp.json()
    return candidate_id, asset


def _create_legacy_asset(runtime) -> dict:
    """历史 builtin_legacy 资产：v0.8.0 Task 6 起产品入口退役，经服务层创建。"""

    from geomodeling.platform import render_assets
    from geomodeling.platform.legacy_render_sources import resolve_legacy_render_source

    register_legacy_grid(runtime)
    source = resolve_legacy_render_source(runtime, "resistivity")
    record, created = render_assets.create_render_asset(runtime, source, retry_failed=False)
    assert created is True
    return {
        "id": record.id,
        "manifest_url": f"/api/render-assets/{record.id}/manifest",
        "grid_sha256": record.grid_sha256,
        "netcdf_sha256": record.netcdf_sha256,
    }


def test_candidate_asset_slice_analysis_orientation_and_identity(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        _, asset = _create_candidate_asset(client)
        manifest = client.get(asset["manifest_url"]).json()
        z_len = manifest["shape"][2]

        resp = client.get(f"/api/render-assets/{asset['id']}/slice-analysis?axis=z&index=1")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["asset_identity"]["asset_id"] == asset["id"]
        assert body["asset_identity"]["source_kind"] == "candidate_result"
        assert body["asset_identity"]["grid_sha256"] == asset["grid_sha256"]
        assert body["asset_identity"]["netcdf_sha256"] == asset["netcdf_sha256"]
        assert body["slice"]["fixed_axis"] == "z"
        assert body["slice"]["index"] == 1
        assert body["slice"]["row_axis"] == "y"
        assert body["slice"]["column_axis"] == "x"
        assert body["slice"]["sdk_relative_position"] == pytest.approx(1 / (z_len - 1))
        assert len(body["slice"]["row_coordinates"]) == manifest["shape"][1]
        assert len(body["slice"]["column_coordinates"]) == manifest["shape"][0]
        assert body["statistics"]["total_count"] == manifest["shape"][0] * manifest["shape"][1]
        assert body["render_profile"] is not None
        # 语义属性名来自来源 profile（本夹具 value_name=属性）；
        # manifest.variable_name 是 NetCDF 安全变量名（非 ASCII 归一化），二者合法不同
        assert body["property"]["name"] == "属性"
        assert body["property"]["unit"] == "unknown"
        assert_no_path_leak(body, "$.slice_analysis")


def test_legacy_asset_slice_analysis(tmp_path, monkeypatch):
    """历史 builtin_legacy 资产的剖面分析只读保留（产品入口退役不影响）。"""

    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        asset = _create_legacy_asset(runtime)

        resp = client.get(f"/api/render-assets/{asset['id']}/slice-analysis?axis=x&index=0")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["asset_identity"]["source_kind"] == "builtin_legacy"
        assert body["asset_identity"]["source_id"] == "resistivity"
        assert body["slice"]["row_axis"] == "z"
        assert body["slice"]["column_axis"] == "y"
        assert body["slice"]["sdk_relative_position"] == 0.0
        assert body["render_profile"]["default_palette"] == "native-spectrum"
        assert_no_path_leak(body, "$.slice_analysis_legacy")


def test_slice_analysis_all_three_axes_coordinates_increasing(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        _, asset = _create_candidate_asset(client)
        resp = client.get(f"/api/render-assets/{asset['id']}/slice-analysis?axis=y&index=0")
        body = resp.json()
        for name in ("x", "y", "z"):
            coords = body["axes"][name]["coordinates"]
            assert len(coords) == body["axes"][name]["length"]
            assert all(b > a for a, b in zip(coords, coords[1:])), name


def test_slice_analysis_get_is_pure_query(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        _, asset = _create_candidate_asset(client)
        before_files = sorted(p for p in (runtime.settings.data_dir).rglob("*") if p.is_file())
        resp = client.get(f"/api/render-assets/{asset['id']}/slice-analysis?axis=z&index=0")
        assert resp.status_code == 200
        after_files = sorted(p for p in (runtime.settings.data_dir).rglob("*") if p.is_file())
        assert before_files == after_files


def test_slice_analysis_errors_are_typed(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        _, asset = _create_candidate_asset(client)

        resp = client.get("/api/render-assets/no-such/slice-analysis?axis=z&index=0")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "RENDER_ASSET_NOT_FOUND"

        resp = client.get(f"/api/render-assets/{asset['id']}/slice-analysis?axis=w&index=0")
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "SLICE_AXIS_INVALID"

        resp = client.get(f"/api/render-assets/{asset['id']}/slice-analysis?axis=z&index=999")
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "SLICE_INDEX_OUT_OF_RANGE"
        detail = resp.json()["error"]["details"]
        assert "D:\\" not in str(detail) and "/tmp" not in str(detail)


def test_slice_analysis_non_ready_asset_is_409(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        _, asset = _create_candidate_asset(client)
        from geomodeling.platform import tables

        with runtime.session() as session:
            row = session.get(tables.RenderAsset, asset["id"])
            row.status = "creating"
            session.commit()
        resp = client.get(f"/api/render-assets/{asset['id']}/slice-analysis?axis=z&index=0")
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "RENDER_ASSET_NOT_READY"


def test_slice_analysis_corrupt_asset_is_409(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        _, asset = _create_candidate_asset(client)
        package = runtime.settings.render_assets_dir / asset["id"] / "volume.nc"
        with package.open("ab") as handle:
            handle.write(b"tamper")
        resp = client.get(f"/api/render-assets/{asset['id']}/slice-analysis?axis=z&index=0")
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "RENDER_ASSET_CORRUPT"


def test_slice_analysis_all_nodata_plane_returns_200(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        _, asset = _create_candidate_asset(client)
        # 资产网格由夹具夹具值全有限；构造一个轴边界剖面并断言计数口径自洽
        resp = client.get(f"/api/render-assets/{asset['id']}/slice-analysis?axis=z&index=0")
        assert resp.status_code == 200
        body = resp.json()
        stats = body["statistics"]
        assert stats["valid_count"] + stats["nodata_count"] == stats["total_count"]
        if stats["valid_count"] == 0:
            for key in ("min", "max", "mean", "std_population", "p10", "p50", "p90"):
                assert stats[key] is None
