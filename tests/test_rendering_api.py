"""v0.6.1 Task 7: explicit mutation and pure query render APIs.

契约锁定（设计 §2.3）：

- GET capability/status/manifest/volume.nc 是纯查询：绝不物化成果、绝不导出
  NetCDF、绝不创建文件或改写数据库行；资产缺席 404。
- POST 是唯一显式变异：候选 POST 先显式 ``materialize`` 再创建资产；首个
  成功 201、幂等复用 200、``creating`` 行 409 ``RENDER_ASSET_IN_PROGRESS``、
  failed/interrupted 行无 ``retry_failed=true`` 时以 409 返回持久化失败。
- 文件端点只服务 ready 行：containment 校验 + 当前文件哈希核验，不符
  ``RENDER_ASSET_CORRUPT``（JSON 错误体，绝不下发字节）；非法资产 ID 400。
- v0.8.0 Task 6：legacy 电阻率渲染产品入口（capability/资产 POST/状态 GET/
  产品内导入 POST）类型化退役，一律 410 ``LEGACY_RESISTIVITY_RETIRED``；
  已登记的历史 ``builtin_legacy`` 资产仍经不可变资产文件路由只读下发。
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
from geomodeling.platform.legacy_render_sources import (
    import_legacy_grid,
    resolve_legacy_render_source,
)
from geomodeling.platform.render_assets import resolve_candidate_render_source
from geomodeling.platform.repositories import RenderAssetRepository
from geomodeling.platform.schemas import STATUS_READY
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
# v0.8.0 Task 6：legacy 内置电阻率渲染入口类型化退役
#
# 四个产品路由（capability / 资产 POST / 资产状态 GET / 产品内导入 POST）一律
# 410 LEGACY_RESISTIVITY_RETIRED，绝不返回旧 S3M 数值；``builtin_legacy`` 来源
# 只有 resistivity 一个实例，退役即全部 410。LEGACY_SOURCE_KIND 通用登记/解析
# 机制保留（render_cli、demo_check、历史资产文件路由不受影响）。
# ---------------------------------------------------------------------------

RETIRED_LEGACY_RENDER_ROUTES = (
    ("GET", "/api/cases/resistivity/render-capability"),
    ("POST", "/api/cases/resistivity/render-assets/netcdf"),
    ("GET", "/api/cases/resistivity/render-assets/netcdf"),
    ("POST", "/api/cases/resistivity/render-sources/import"),
)


def _hit(client, method: str, path: str):
    # 退役判定先于一切请求体/表单解析：裸 POST 也必须 410
    return client.get(path) if method == "GET" else client.post(path)


def test_legacy_render_routes_retired_when_unregistered(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        for method, path in RETIRED_LEGACY_RENDER_ROUTES:
            _assert_retired(_hit(client, method, path))


def test_legacy_render_routes_retired_even_when_grid_registered(tmp_path, monkeypatch):
    """已登记旧网格同样 410：产品解析入口退役，绝不翻回旧 S3M 渲染链。"""

    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        register_legacy_grid(runtime)
        for method, path in RETIRED_LEGACY_RENDER_ROUTES:
            _assert_retired(_hit(client, method, path))


def _assert_retired(resp) -> None:
    body = assert_envelope(resp, 410, "LEGACY_RESISTIVITY_RETIRED")
    serialized = json.dumps(body, ensure_ascii=False)
    assert "asset_dir" not in serialized


def test_historical_legacy_render_asset_files_still_served(tmp_path, monkeypatch):
    """历史 builtin_legacy 资产经不可变资产文件路由只读保留。

    产品注册/解析入口退役不影响已登记资产记录的读取：资产经服务层创建
    （与旧 POST 同一 ``create_render_asset``），manifest/volume.nc 照常下发。
    """

    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        register_legacy_grid(runtime)
        source = resolve_legacy_render_source(runtime, "resistivity")
        record, created = render_assets.create_render_asset(runtime, source, retry_failed=False)
        assert created is True
        assert record.status == STATUS_READY
        assert record.source_kind == "builtin_legacy"

        volume = client.get(f"/api/render-assets/{record.id}/volume.nc")
        assert volume.status_code == 200, volume.text
        assert volume.content[:4] == b"CDF\x01"
        manifest = client.get(f"/api/render-assets/{record.id}/manifest")
        assert manifest.status_code == 200, manifest.text
        assert manifest.json()["source_kind"] == "builtin_legacy"
        assert manifest.json()["source_id"] == "resistivity"


def test_retired_import_route_registers_nothing(tmp_path, monkeypatch):
    """退役的产品内导入绝不登记新渲染源：render-sources 目录零残留。"""

    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        resp = post_import(client, LEGACY_GRID_FIXTURE.read_text(encoding="utf-8"))
        _assert_retired(resp)
        assert legacy_source_listing(runtime) == []


# ---------------------------------------------------------------------------
# legacy 渲染源产品内导入（已退役）：POST /api/cases/resistivity/render-sources/import
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


def test_legacy_import_retired_410_regardless_of_payload(tmp_path, monkeypatch):
    """退役后任何导入请求（完整表单/缺参/超限）一律 410，绝不读上传字节。"""

    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        csv_text = LEGACY_GRID_FIXTURE.read_text(encoding="utf-8")
        # 完整合法表单
        _assert_retired(post_import(client, csv_text))
        # 缺文件/缺参数同样 410（退役判定先于请求校验）
        _assert_retired(client.post(LEGACY_IMPORT_URL, data=IMPORT_FORM))
        form = {key: value for key, value in IMPORT_FORM.items() if key != "z_column"}
        _assert_retired(
            client.post(
                LEGACY_IMPORT_URL,
                files={"file": ("grid.csv", csv_text.encode("utf-8"), "text/csv")},
                data=form,
            )
        )
        # 全部拒绝后零登记残留
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
        # v0.8.0 Task 6：legacy 渲染路由仍注册但已类型化退役（410），
        # 命中退役路由而非动态案例路由
        capability = client.get("/api/cases/resistivity/render-capability")
        assert capability.status_code == 410, capability.text
        assert capability.json()["error"]["code"] == "LEGACY_RESISTIVITY_RETIRED"


def test_error_bodies_share_envelope_and_hide_local_paths(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        candidate_id = prepare_materialized_candidate(client)

        responses = [
            client.get(f"/api/results/{candidate_id}/render-assets/netcdf"),  # 404
            client.get("/api/render-assets/bogus/manifest"),  # 400
            client.get(f"/api/render-assets/{'nc-' + '0' * 32}/volume.nc"),  # 404
            client.post("/api/cases/resistivity/render-assets/netcdf"),  # 410 退役
            client.get("/api/results/no-such-result/render-capability"),  # 404
        ]
        for resp in responses:
            body = resp.json()
            assert set(body) == {"error"}, body
            assert set(body["error"]) == {"code", "message", "details"}
            serialized = json.dumps(body, ensure_ascii=False)
            assert str(tmp_path) not in serialized
            assert "asset_dir" not in serialized


# ---------------------------------------------------------------------------
# v0.8.0 Task 8：dsi_like 成功候选走统一 candidate_result → NetCDF → 分析/导出链
#
# 渲染源解析、NetCDF 发布、剖面分析/导出全部算法无关（无任何算法字面量白
# 名单），dsi_like 与 IDW/普通克里金逐位共用同一路径；绝无 DSI 专用渲染器、
# 点云回退或第二传输通道。本测试为防回归锁定。
# ---------------------------------------------------------------------------


def _seed_preset_runtime(runtime, tmp_path: Path):
    """按 test_resistivity_preset_seed 夹具模式 seed 电阻率预置运行库。"""

    from geomodeling.platform.resistivity_preset import (
        load_resistivity_preset,
        seed_resistivity_preset,
    )
    from test_resistivity_preset import write_resistivity_fixture
    from test_resistivity_preset_seed import _fixture_baseline

    source_path = write_resistivity_fixture(tmp_path / "rho-source.csv", rows=17_549)
    source = load_resistivity_preset(source_path)
    seed_resistivity_preset(
        runtime, source_path=source_path, baseline=_fixture_baseline(source)
    )
    return source


def _run_dsi_like_candidate(runtime, source) -> str:
    """seed 运行库上创建 dsi_like 用户实验成功候选（显式粗网格控制物化耗时）。"""

    import threading
    import uuid

    from geomodeling.modeling.runner import execute_run
    from geomodeling.platform.resistivity_preset import PRESET_CASE_ID
    from test_resistivity_preset_seed import FIXTURE_GRID_RESOLUTION

    with runtime.session() as session:
        dataset_id = (
            session.query(tables.DatasetVersion)
            .filter(tables.DatasetVersion.case_id == PRESET_CASE_ID)
            .one()
            .id
        )
    frame = source.frame
    params = {
        "algorithm": "dsi_like",
        "dataset_version_id": dataset_id,
        "search_mode": "manual",
        "parameters": {"neighbor_connectivity": 6},
        "validation": {
            "method": "spatial_kfold",
            "folds": 3,
            "seed": 11,
            "holdout_fraction": 0.2,
        },
        # 显式粗网格（同夹具基线口径）：物化网格约百余节点，测试耗时可控
        "grid": {
            "bounds": [
                [float(frame["X"].min()), float(frame["X"].max())],
                [float(frame["Y"].min()), float(frame["Y"].max())],
                [float(frame["Z"].min()), float(frame["Z"].max())],
            ],
            "resolution": list(FIXTURE_GRID_RESOLUTION),
            "max_cells": 100_000,
        },
    }
    experiment_id = f"dsi-exp-{uuid.uuid4().hex[:8]}"
    run_id = f"dsi-run-{uuid.uuid4().hex[:8]}"
    with runtime.session() as session:
        session.add(
            tables.Experiment(
                id=experiment_id,
                case_id=PRESET_CASE_ID,
                name="DSI-like 渲染链实验",
                params_json=tables.dumps_canonical(params),
            )
        )
        session.add(tables.Run(id=run_id, experiment_id=experiment_id, status="queued"))
        session.commit()
    outcome = execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "succeeded"
    with runtime.session() as session:
        return (
            session.query(tables.CandidateResult)
            .filter(tables.CandidateResult.run_id == run_id)
            .one()
            .id
        )


def _slice_png(width: int = 8, height: int = 8) -> bytes:
    """最小合法 PNG（同 test_slice_exports._png 构造；复制以避免跨文件循环导入）。"""

    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return (
            struct.pack(">I", len(data))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def test_dsi_like_candidate_uses_candidate_result_netcdf(tmp_path, monkeypatch):
    """dsi_like 成功候选与 IDW/Kriging 走完全相同的渲染/分析/导出链。"""

    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        source = _seed_preset_runtime(runtime, tmp_path)
        candidate_id = _run_dsi_like_candidate(runtime, source)

        # 能力（纯查询）：未物化前与 IDW/Kriging 同一语义——supported=False +
        # RESULT_NOT_MATERIALIZED，绝不因算法不同而物化或放行
        resp = client.get(f"/api/results/{candidate_id}/render-capability")
        assert resp.status_code == 200, resp.text
        capability = resp.json()
        assert capability["source_kind"] == "candidate_result"
        assert capability["source_id"] == candidate_id
        assert capability["supported"] is False
        assert capability["reason_code"] == "RESULT_NOT_MATERIALIZED"
        assert capability["render_profile"] is None
        assert_no_path_leak(capability, "$.dsi_capability")

        # POST 显式变异：物化 + 首个资产 201 ready
        resp = client.post(f"/api/results/{candidate_id}/render-assets/netcdf")
        assert resp.status_code == 201, resp.text
        record = resp.json()
        assert record["source_kind"] == "candidate_result"
        assert record["source_id"] == candidate_id
        assert record["status"] == "ready"

        # 物化后能力：3D 规则网格、RHO 语义来自预置 profile、候选默认 render_profile
        resp = client.get(f"/api/results/{candidate_id}/render-capability")
        assert resp.status_code == 200, resp.text
        capability = resp.json()
        assert capability["supported"] is True
        assert capability["reason_code"] is None
        assert capability["dimension"] == "3d"
        assert capability["grid_kind"] == "regular"
        assert capability["property_name"] == "RHO"
        assert capability["render_profile"] is not None
        assert capability["render_profile"]["default_scale"] == "linear"
        assert capability["render_profile"]["default_palette"] == "viridis"
        assert_no_path_leak(record, "$.dsi_asset")

        # 物化成果 metadata（结果级 manifest）：算法/参数/源 SHA/数据版本指纹/
        # 网格规格/归属链 provenance 全部按通用口径落盘
        metadata = json.loads(
            (runtime.settings.result_grid(candidate_id).parent / "metadata.json").read_text(
                encoding="utf-8"
            )
        )
        assert metadata["algorithm"] == "dsi_like"
        assert metadata["parameters"]["neighbor_connectivity"] == 6
        assert metadata["dimension"] == "3d"
        assert len(metadata["source_sha256"]) == 64
        assert len(metadata["standardized_sha256"]) == 64
        assert len(metadata["fingerprint"]) == 64
        assert metadata["dataset_version_id"]
        assert metadata["run_id"] and metadata["experiment_id"]
        assert len(metadata["bounds"]) == 3
        assert len(metadata["resolution"]) == 3
        shape = metadata["shape"]
        assert len(shape) == 3 and all(int(n) >= 2 for n in shape)
        assert metadata["cell_count"] == shape[0] * shape[1] * shape[2]
        assert metadata["grid_sha256"] == record["grid_sha256"]

        # NetCDF 包 manifest：与 IDW/Kriging 同一 v2 格式合同（算法无关）
        manifest_resp = client.get(f"/api/render-assets/{record['id']}/manifest")
        assert manifest_resp.status_code == 200, manifest_resp.text
        manifest = manifest_resp.json()
        assert manifest["format"] == "supermap-voxel-netcdf"
        assert manifest["version"] == 2
        assert manifest["source_kind"] == "candidate_result"
        assert manifest["source_id"] == candidate_id
        assert manifest["grid_sha256"] == metadata["grid_sha256"]
        assert manifest["netcdf_sha256"] == record["netcdf_sha256"]
        assert manifest["property_name"] == "RHO"

        # volume.nc 字节服务（同一传输通道、同一身份头）
        volume = client.get(f"/api/render-assets/{record['id']}/volume.nc")
        assert volume.status_code == 200, volume.text
        assert volume.content[:4] == b"CDF\x01"
        assert hashlib.sha256(volume.content).hexdigest() == record["netcdf_sha256"]

        # X/Y/Z 正交剖面分析（同一权威网格口径，渲染资产身份回链）
        for axis in ("x", "y", "z"):
            analysis = client.get(
                f"/api/render-assets/{record['id']}/slice-analysis",
                params={"axis": axis, "index": 0},
            )
            assert analysis.status_code == 200, analysis.text
            body = analysis.json()
            assert body["asset_identity"]["source_kind"] == "candidate_result"
            assert body["asset_identity"]["source_id"] == candidate_id
            assert body["property"] == {"name": "RHO", "unit": "Ω·m"}
            assert body["statistics"]["valid_count"] > 0

        # 剖面 ZIP 导出（服务端权威重算；导出归属回链到 dsi_like 候选）
        export = client.post(
            f"/api/render-assets/{record['id']}/slice-exports",
            files={
                "axis": (None, "z"),
                "index": (None, "0"),
                "image": ("slice.png", _slice_png(), "image/png"),
            },
        )
        assert export.status_code == 201, export.text
        assert export.json()["candidate_result_id"] == candidate_id
