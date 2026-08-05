"""v0.6.1 Task 7: explicit mutation and pure query render APIs.

契约锁定（设计 §2.3）：

- GET capability/status/manifest/volume.nc 是纯查询：绝不物化成果、绝不导出
  NetCDF、绝不创建文件或改写数据库行；资产缺席 404。
- POST 是唯一显式变异：候选 POST 先显式 ``materialize`` 再创建资产；首个
  成功 201、幂等复用 200、``creating`` 行 409 ``RENDER_ASSET_IN_PROGRESS``、
  failed/interrupted 行无 ``retry_failed=true`` 时以 409 返回持久化失败。
- 文件端点只服务 ready 行：containment 校验 + 当前文件哈希核验，不符
  ``RENDER_ASSET_CORRUPT``（JSON 错误体，绝不下发字节）；非法资产 ID 400。
- legacy capability GET 纯只读：已登记网格派生 display_transform；未登记但
  测点 CSV 可读则派生同形 transform（iframe 点云模式）；都不可读
  ``display_transform=null``。legacy POST 只解析已登记源，绝不重跑 Kriging。
- 所有错误体为 ``{"error":{"code","message","details"}}``，任何响应不含本机
  绝对路径（``asset_dir`` 绝不外发）。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import geomodeling.platform.render_assets as render_assets
import geomodeling.platform.results as platform_results
from geomodeling.api.app import create_app
from geomodeling.api.deps import (
    ApiSettings,
    get_app_config,
    get_iserver_client,
    get_settings,
)
from geomodeling.platform import tables
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.legacy_render_sources import import_legacy_grid
from geomodeling.platform.render_assets import resolve_candidate_render_source
from geomodeling.platform.repositories import RenderAssetRepository
from test_api import FakeIServer, LIVE_RESPONSES, make_config
from test_platform_results import prepare_completed_run
from test_public_dto import assert_no_path_leak

LEGACY_GRID_FIXTURE = Path("tests/fixtures/legacy_rho_regular_grid.csv")

PACKAGE_FILES = {"volume.nc", "manifest.json", "checksums.sha256"}


def make_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, config=None):
    """完整应用（lifespan 拥有 runtime/worker），数据目录隔离到 tmp_path。"""

    monkeypatch.setenv("GEOMODELING_DATA_DIR", str(tmp_path / "data"))
    settings = ApiSettings(
        config_path=Path("config/default.yaml"),
        metrics_json=None,
        evidence_dir=tmp_path / "evidence",
        frontend_dist=None,
        voxel_cache_dir=None,
    )
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_app_config] = lambda: (config or make_config())
    app.dependency_overrides[get_iserver_client] = lambda: FakeIServer(LIVE_RESPONSES)
    return app


def assert_envelope(resp, status: int, code: str | None = None) -> dict:
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert set(body) == {"error"}, body
    assert set(body["error"]) == {"code", "message", "details"}
    if code is not None:
        assert body["error"]["code"] == code
    return body["error"]


def render_asset_rows(runtime) -> list:
    with runtime.session() as session:
        return session.query(tables.RenderAsset).all()


def asset_dir_listing(runtime) -> list[str]:
    assets_dir = runtime.settings.render_assets_dir
    if not assets_dir.exists():
        return []
    return sorted(p.name for p in assets_dir.iterdir())


def prepare_materialized_candidate(client) -> str:
    _, _, _, candidate_id = prepare_completed_run(client)
    resp = client.post(f"/api/results/{candidate_id}/materialize")
    assert resp.status_code in (200, 201), resp.text
    return candidate_id


def register_legacy_grid(runtime) -> None:
    import_legacy_grid(
        runtime,
        source_id="resistivity",
        csv_path=LEGACY_GRID_FIXTURE,
        x_column="X",
        y_column="Y",
        z_column="Z",
        value_column="RHO",
        property_name="RHO",
        units="unknown",
    )


def bomb_materialize(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    real = platform_results.materialize

    def spy(runtime, result_id):
        calls.append(result_id)
        return real(runtime, result_id)

    monkeypatch.setattr(platform_results, "materialize", spy)
    return calls


# ---------------------------------------------------------------------------
# 候选 capability：纯查询
# ---------------------------------------------------------------------------


def test_capability_is_pure_query_and_never_materializes(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        _, _, _, candidate_id = prepare_completed_run(client)  # 未物化
        calls = bomb_materialize(monkeypatch)

        resp = client.get(f"/api/results/{candidate_id}/render-capability")
        assert resp.status_code == 200, resp.text
        capability = resp.json()
        assert capability["source_kind"] == "candidate_result"
        assert capability["source_id"] == candidate_id
        assert capability["supported"] is False
        assert capability["reason_code"] == "RESULT_NOT_MATERIALIZED"
        assert capability["display_transform"] is None
        assert capability["render_profile"] is None
        assert capability["geolocation_status"] == "display_anchor_only"
        assert_no_path_leak(capability, "$.capability")

        # 纯查询：不物化、不建文件、不写渲染资产行
        assert calls == []
        assert not runtime.settings.result_grid(candidate_id).exists()
        assert asset_dir_listing(runtime) == []
        assert render_asset_rows(runtime) == []


def test_capability_supported_with_display_transform(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        candidate_id = prepare_materialized_candidate(client)

        resp = client.get(f"/api/results/{candidate_id}/render-capability")
        assert resp.status_code == 200, resp.text
        capability = resp.json()
        assert capability["supported"] is True
        assert capability["reason_code"] is None
        assert capability["reason"] is None
        assert capability["dimension"] == "3d"
        # v0.7.0 第二批：候选能力暴露来源默认 render_profile（linear/viridis）
        profile = capability["render_profile"]
        assert profile is not None
        assert profile["default_scale"] == "linear"
        assert profile["default_palette"] == "viridis"
        assert profile["log_available"] is True
        lo, hi = profile["value_range"]
        assert lo > 0 and hi > lo
        assert profile["filter_range"] == profile["value_range"]
        assert profile["lighting"] is True
        assert profile["gradient_opacity"] is True
        assert profile["bounding_box"] is True
        assert profile["opacity"] == 1.0
        assert capability["grid_kind"] == "regular"
        # 通用 profile（value_name=属性，无单位）：不固定 rho 语义
        assert capability["property_name"] == "属性"
        assert capability["units"] == "unknown"
        transform = capability["display_transform"]
        assert transform["contract"] == "wgs84_display_anchor_v1"
        assert transform["anchor_longitude"] == 120.0
        assert transform["anchor_latitude"] == 30.0
        assert capability["geolocation_status"] == "display_anchor_only"
        assert_no_path_leak(capability, "$.capability")


# ---------------------------------------------------------------------------
# 候选资产 status GET：缺席 404，绝不导出
# ---------------------------------------------------------------------------


def test_get_asset_status_absent_404_and_exports_nothing(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        candidate_id = prepare_materialized_candidate(client)
        calls = bomb_materialize(monkeypatch)

        resp = client.get(f"/api/results/{candidate_id}/render-assets/netcdf")
        assert_envelope(resp, 404, "RENDER_ASSET_NOT_FOUND")
        assert calls == []
        assert asset_dir_listing(runtime) == []
        assert render_asset_rows(runtime) == []


# ---------------------------------------------------------------------------
# 候选 POST：显式变异，201/200/409 语义
# ---------------------------------------------------------------------------


def test_post_creates_ready_asset_201(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        _, _, _, candidate_id = prepare_completed_run(client)  # 未物化

        resp = client.post(f"/api/results/{candidate_id}/render-assets/netcdf")
        assert resp.status_code == 201, resp.text
        record = resp.json()
        assert record["id"].startswith("nc-") and len(record["id"]) == 35
        assert record["source_kind"] == "candidate_result"
        assert record["source_id"] == candidate_id
        assert record["renderer"] == "supermap_voxelgrid_netcdf"
        assert record["status"] == "ready"
        assert len(record["grid_sha256"]) == 64
        assert len(record["netcdf_sha256"]) == 64
        assert record["manifest_url"] == f"/api/render-assets/{record['id']}/manifest"
        assert record["netcdf_url"] == f"/api/render-assets/{record['id']}/volume.nc"
        assert record["error"] is None
        assert "asset_dir" not in record
        assert_no_path_leak(record, "$.asset")

        # POST 是显式变异：物化成果 + 原子发布资产目录
        assert runtime.settings.result_grid(candidate_id).is_file()
        package_dir = runtime.settings.render_assets_dir / record["id"]
        assert {p.name for p in package_dir.iterdir()} == PACKAGE_FILES
        assert (package_dir / "volume.nc").read_bytes()[:4] == b"CDF\x01"


def test_post_is_the_only_materializing_operation(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        _, _, _, candidate_id = prepare_completed_run(client)
        calls = bomb_materialize(monkeypatch)

        client.get(f"/api/results/{candidate_id}/render-capability")
        client.get(f"/api/results/{candidate_id}/render-assets/netcdf")
        assert calls == []  # GET 绝不物化

        resp = client.post(f"/api/results/{candidate_id}/render-assets/netcdf")
        assert resp.status_code == 201, resp.text
        assert calls == [candidate_id]  # POST 恰好显式物化一次


def test_repeated_post_returns_same_asset_200(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        candidate_id = prepare_materialized_candidate(client)

        first = client.post(f"/api/results/{candidate_id}/render-assets/netcdf")
        assert first.status_code == 201, first.text
        first_record = first.json()
        volume_path = runtime.settings.render_assets_dir / first_record["id"] / "volume.nc"
        mtime = volume_path.stat().st_mtime_ns

        second = client.post(f"/api/results/{candidate_id}/render-assets/netcdf", json={})
        assert second.status_code == 200, second.text
        assert second.json() == first_record  # 幂等复用同资产同 SHA
        assert volume_path.stat().st_mtime_ns == mtime  # 未重写

        # ready 行绝不因 retry_failed 翻回创建
        third = client.post(
            f"/api/results/{candidate_id}/render-assets/netcdf",
            json={"retry_failed": True},
        )
        assert third.status_code == 200, third.text
        assert third.json()["id"] == first_record["id"]
        assert volume_path.stat().st_mtime_ns == mtime


def test_creating_row_conflict_409(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        candidate_id = prepare_materialized_candidate(client)
        source = resolve_candidate_render_source(runtime, candidate_id)
        with runtime.session() as session:
            _, created = RenderAssetRepository(session).claim(source, retry_failed=False)
        assert created  # 他方持有 creating 创建权

        resp = client.post(f"/api/results/{candidate_id}/render-assets/netcdf")
        assert_envelope(resp, 409, "RENDER_ASSET_IN_PROGRESS")


def test_failed_asset_persisted_409_until_retry_failed(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        candidate_id = prepare_materialized_candidate(client)

        with monkeypatch.context() as m:
            def broken_writer(*_args, **_kwargs):
                raise PlatformError(
                    "RENDER_NETCDF_WRITE_FAILED", "写入失败", http_status=500
                )

            m.setattr(render_assets, "write_netcdf_package", broken_writer)
            resp = client.post(f"/api/results/{candidate_id}/render-assets/netcdf")
            assert_envelope(resp, 500, "RENDER_NETCDF_WRITE_FAILED")

        # 未显式 retry_failed：返回持久化失败（409），绝不重建
        resp = client.post(f"/api/results/{candidate_id}/render-assets/netcdf")
        assert_envelope(resp, 409, "RENDER_NETCDF_WRITE_FAILED")
        assert asset_dir_listing(runtime) == []

        # GET status 读持久化失败记录，不重建
        status = client.get(f"/api/results/{candidate_id}/render-assets/netcdf")
        assert status.status_code == 200, status.text
        record = status.json()
        assert record["status"] == "failed"
        assert record["error"]["code"] == "RENDER_NETCDF_WRITE_FAILED"
        assert record["manifest_url"] is None
        assert record["netcdf_url"] is None
        assert_no_path_leak(record, "$.failed_asset")
        assert asset_dir_listing(runtime) == []

        # retry_failed=true 才允许重建
        retried = client.post(
            f"/api/results/{candidate_id}/render-assets/netcdf",
            json={"retry_failed": True},
        )
        assert retried.status_code == 201, retried.text
        assert retried.json()["status"] == "ready"


# ---------------------------------------------------------------------------
# manifest / volume.nc：身份、头与 fail-closed
# ---------------------------------------------------------------------------


def test_manifest_and_volume_served_with_identity_headers(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        candidate_id = prepare_materialized_candidate(client)
        record = client.post(f"/api/results/{candidate_id}/render-assets/netcdf").json()
        asset_id = record["id"]

        manifest_resp = client.get(f"/api/render-assets/{asset_id}/manifest")
        assert manifest_resp.status_code == 200, manifest_resp.text
        assert manifest_resp.headers["content-type"].startswith("application/json")
        manifest = manifest_resp.json()
        assert manifest["format"] == "supermap-voxel-netcdf"
        assert manifest["version"] == 2
        assert manifest["renderer"] == "supermap_voxelgrid_netcdf"
        assert manifest["source_kind"] == "candidate_result"
        assert manifest["source_id"] == candidate_id
        assert manifest["grid_sha256"] == record["grid_sha256"]
        assert manifest["netcdf_sha256"] == record["netcdf_sha256"]
        assert manifest["geolocation_status"] == "display_anchor_only"
        assert manifest["display_transform"]["contract"] == "wgs84_display_anchor_v1"
        assert_no_path_leak(manifest, "$.manifest")

        volume_resp = client.get(f"/api/render-assets/{asset_id}/volume.nc")
        assert volume_resp.status_code == 200, volume_resp.text
        assert volume_resp.headers["content-type"] == "application/x-netcdf"
        assert volume_resp.headers["etag"] == f'"sha256-{record["netcdf_sha256"]}"'
        assert volume_resp.headers["cache-control"] == "public, immutable"
        assert volume_resp.content[:4] == b"CDF\x01"
        assert hashlib.sha256(volume_resp.content).hexdigest() == record["netcdf_sha256"]


def test_invalid_asset_ids_and_traversal_rejected(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        prepare_materialized_candidate(client)

        for bad_id in ("not-an-asset", "nc-xyz", "nc-" + "0" * 31):
            resp = client.get(f"/api/render-assets/{bad_id}/manifest")
            assert_envelope(resp, 400, "RENDER_ASSET_ID_INVALID")
            resp = client.get(f"/api/render-assets/{bad_id}/volume.nc")
            assert_envelope(resp, 400, "RENDER_ASSET_ID_INVALID")

        # 形态合法但不存在 → 404
        missing = "nc-" + "0" * 32
        assert_envelope(
            client.get(f"/api/render-assets/{missing}/manifest"), 404, "RENDER_ASSET_NOT_FOUND"
        )
        assert_envelope(
            client.get(f"/api/render-assets/{missing}/volume.nc"), 404, "RENDER_ASSET_NOT_FOUND"
        )

        # 路径穿越：反斜杠编码形态命中路由后按非法 ID 拒绝（400）；
        # 正斜杠形态改变路径段数，绝不命中资产文件（404）
        resp = client.get("/api/render-assets/..%5C..%5Csecret/manifest")
        assert_envelope(resp, 400, "RENDER_ASSET_ID_INVALID")
        resp = client.get("/api/render-assets/..%2F..%2Fsecret/manifest")
        assert resp.status_code == 404


def test_file_endpoints_reject_non_ready_rows(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        candidate_id = prepare_materialized_candidate(client)
        source = resolve_candidate_render_source(runtime, candidate_id)
        with runtime.session() as session:
            record, _ = RenderAssetRepository(session).claim(source, retry_failed=False)
        asset_id = record.id  # creating 行

        assert_envelope(
            client.get(f"/api/render-assets/{asset_id}/manifest"), 409, "RENDER_ASSET_NOT_READY"
        )
        assert_envelope(
            client.get(f"/api/render-assets/{asset_id}/volume.nc"), 409, "RENDER_ASSET_NOT_READY"
        )

        with runtime.session() as session:
            RenderAssetRepository(session).mark_failed(
                asset_id, code="X_FAILED", message="失败", details={}
            )
        assert_envelope(
            client.get(f"/api/render-assets/{asset_id}/manifest"), 409, "RENDER_ASSET_NOT_READY"
        )
        assert_envelope(
            client.get(f"/api/render-assets/{asset_id}/volume.nc"), 409, "RENDER_ASSET_NOT_READY"
        )


def test_hash_mismatch_returns_corrupt_json_not_bytes(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        candidate_id = prepare_materialized_candidate(client)
        record = client.post(f"/api/results/{candidate_id}/render-assets/netcdf").json()
        asset_id = record["id"]
        volume_path = runtime.settings.render_assets_dir / asset_id / "volume.nc"
        payload = bytearray(volume_path.read_bytes())
        payload[100] ^= 0xFF
        volume_path.write_bytes(bytes(payload))

        resp = client.get(f"/api/render-assets/{asset_id}/volume.nc")
        assert_envelope(resp, 409, "RENDER_ASSET_CORRUPT")
        assert resp.headers["content-type"].startswith("application/json")  # 绝不下发字节

        resp = client.get(f"/api/render-assets/{asset_id}/manifest")
        assert_envelope(resp, 409, "RENDER_ASSET_CORRUPT")


# ---------------------------------------------------------------------------
# legacy 内置电阻率案例
# ---------------------------------------------------------------------------


def test_legacy_capability_unregistered_and_points_csv_unreadable(tmp_path, monkeypatch):
    config = make_config(standardized=(tmp_path / "missing.csv").resolve())
    app = make_app(tmp_path, monkeypatch, config=config)
    with TestClient(app) as client:
        resp = client.get("/api/cases/resistivity/render-capability")
        assert resp.status_code == 200, resp.text
        capability = resp.json()
        assert capability["source_kind"] == "builtin_legacy"
        assert capability["source_id"] == "resistivity"
        assert capability["supported"] is False
        assert capability["reason_code"] == "LEGACY_RENDER_SOURCE_NOT_REGISTERED"
        assert capability["display_transform"] is None
        assert capability["render_profile"] is None
        assert capability["property_name"] is None
        assert capability["geolocation_status"] == "display_anchor_only"
        assert_no_path_leak(capability, "$.legacy_capability")


def test_legacy_capability_unregistered_derives_transform_from_points(tmp_path, monkeypatch):
    points_csv = tmp_path / "points.csv"
    points_csv.write_text(
        "X,Y,Z,RHO\n0,0,0,1\n10,0,0,2\n0,20,-5,3\n10,20,-5,4\n", encoding="utf-8"
    )
    config = make_config(standardized=points_csv)
    app = make_app(tmp_path, monkeypatch, config=config)
    with TestClient(app) as client:
        resp = client.get("/api/cases/resistivity/render-capability")
        assert resp.status_code == 200, resp.text
        capability = resp.json()
        assert capability["supported"] is False
        assert capability["reason_code"] == "LEGACY_RENDER_SOURCE_NOT_REGISTERED"
        # 测点 CSV 可读：同形 transform 供 iframe 点云模式（display_anchor_only）
        transform = capability["display_transform"]
        assert transform is not None
        assert transform["contract"] == "wgs84_display_anchor_v1"
        assert transform["origin_x"] == pytest.approx(5.0)
        assert transform["origin_y"] == pytest.approx(10.0)
        assert capability["geolocation_status"] == "display_anchor_only"
        assert_no_path_leak(capability, "$.legacy_capability_points")


def test_legacy_capability_registered_grid_supported(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        register_legacy_grid(runtime)

        resp = client.get("/api/cases/resistivity/render-capability")
        assert resp.status_code == 200, resp.text
        capability = resp.json()
        assert capability["supported"] is True
        assert capability["reason_code"] is None
        assert capability["dimension"] == "3d"
        assert capability["grid_kind"] == "regular"
        assert capability["property_name"] == "RHO"
        assert capability["units"] == "unknown"
        # v0.7.0 第二批：legacy 默认 log/native-spectrum；本夹具最小值为 0
        # → log_available=False 降级 linear（不丢弃/不平移原始值）
        profile = capability["render_profile"]
        assert profile is not None
        assert profile["default_scale"] == "linear"
        assert profile["default_palette"] == "native-spectrum"
        assert profile["log_available"] is False
        assert profile["value_range"][0] == 0.0
        assert profile["property_name"] == "RHO"
        assert profile["unit"] == "unknown"
        transform = capability["display_transform"]
        # 灯具网格轴 X=[0,20,40]、Y=[0,20,40,60] → 原点即中心
        assert transform["origin_x"] == pytest.approx(20.0)
        assert transform["origin_y"] == pytest.approx(30.0)
        assert_no_path_leak(capability, "$.legacy_capability_registered")


def test_legacy_post_unregistered_404_and_status_absent(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        resp = client.post("/api/cases/resistivity/render-assets/netcdf")
        assert_envelope(resp, 404, "LEGACY_RENDER_SOURCE_NOT_REGISTERED")
        resp = client.get("/api/cases/resistivity/render-assets/netcdf")
        assert_envelope(resp, 404, "RENDER_ASSET_NOT_FOUND")


def test_legacy_post_registered_201_then_200_never_materializes(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        register_legacy_grid(runtime)
        calls = bomb_materialize(monkeypatch)

        resp = client.post("/api/cases/resistivity/render-assets/netcdf")
        assert resp.status_code == 201, resp.text
        record = resp.json()
        assert record["source_kind"] == "builtin_legacy"
        assert record["source_id"] == "resistivity"
        assert record["status"] == "ready"
        assert calls == []  # legacy POST 只解析已登记源，绝不重跑 Kriging/物化

        status = client.get("/api/cases/resistivity/render-assets/netcdf")
        assert status.status_code == 200, status.text
        assert status.json() == record

        again = client.post("/api/cases/resistivity/render-assets/netcdf")
        assert again.status_code == 200, again.text
        assert again.json()["id"] == record["id"]

        # legacy 资产同样经不可变文件端点下发
        volume = client.get(f"/api/render-assets/{record['id']}/volume.nc")
        assert volume.status_code == 200, volume.text
        assert volume.content[:4] == b"CDF\x01"


# ---------------------------------------------------------------------------
# legacy 渲染源产品内导入：POST /api/cases/resistivity/render-sources/import
# ---------------------------------------------------------------------------

LEGACY_IMPORT_URL = "/api/cases/resistivity/render-sources/import"

IMPORT_FORM = {
    "x_column": "X",
    "y_column": "Y",
    "z_column": "Z",
    "value_column": "RHO",
    "property_name": "RHO",
    "units": "unknown",
}

# 与 fixture 网格不同（2×2×2、值域不同）的合法网格：覆盖保护测试专用
OTHER_GRID_CSV = (
    "X,Y,Z,RHO\n"
    "0,0,0,1\n10,0,0,2\n0,10,0,3\n10,10,0,4\n"
    "0,0,-5,5\n10,0,-5,6\n0,10,-5,7\n10,10,-5,8\n"
)


def post_import(client, csv_text: str, **form_overrides):
    form = {**IMPORT_FORM, **form_overrides}
    return client.post(
        LEGACY_IMPORT_URL,
        files={"file": ("grid.csv", csv_text.encode("utf-8"), "text/csv")},
        data=form,
    )


def legacy_source_listing(runtime) -> list[str]:
    root = runtime.settings.render_sources_dir
    if not root.exists():
        return []
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))


def test_legacy_import_registers_201_and_flips_capability(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        before = client.get("/api/cases/resistivity/render-capability").json()
        assert before["supported"] is False
        assert before["reason_code"] == "LEGACY_RENDER_SOURCE_NOT_REGISTERED"

        resp = post_import(client, LEGACY_GRID_FIXTURE.read_text(encoding="utf-8"))
        assert resp.status_code == 201, resp.text
        record = resp.json()
        # 登记身份白名单：只有逻辑身份/相对工件目录/SHA，绝无绝对路径
        assert set(record) == {
            "source_kind",
            "source_id",
            "grid_sha256",
            "property_name",
            "units",
            "shape",
            "artifact_dir",
            "import_source_sha256",
        }
        assert record["source_kind"] == "builtin_legacy"
        assert record["source_id"] == "resistivity"
        assert record["shape"] == [3, 4, 5]
        assert record["artifact_dir"].startswith("builtin_legacy/resistivity/")
        assert len(record["grid_sha256"]) == 64
        assert len(record["import_source_sha256"]) == 64
        assert_no_path_leak(record, "$.import")

        # 登记后能力翻转为 supported，体渲染走既有资产流程
        after = client.get("/api/cases/resistivity/render-capability").json()
        assert after["supported"] is True
        assert after["property_name"] == "RHO"

        listing = legacy_source_listing(runtime)
        assert "builtin_legacy/resistivity/current.json" in listing


def test_legacy_import_idempotent_reimport_200_same_identity(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        csv_text = LEGACY_GRID_FIXTURE.read_text(encoding="utf-8")

        first = post_import(client, csv_text)
        assert first.status_code == 201, first.text
        current_json = (
            runtime.settings.render_sources_dir / "builtin_legacy" / "resistivity" / "current.json"
        )
        mtime = current_json.stat().st_mtime_ns

        second = post_import(client, csv_text)
        assert second.status_code == 200, second.text
        assert second.json() == first.json()  # 幂等：同身份返回既有登记
        assert current_json.stat().st_mtime_ns == mtime  # 登记状态未改写


def test_legacy_import_conflict_409_never_overwrites(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        register_legacy_grid(runtime)

        resp = post_import(client, OTHER_GRID_CSV)
        assert_envelope(resp, 409, "LEGACY_RENDER_SOURCE_CONFLICT")
        serialized = json.dumps(resp.json(), ensure_ascii=False)
        assert str(tmp_path) not in serialized

        # 既有登记原样保留：同网格重导入仍幂等 200
        again = post_import(client, LEGACY_GRID_FIXTURE.read_text(encoding="utf-8"))
        assert again.status_code == 200, again.text


def test_legacy_import_validation_failures_422_and_zero_residue(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        cases = [
            # 缺一个笛卡尔格点（8 缺 1）
            (
                "X,Y,Z,RHO\n0,0,0,1\n10,0,0,2\n0,10,0,3\n10,10,0,4\n"
                "0,0,-5,5\n10,0,-5,6\n0,10,-5,7\n",
                {},
                "LEGACY_IMPORT_GRID_INCOMPLETE",
            ),
            # 指定的坐标列不存在
            ("X,Y,Z,RHO\n0,0,0,1\n", {"y_column": "LAT"}, "LEGACY_IMPORT_COLUMN_NOT_FOUND"),
            # 重复坐标元组
            ("X,Y,Z,RHO\n0,0,0,1\n0,0,0,2\n", {}, "LEGACY_IMPORT_DUPLICATE_COORDINATES"),
            # 非有限坐标
            ("X,Y,Z,RHO\n0,0,0,1\nNaN,0,0,2\n", {}, "LEGACY_IMPORT_COORDINATE_INVALID"),
            # X 轴间距不等（0,10,30），不是规则轴
            (
                "X,Y,Z,RHO\n0,0,0,1\n10,0,0,2\n30,0,0,3\n0,10,0,4\n10,10,0,5\n30,10,0,6\n"
                "0,0,-5,7\n10,0,-5,8\n30,0,-5,9\n0,10,-5,10\n10,10,-5,11\n30,10,-5,12\n",
                {},
                "LEGACY_IMPORT_AXIS_IRREGULAR",
            ),
            # 空文件
            ("", {}, "LEGACY_IMPORT_PARSE_FAILED"),
        ]
        for csv_text, overrides, code in cases:
            resp = post_import(client, csv_text, **overrides)
            assert_envelope(resp, 422, code)
            serialized = json.dumps(resp.json(), ensure_ascii=False)
            assert str(tmp_path) not in serialized
        # 零残留：全部失败后 render-sources 目录没有任何登记状态或工件
        assert legacy_source_listing(runtime) == []


def test_legacy_import_missing_parameters_keep_unified_envelope(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        csv_bytes = LEGACY_GRID_FIXTURE.read_bytes()

        # 缺文件
        resp = client.post(LEGACY_IMPORT_URL, data=IMPORT_FORM)
        assert_envelope(resp, 422, "LEGACY_IMPORT_REQUEST_INVALID")
        # 缺列名参数
        form = {key: value for key, value in IMPORT_FORM.items() if key != "z_column"}
        resp = client.post(
            LEGACY_IMPORT_URL,
            files={"file": ("grid.csv", csv_bytes, "text/csv")},
            data=form,
        )
        assert_envelope(resp, 422, "LEGACY_IMPORT_REQUEST_INVALID")
        # 空白属性名
        resp = post_import(
            client, LEGACY_GRID_FIXTURE.read_text(encoding="utf-8"), property_name="  "
        )
        assert_envelope(resp, 422, "LEGACY_IMPORT_REQUEST_INVALID")
        assert legacy_source_listing(runtime) == []


def test_legacy_import_oversized_upload_413(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "geomodeling.api.routes.rendering.MAX_LEGACY_IMPORT_BYTES", 1024
    )
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        big_csv = "X,Y,Z,RHO\n" + "0,0,0,1\n" * 200  # 远超 1024 字节
        resp = post_import(client, big_csv)
        assert_envelope(resp, 413, "LEGACY_IMPORT_UPLOAD_TOO_LARGE")
        assert legacy_source_listing(runtime) == []


# ---------------------------------------------------------------------------
# 路由注册顺序与错误体脱敏
# ---------------------------------------------------------------------------


def test_rendering_routes_registered_without_shadowing(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        paths = client.get("/openapi.json").json()["paths"]
        for path in (
            "/api/results/{result_id}/render-capability",
            "/api/results/{result_id}/render-assets/netcdf",
            "/api/cases/resistivity/render-capability",
            "/api/cases/resistivity/render-assets/netcdf",
            "/api/cases/resistivity/render-sources/import",
            "/api/render-assets/{asset_id}/manifest",
            "/api/render-assets/{asset_id}/volume.nc",
        ):
            assert path in paths, path
        # legacy 精确路由不被遮蔽；v0.7.0 DAT 路由已退出产品面
        legacy = client.get("/api/cases/resistivity")
        assert legacy.status_code == 200, legacy.text
        assert legacy.json()["case_id"] == "resistivity"
        assert "/api/cases/{case_id}/microseismic-imports" not in paths
        # 渲染 capability 命中渲染路由而非动态案例路由
        capability = client.get("/api/cases/resistivity/render-capability")
        assert capability.status_code == 200, capability.text
        assert capability.json()["source_kind"] == "builtin_legacy"


def test_error_bodies_share_envelope_and_hide_local_paths(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        candidate_id = prepare_materialized_candidate(client)

        responses = [
            client.get(f"/api/results/{candidate_id}/render-assets/netcdf"),  # 404
            client.get("/api/render-assets/bogus/manifest"),  # 400
            client.get(f"/api/render-assets/{'nc-' + '0' * 32}/volume.nc"),  # 404
            client.post("/api/cases/resistivity/render-assets/netcdf"),  # 404
            client.get("/api/results/no-such-result/render-capability"),  # 404
        ]
        for resp in responses:
            body = resp.json()
            assert set(body) == {"error"}, body
            assert set(body["error"]) == {"code", "message", "details"}
            serialized = json.dumps(body, ensure_ascii=False)
            assert str(tmp_path) not in serialized
            assert "asset_dir" not in serialized
