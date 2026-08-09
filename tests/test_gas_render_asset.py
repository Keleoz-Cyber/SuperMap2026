"""v0.8.0 第三批 Task 6：瓦斯官方候选规则网格物化与 NetCDF 渲染资产链。

针对**真实内置源 + 真实冻结基线**的完整瓦斯 seed 链（``seed_gas_preset``
默认参数即生产入口），断言通用 Case→Dataset→Experiment→Run→Candidate→
materialize→NetCDF→RenderAsset→剖面/导出链对瓦斯开箱即用：网格 bounds 逐轴
恰为瓦斯数据 bounds（冻结基线网格合同），三轴长度/变量名/单位/坐标类型写入
manifest，volume/slice/export 身份全部可追溯到官方候选。通用链在 v0.8.0 已
泛化（属性语义来自数据集 profile 映射，绝不固定 rho 语义），本文件全部断言
作为回归锁定保留。

耗时控制（2026-08-09 本机实测）：官方网格 151×333×12 = 603,396 节点，
ordinary_kriging(spherical, neighbor_count=24) 全数据 fit ≈0.04s、603k 节点
逐目标预测 ≈140s，``seed_gas_preset`` 总耗时 ≈145s（含 5 折空间 CV），在
计划允许的 1–3 分钟窗口内，故使用真实冻结网格、不缩小。模块级夹具共享同一
runtime/seed/client/资产，整个文件只付一次物化成本。

NoData 语义（实测锁定）：官方网格逐轴恰为观测包围盒（绝不外推，盒外无网格
节点），kriging 24 邻点在盒内处处足够 → 603,396 体元全部有限、零 NoData；
有效值域 [1.540914, 30.278860] 全正（log_available=True）。空资产（全
NoData/全非有限）与缺失/非有限/超 bounds 输入的类型化失败由失败态锁定测试
覆盖：一律 fail-closed，空资产绝不标 ready。
"""

from __future__ import annotations

import hashlib
import io
import json
import struct
import threading
import uuid
import zipfile
import zlib
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

import geomodeling.platform.render_assets as render_assets
from geomodeling.api.app import create_app
from geomodeling.api.deps import (
    ApiSettings,
    get_app_config,
    get_iserver_client,
    get_settings,
)
from geomodeling.modeling.runner import execute_run
from geomodeling.platform import PlatformRuntime, tables
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.gas_preset import (
    PRESET_CASE_ID,
    VALIDATION_CONTRACT,
    seed_gas_preset,
)
from geomodeling.platform.render_assets import (
    RENDER_AXIS_INVALID,
    RENDER_GRID_IDENTITY_MISMATCH,
    RENDER_GRID_IRREGULAR,
    RENDER_GRID_SHAPE_MISMATCH,
    RENDER_NO_VALID_VALUES,
    RENDER_REQUIRES_3D,
    create_render_asset,
    resolve_candidate_render_source,
)
from geomodeling.platform.render_contracts import RenderGridSource
from geomodeling.platform.results import RESULT_NOT_MATERIALIZED, materialize
from test_api import FakeIServer, make_config
from test_gas_preset_contract import GAS_SOURCE_SHA256
from test_public_dto import assert_no_path_leak
from test_render_source_resolution import insert_candidate_chain

#: 冻结基线网格合同（config/presets/gas-official-baseline.json，逐轴恰为源坐标范围）
REAL_BOUNDS = [[1023.802, 4016.788], [1049.716, 7688.731], [121.0375, 175.656]]
REAL_GRID_SHAPE = [151, 333, 12]
REAL_GRID_CELLS = 151 * 333 * 12
DECLARED_RESOLUTION = [20.0, 20.0, 5.0]
#: 不可整除口径的实际回算分辨率（round((hi-lo)/step)+1 节点；实测锁定值）
ACTUAL_RESOLUTION = [19.953239999999997, 19.99703313253012, 4.965318181818183]

#: 冻结 winner（ordinary_kriging spherical/24）
WINNER_ALGORITHM = "ordinary_kriging"
WINNER_PARAMETERS = {"neighbor_count": 24, "variogram_model": "spherical"}

#: 2026-08-09 实测物化值域（确定性：同源同算法同网格）；跨平台以 rel 容差锁定
MEASURED_VALUE_RANGE = [1.5409142384731545, 30.278859961829596]

PACKAGE_FILES = {"volume.nc", "manifest.json", "checksums.sha256"}

#: 失败态合成网格的瓦斯量级规则轴（4×5×3，秒级）
_GAS_AXES = (
    np.linspace(1023.802, 4016.788, 4),
    np.linspace(1049.716, 7688.731, 5),
    np.linspace(121.0375, 175.656, 3),
)
_GAS_SHAPE = (4, 5, 3)


# ---------------------------------------------------------------------------
# 夹具：真实 seed（模块级共享，≈145s 物化成本只付一次）
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def gas_runtime(tmp_path_factory):
    runtime = PlatformRuntime(tmp_path_factory.mktemp("gas-render-asset") / "runtime")
    runtime.initialize()
    yield runtime
    runtime.close()


@pytest.fixture(scope="module")
def seeded(gas_runtime):
    """真实内置源 + 真实冻结基线的官方 seed（默认参数即生产入口）。

    实测总耗时 ≈145s（5 折空间 CV + 603k 节点 kriging 物化），在计划
    允许的 1–3 分钟窗口内；模块级共享，绝不重复 seed。
    """

    record = seed_gas_preset(gas_runtime)
    assert record.case_id == PRESET_CASE_ID == "gas"
    assert record.workspace_kind == "builtin_preset"
    assert record.official_result.materialized is True
    return record


def _make_app_client(runtime, tmp_path: Path) -> TestClient:
    """完整应用 + 注入已 seed 的运行库（不跑 lifespan；同 test_gas_preset_seed 模式）。"""

    fixture_csv = Path("tests/fixtures/rho_tiny_validation.csv").resolve()
    config = make_config(standardized=fixture_csv)
    settings = ApiSettings(
        config_path=Path("config/default.yaml"),
        metrics_json=(tmp_path / "m.json"),
        evidence_dir=tmp_path / "evidence",
        frontend_dist=None,
        voxel_cache_dir=tmp_path / "cache",
    )
    (tmp_path / "m.json").write_text('{"summaries": {}}', encoding="utf-8")
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_app_config] = lambda: config
    app.dependency_overrides[get_iserver_client] = lambda: FakeIServer({})
    app.state.platform_runtime = runtime
    return TestClient(app)


@pytest.fixture(scope="module")
def client(gas_runtime, seeded, tmp_path_factory):
    return _make_app_client(gas_runtime, tmp_path_factory.mktemp("gas-render-app"))


@pytest.fixture(scope="module")
def render_asset(client, seeded) -> dict:
    """首建 NetCDF 渲染资产（201 语义锁定在夹具内）；模块级共享同一资产。"""

    result_id = seeded.official_result.result_id
    resp = client.post(f"/api/results/{result_id}/render-assets/netcdf")
    assert resp.status_code == 201, resp.text
    record = resp.json()
    assert record["status"] == "ready"
    return record


def _result_metadata(runtime, result_id: str) -> dict:
    grid_path = runtime.settings.result_grid(result_id)
    return json.loads((grid_path.parent / "metadata.json").read_text(encoding="utf-8"))


def _png(width: int = 8, height: int = 8) -> bytes:
    """最小合法 PNG（同 test_slice_exports._png 构造；复制以避免跨文件循环导入）。"""

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


# ---------------------------------------------------------------------------
# 物化：官方规则网格与结果级 metadata 合同
# ---------------------------------------------------------------------------


def test_official_grid_npz_shape_axes_and_nodata_policy(gas_runtime, seeded):
    result_id = seeded.official_result.result_id
    grid_path = gas_runtime.settings.result_grid(result_id)
    metadata = _result_metadata(gas_runtime, result_id)

    # 冻结基线网格合同：bounds 逐轴恰为瓦斯数据 bounds（绝不外推）
    assert metadata["dimension"] == "3d"
    assert metadata["shape"] == REAL_GRID_SHAPE
    assert metadata["cell_count"] == REAL_GRID_CELLS == 603_396
    assert metadata["bounds"] == REAL_BOUNDS
    assert metadata["resolution"] == pytest.approx(DECLARED_RESOLUTION, abs=0.05)
    # 实际回算分辨率精确锁定（不可整除口径）
    assert metadata["resolution"] == pytest.approx(ACTUAL_RESOLUTION, rel=1e-9)

    with np.load(grid_path, allow_pickle=True) as bundle:
        axes = tuple(np.asarray(a, dtype="float64") for a in bundle["axes"])
        values = np.asarray(bundle["values"], dtype="float64")
        is_nodata = np.asarray(bundle["is_nodata"], dtype=bool)

    assert values.shape == tuple(REAL_GRID_SHAPE)
    assert is_nodata.shape == tuple(REAL_GRID_SHAPE)
    assert [axis.size for axis in axes] == REAL_GRID_SHAPE
    for axis, (lo, hi) in zip(axes, REAL_BOUNDS, strict=True):
        assert axis[0] == pytest.approx(lo)
        assert axis[-1] == pytest.approx(hi)
        assert np.all(np.diff(axis) > 0)

    # 值全部有限；观测包围盒即网格范围（盒外无节点），盒内零 NoData（实测锁定）
    assert np.isfinite(values).all()
    assert int(is_nodata.sum()) == metadata["nodata_count"] == 0
    assert metadata["value_range"] == pytest.approx(MEASURED_VALUE_RANGE, rel=1e-6)

    # 网格身份：登记哈希 == 实际文件哈希
    assert metadata["grid_sha256"] == hashlib.sha256(grid_path.read_bytes()).hexdigest()


def test_materialized_metadata_identity_chain(gas_runtime, seeded):
    result_id = seeded.official_result.result_id
    metadata = _result_metadata(gas_runtime, result_id)

    # 算法与确认参数（冻结 winner ordinary_kriging spherical/24）
    assert metadata["algorithm"] == WINNER_ALGORITHM
    assert metadata["parameters"] == WINNER_PARAMETERS
    # 源 SHA / 标准化数据版本指纹 / 候选指纹
    assert metadata["source_sha256"] == GAS_SOURCE_SHA256
    assert len(metadata["standardized_sha256"]) == 64
    assert len(metadata["fingerprint"]) == 64
    # 归属链 result → run → experiment → dataset
    assert metadata["result_id"] == result_id
    assert metadata["run_id"] == seeded.run_id
    assert metadata["experiment_id"] == seeded.experiment_id
    assert metadata["dataset_version_id"] == seeded.dataset_version_id
    assert metadata["validation"] == dict(VALIDATION_CONTRACT)
    # 渲染 property 语义三键（通用 profile 映射：CH4_content / ml/g / local_linear）
    assert metadata["property_name"] == "CH4_content"
    assert metadata["units"] == "ml/g"
    assert metadata["coordinate_kind"] == "local_linear"

    # DB 归属链复核（官方候选挂在官方 run/experiment/案例上）
    with gas_runtime.session() as session:
        candidate = session.get(tables.CandidateResult, result_id)
        assert candidate.status == "succeeded"
        assert candidate.run_id == seeded.run_id
        run = session.get(tables.Run, seeded.run_id)
        assert run.experiment_id == seeded.experiment_id
        experiment = session.get(tables.Experiment, seeded.experiment_id)
        assert experiment.case_id == PRESET_CASE_ID
        dataset = session.get(tables.DatasetVersion, seeded.dataset_version_id)
        assert dataset.case_id == PRESET_CASE_ID
        assert dataset.status == "validated"


def test_materialize_is_idempotent_without_rewrite(gas_runtime, seeded):
    result_id = seeded.official_result.result_id
    grid_path = gas_runtime.settings.result_grid(result_id)
    mtime = grid_path.stat().st_mtime_ns
    metadata = materialize(gas_runtime, result_id)
    assert metadata["shape"] == REAL_GRID_SHAPE
    assert metadata["algorithm"] == WINNER_ALGORITHM
    assert grid_path.stat().st_mtime_ns == mtime  # 幂等重读，绝不重算重写


# ---------------------------------------------------------------------------
# 渲染能力：display_anchor 坐标合同
# ---------------------------------------------------------------------------


def test_render_capability_supported_with_display_anchor_contract(client, seeded):
    result_id = seeded.official_result.result_id
    resp = client.get(f"/api/results/{result_id}/render-capability")
    assert resp.status_code == 200, resp.text
    capability = resp.json()
    assert capability["source_kind"] == "candidate_result"
    assert capability["source_id"] == result_id
    assert capability["supported"] is True
    assert capability["reason_code"] is None
    assert capability["reason"] is None
    assert capability["dimension"] == "3d"
    assert capability["grid_kind"] == "regular"
    assert capability["property_name"] == "CH4_content"
    assert capability["units"] == "ml/g"
    assert capability["geolocation_status"] == "display_anchor_only"

    # 坐标类型：wgs84_display_anchor_v1（局部米制 → 固定显示锚点，绝非真实配准）
    transform = capability["display_transform"]
    assert transform["contract"] == "wgs84_display_anchor_v1"
    assert transform["origin_x"] == pytest.approx(
        (REAL_BOUNDS[0][0] + REAL_BOUNDS[0][1]) / 2
    )
    assert transform["origin_y"] == pytest.approx(
        (REAL_BOUNDS[1][0] + REAL_BOUNDS[1][1]) / 2
    )
    assert transform["anchor_longitude"] == 120.0
    assert transform["anchor_latitude"] == 30.0

    profile = capability["render_profile"]
    assert profile["property_name"] == "CH4_content"
    assert profile["unit"] == "ml/g"
    assert profile["default_scale"] == "linear"
    assert profile["default_palette"] == "viridis"
    assert profile["value_range"] == pytest.approx(MEASURED_VALUE_RANGE, rel=1e-6)
    assert profile["log_available"] is True  # 实测有效值域全正
    assert profile["filter_range"] == profile["value_range"]
    assert_no_path_leak(capability, "$.gas_capability")


# ---------------------------------------------------------------------------
# NetCDF 渲染资产：201 首建 / 200 幂等 / manifest / volume.nc
# ---------------------------------------------------------------------------


def test_post_creates_ready_asset_201_with_candidate_identity(render_asset, seeded):
    # 首建 201 语义锁定在 render_asset 夹具内；此处锁定记录身份合同
    assert render_asset["id"].startswith("nc-") and len(render_asset["id"]) == 35
    assert render_asset["source_kind"] == "candidate_result"
    assert render_asset["source_id"] == seeded.official_result.result_id
    assert render_asset["renderer"] == "supermap_voxelgrid_netcdf"
    assert len(render_asset["grid_sha256"]) == 64
    assert len(render_asset["netcdf_sha256"]) == 64
    assert render_asset["manifest_url"] == (
        f"/api/render-assets/{render_asset['id']}/manifest"
    )
    assert render_asset["netcdf_url"] == (
        f"/api/render-assets/{render_asset['id']}/volume.nc"
    )
    assert render_asset["error"] is None
    assert "asset_dir" not in render_asset
    assert_no_path_leak(render_asset, "$.gas_asset")


def test_repeated_post_returns_same_asset_200(client, gas_runtime, render_asset, seeded):
    result_id = seeded.official_result.result_id
    package_dir = gas_runtime.settings.render_assets_dir / render_asset["id"]
    assert {p.name for p in package_dir.iterdir()} == PACKAGE_FILES
    volume_path = package_dir / "volume.nc"
    assert volume_path.read_bytes()[:4] == b"CDF\x01"
    mtime = volume_path.stat().st_mtime_ns

    second = client.post(f"/api/results/{result_id}/render-assets/netcdf", json={})
    assert second.status_code == 200, second.text
    assert second.json() == render_asset  # 幂等复用同资产同 SHA
    assert volume_path.stat().st_mtime_ns == mtime  # 绝不重写


def test_netcdf_manifest_identity_axes_units_and_display_anchor(
    client, gas_runtime, seeded, render_asset
):
    metadata = _result_metadata(gas_runtime, seeded.official_result.result_id)
    resp = client.get(f"/api/render-assets/{render_asset['id']}/manifest")
    assert resp.status_code == 200, resp.text
    manifest = resp.json()
    assert manifest["format"] == "supermap-voxel-netcdf"
    assert manifest["version"] == 2
    assert manifest["renderer"] == "supermap_voxelgrid_netcdf"

    # 来源身份与双哈希一致（资产 → 官方候选 → 物化网格）
    assert manifest["source_kind"] == "candidate_result"
    assert manifest["source_id"] == seeded.official_result.result_id
    assert manifest["grid_sha256"] == render_asset["grid_sha256"] == metadata["grid_sha256"]
    assert manifest["netcdf_sha256"] == render_asset["netcdf_sha256"]

    # 三轴长度 / 变量名 / 单位
    assert manifest["dimension_names"] == ["x", "y", "z"]
    assert manifest["shape"] == REAL_GRID_SHAPE
    assert manifest["variable_name"] == "CH4_content"
    assert manifest["property_name"] == "CH4_content"
    assert manifest["units"] == "ml/g"

    # 坐标类型：wgs84_display_anchor_v1 合同（显示锚点，绝非真实配准）
    assert manifest["render_coordinate_contract"] == "wgs84_display_anchor_v1"
    assert manifest["geolocation_status"] == "display_anchor_only"
    transform = manifest["display_transform"]
    assert transform["contract"] == "wgs84_display_anchor_v1"
    assert transform["origin_x"] == pytest.approx(2520.295)
    assert transform["origin_y"] == pytest.approx(4369.2235)
    degrees = manifest["layer_bounds_degrees"]
    assert 119.0 < degrees["west"] < 120.0 < degrees["east"] < 121.0
    assert 29.0 < degrees["south"] < 30.0 < degrees["north"] < 31.0
    assert manifest["z_bounds_metres"] == pytest.approx(REAL_BOUNDS[2])

    # 统计与值域（实测：603,396 体元全部有效）
    assert manifest["valid_count"] == REAL_GRID_CELLS
    assert manifest["nodata_count"] == 0
    assert manifest["value_range"] == pytest.approx(MEASURED_VALUE_RANGE, rel=1e-6)
    assert manifest["sdk_target"]
    assert_no_path_leak(manifest, "$.gas_manifest")


def test_volume_nc_served_with_identity_headers(client, render_asset):
    resp = client.get(f"/api/render-assets/{render_asset['id']}/volume.nc")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/x-netcdf"
    assert resp.headers["etag"] == f'"sha256-{render_asset["netcdf_sha256"]}"'
    assert resp.headers["cache-control"] == "public, immutable"
    assert resp.content[:4] == b"CDF\x01"
    assert hashlib.sha256(resp.content).hexdigest() == render_asset["netcdf_sha256"]


# ---------------------------------------------------------------------------
# 剖面分析：X/Y/Z 三轴真实米制坐标标签
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("axis,index", [("x", 75), ("y", 166), ("z", 6)])
def test_slice_analysis_three_axes_real_metric_labels(
    client, seeded, render_asset, axis, index
):
    resp = client.get(
        f"/api/render-assets/{render_asset['id']}/slice-analysis",
        params={"axis": axis, "index": index},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    identity = body["asset_identity"]
    assert identity["asset_id"] == render_asset["id"]
    assert identity["source_kind"] == "candidate_result"
    assert identity["source_id"] == seeded.official_result.result_id
    assert identity["grid_sha256"] == render_asset["grid_sha256"]
    assert identity["netcdf_sha256"] == render_asset["netcdf_sha256"]
    assert body["property"] == {"name": "CH4_content", "unit": "ml/g"}

    # 三轴坐标标签为真实米制值（局部米制轴，绝非显示经纬度）
    for name, length, (lo, hi) in zip(
        ("x", "y", "z"), REAL_GRID_SHAPE, REAL_BOUNDS, strict=True
    ):
        info = body["axes"][name]
        assert info["length"] == length
        assert info["unit"] == "m"
        coords = info["coordinates"]
        assert coords[0] == pytest.approx(lo)
        assert coords[-1] == pytest.approx(hi)
        assert all(b > a for a, b in zip(coords, coords[1:]))

    plane = body["slice"]
    assert plane["fixed_axis"] == axis
    assert plane["index"] == index
    lo, hi = REAL_BOUNDS["xyz".index(axis)]
    assert lo <= plane["coordinate"] <= hi
    assert len(plane["values"]) == len(plane["row_coordinates"])
    assert len(plane["values"][0]) == len(plane["column_coordinates"])

    stats = body["statistics"]
    assert stats["valid_count"] > 0
    assert stats["valid_count"] + stats["nodata_count"] == stats["total_count"]
    assert stats["min"] <= stats["p50"] <= stats["max"]
    assert_no_path_leak(body, "$.gas_slice")


# ---------------------------------------------------------------------------
# 剖面导出：ZIP 含剖面证据（CSV/统计/manifest/PNG）
# ---------------------------------------------------------------------------


def test_slice_export_zip_contains_profile_evidence(client, seeded, render_asset):
    resp = client.post(
        f"/api/render-assets/{render_asset['id']}/slice-exports",
        files={
            "axis": (None, "z"),
            "index": (None, "6"),
            "image": ("slice.png", _png(), "image/png"),
        },
    )
    assert resp.status_code == 201, resp.text
    export = resp.json()
    assert export["case_id"] == PRESET_CASE_ID
    assert export["candidate_result_id"] == seeded.official_result.result_id

    download = client.get(f"/api/exports/{export['id']}/download")
    assert download.status_code == 200, download.text
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
    assert len(lines) == 333 * 151 + 1  # z 剖面全体元行（row=y × column=x）

    stats = json.loads(archive.read("statistics.json"))
    analysis = client.get(
        f"/api/render-assets/{render_asset['id']}/slice-analysis",
        params={"axis": "z", "index": 6},
    ).json()
    assert stats == analysis["statistics"]  # 服务端权威重算，同一统计合同
    assert stats["valid_count"] > 0

    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["format_version"] == "slice-analysis/v1"
    assert manifest["export_kind"] == "slice_analysis"
    assert manifest["image_provenance"] == "client_echarts_canvas"
    assert manifest["property"] == {"name": "CH4_content", "unit": "ml/g"}
    identity = manifest["asset_identity"]
    assert identity["asset_id"] == render_asset["id"]
    assert identity["source_kind"] == "candidate_result"
    assert identity["source_id"] == seeded.official_result.result_id
    assert identity["grid_sha256"] == render_asset["grid_sha256"]
    assert identity["netcdf_sha256"] == render_asset["netcdf_sha256"]
    assert manifest["axes"] == {
        "x": {"length": 151},
        "y": {"length": 333},
        "z": {"length": 12},
    }
    assert manifest["slice"]["fixed_axis"] == "z"
    assert manifest["slice"]["index"] == 6
    assert manifest["slice"]["coordinate"] == pytest.approx(analysis["slice"]["coordinate"])
    assert_no_path_leak(manifest, "$.gas_slice_export")


# ---------------------------------------------------------------------------
# 失败态锁定：缺失/非有限/超 bounds 类型化错误；空资产绝不标 ready
#
# 通用链（render_assets.validate_regular_grid / create_render_asset /
# slice_analysis）对瓦斯量级网格同样 fail-closed；以下合成网格复用瓦斯
# 坐标量级，作为回归锁定保留。
# ---------------------------------------------------------------------------


@pytest.fixture()
def fresh_runtime(tmp_path: Path):
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    yield runtime
    runtime.close()


def _write_synthetic_grid(path: Path, axes, values, is_nodata) -> str:
    np.savez_compressed(
        path, axes=np.array(axes, dtype=object), values=values, is_nodata=is_nodata
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _synthetic_gas_source(
    grid_path: Path, sha256: str, source_id: str = "synthetic-gas-grid"
) -> RenderGridSource:
    return RenderGridSource(
        source_kind="candidate_result",
        source_id=source_id,
        grid_path=grid_path,
        grid_sha256=sha256,
        property_name="CH4_content",
        units="ml/g",
        coordinate_kind="local_linear",
        dimension="3d",
    )


def _asset_rows(runtime) -> list:
    with runtime.session() as session:
        return session.query(tables.RenderAsset).all()


def _asset_dir_listing(runtime) -> list[str]:
    assets_dir = runtime.settings.render_assets_dir
    if not assets_dir.exists():
        return []
    return sorted(p.name for p in assets_dir.iterdir())


def test_all_nodata_grid_fails_closed_and_never_marks_ready(fresh_runtime, tmp_path):
    grid_path = tmp_path / "grid.npz"
    sha = _write_synthetic_grid(
        grid_path,
        _GAS_AXES,
        np.full(_GAS_SHAPE, np.nan),
        np.ones(_GAS_SHAPE, dtype=bool),
    )
    with pytest.raises(PlatformError) as excinfo:
        create_render_asset(fresh_runtime, _synthetic_gas_source(grid_path, sha))
    assert excinfo.value.code == RENDER_NO_VALID_VALUES
    assert excinfo.value.http_status == 409
    # 网格校验先于认领：空资产绝不留行、绝不标 ready、绝不留目录
    assert _asset_rows(fresh_runtime) == []
    assert _asset_dir_listing(fresh_runtime) == []


def test_nonfinite_values_grid_fails_closed(fresh_runtime, tmp_path):
    """未标 NoData 的全 NaN 值（非有限输入）同样 fail-closed，绝不留行。"""

    grid_path = tmp_path / "grid.npz"
    sha = _write_synthetic_grid(
        grid_path,
        _GAS_AXES,
        np.full(_GAS_SHAPE, np.nan),
        np.zeros(_GAS_SHAPE, dtype=bool),
    )
    with pytest.raises(PlatformError) as excinfo:
        create_render_asset(fresh_runtime, _synthetic_gas_source(grid_path, sha))
    assert excinfo.value.code == RENDER_NO_VALID_VALUES
    assert _asset_rows(fresh_runtime) == []
    assert _asset_dir_listing(fresh_runtime) == []


def test_nonfinite_axis_fails_closed(fresh_runtime, tmp_path):
    grid_path = tmp_path / "grid.npz"
    axes = (
        np.array([1023.802, np.nan, 3000.0, 4016.788]),
        _GAS_AXES[1],
        _GAS_AXES[2],
    )
    sha = _write_synthetic_grid(
        grid_path, axes, np.ones(_GAS_SHAPE), np.zeros(_GAS_SHAPE, dtype=bool)
    )
    with pytest.raises(PlatformError) as excinfo:
        create_render_asset(fresh_runtime, _synthetic_gas_source(grid_path, sha))
    assert excinfo.value.code == RENDER_AXIS_INVALID
    assert _asset_rows(fresh_runtime) == []


def test_irregular_axis_fails_closed(fresh_runtime, tmp_path):
    grid_path = tmp_path / "grid.npz"
    axes = (
        np.array([1023.802, 1500.0, 1501.0, 4016.788]),  # 非等距
        _GAS_AXES[1],
        _GAS_AXES[2],
    )
    sha = _write_synthetic_grid(
        grid_path, axes, np.ones(_GAS_SHAPE), np.zeros(_GAS_SHAPE, dtype=bool)
    )
    with pytest.raises(PlatformError) as excinfo:
        create_render_asset(fresh_runtime, _synthetic_gas_source(grid_path, sha))
    assert excinfo.value.code == RENDER_GRID_IRREGULAR
    assert _asset_rows(fresh_runtime) == []


def test_shape_mismatch_fails_closed(fresh_runtime, tmp_path):
    grid_path = tmp_path / "grid.npz"
    sha = _write_synthetic_grid(
        grid_path,
        _GAS_AXES,
        np.ones((4, 5, 4)),  # 与轴长度 (4,5,3) 不符
        np.zeros((4, 5, 4), dtype=bool),
    )
    with pytest.raises(PlatformError) as excinfo:
        create_render_asset(fresh_runtime, _synthetic_gas_source(grid_path, sha))
    assert excinfo.value.code == RENDER_GRID_SHAPE_MISMATCH
    assert _asset_rows(fresh_runtime) == []


def test_grid_identity_mismatch_fails_closed(fresh_runtime, tmp_path):
    """登记哈希与实际文件哈希不符（缺失/篡改输入）fail-closed。"""

    grid_path = tmp_path / "grid.npz"
    _write_synthetic_grid(
        grid_path, _GAS_AXES, np.ones(_GAS_SHAPE), np.zeros(_GAS_SHAPE, dtype=bool)
    )
    with pytest.raises(PlatformError) as excinfo:
        create_render_asset(fresh_runtime, _synthetic_gas_source(grid_path, "0" * 64))
    assert excinfo.value.code == RENDER_GRID_IDENTITY_MISMATCH
    assert _asset_rows(fresh_runtime) == []


def test_2d_grid_fails_closed(fresh_runtime, tmp_path):
    grid_path = tmp_path / "grid.npz"
    axes_2d = (_GAS_AXES[0], _GAS_AXES[1])
    sha = _write_synthetic_grid(
        grid_path, axes_2d, np.ones((4, 5)), np.zeros((4, 5), dtype=bool)
    )
    with pytest.raises(PlatformError) as excinfo:
        create_render_asset(fresh_runtime, _synthetic_gas_source(grid_path, sha))
    assert excinfo.value.code == RENDER_REQUIRES_3D
    assert _asset_rows(fresh_runtime) == []


def test_writer_failure_marks_failed_never_ready(fresh_runtime, tmp_path, monkeypatch):
    """认领后写包失败：行落 failed（绝不 ready），stage 全清理。

    render_assets.candidate_result_id 外键要求真实候选行，故先落库最小
    归属链（同 test_render_asset_publication 的既有模式）。
    """

    candidate_id = insert_candidate_chain(fresh_runtime)
    grid_path = tmp_path / "grid.npz"
    sha = _write_synthetic_grid(
        grid_path, _GAS_AXES, np.ones(_GAS_SHAPE), np.zeros(_GAS_SHAPE, dtype=bool)
    )

    def broken_writer(*_args, **_kwargs):
        raise PlatformError(
            "RENDER_NETCDF_WRITE_FAILED", "写入失败", http_status=500
        )

    monkeypatch.setattr(render_assets, "write_netcdf_package", broken_writer)
    with pytest.raises(PlatformError) as excinfo:
        create_render_asset(
            fresh_runtime, _synthetic_gas_source(grid_path, sha, candidate_id)
        )
    assert excinfo.value.code == "RENDER_NETCDF_WRITE_FAILED"

    rows = _asset_rows(fresh_runtime)
    assert len(rows) == 1
    assert rows[0].status == "failed"
    assert rows[0].candidate_result_id == candidate_id
    assert tables.loads_canonical(rows[0].error_json)["code"] == (
        "RENDER_NETCDF_WRITE_FAILED"
    )
    assert _asset_dir_listing(fresh_runtime) == []


def test_slice_analysis_typed_errors_on_gas_asset(client, render_asset):
    """超 bounds/非法轴输入 → 422 类型化错误（真实瓦斯资产）。"""

    # z 轴长度 12：index 12 超 bounds
    resp = client.get(
        f"/api/render-assets/{render_asset['id']}/slice-analysis",
        params={"axis": "z", "index": 12},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "SLICE_INDEX_OUT_OF_RANGE"

    resp = client.get(
        f"/api/render-assets/{render_asset['id']}/slice-analysis",
        params={"axis": "w", "index": 0},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "SLICE_AXIS_INVALID"

    # 导出同一口径：超 bounds 索引 422，绝不产生剖面证据包
    resp = client.post(
        f"/api/render-assets/{render_asset['id']}/slice-exports",
        files={
            "axis": (None, "z"),
            "index": (None, "12"),
            "image": ("slice.png", _png(), "image/png"),
        },
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "SLICE_INDEX_OUT_OF_RANGE"


# ---------------------------------------------------------------------------
# 缺失输入：未物化候选 fail-closed（绝不隐式物化）
# ---------------------------------------------------------------------------


def _build_unmaterialized_user_candidate(runtime) -> str:
    """官方案例上的用户实验成功候选（默认小网格参数，仅过 CV，绝不物化）。"""

    with runtime.session() as session:
        dataset_id = (
            session.query(tables.DatasetVersion)
            .filter(tables.DatasetVersion.case_id == PRESET_CASE_ID)
            .one()
            .id
        )
    experiment_id = f"gas-user-exp-{uuid.uuid4().hex[:8]}"
    run_id = f"gas-user-run-{uuid.uuid4().hex[:8]}"
    params = {
        "algorithm": "idw",
        "dataset_version_id": dataset_id,
        "search_mode": "manual",
        "parameters": {"power": 2.0, "neighbor_count": 8},
        "validation": {"method": "spatial_kfold", "folds": 3, "seed": 11},
        "grid": None,
    }
    with runtime.session() as session:
        session.add(
            tables.Experiment(
                id=experiment_id,
                case_id=PRESET_CASE_ID,
                name="未物化用户实验",
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


def test_unmaterialized_candidate_render_source_fails_closed(gas_runtime, seeded):
    candidate_id = _build_unmaterialized_user_candidate(gas_runtime)
    with pytest.raises(PlatformError) as excinfo:
        resolve_candidate_render_source(gas_runtime, candidate_id)
    assert excinfo.value.code == RESULT_NOT_MATERIALIZED
    assert excinfo.value.http_status == 404
    # 纯查询绝不隐式物化
    assert not gas_runtime.settings.result_grid(candidate_id).exists()


def test_unmaterialized_candidate_capability_unsupported(client, gas_runtime, seeded):
    candidate_id = _build_unmaterialized_user_candidate(gas_runtime)
    resp = client.get(f"/api/results/{candidate_id}/render-capability")
    assert resp.status_code == 200, resp.text
    capability = resp.json()
    assert capability["source_kind"] == "candidate_result"
    assert capability["source_id"] == candidate_id
    assert capability["supported"] is False
    assert capability["reason_code"] == RESULT_NOT_MATERIALIZED
    assert capability["display_transform"] is None
    assert capability["render_profile"] is None
    # 语义尽力回填来自瓦斯数据集 profile（不固定 rho 语义）
    assert capability["property_name"] == "CH4_content"
    assert capability["units"] == "ml/g"
    assert not gas_runtime.settings.result_grid(candidate_id).exists()
