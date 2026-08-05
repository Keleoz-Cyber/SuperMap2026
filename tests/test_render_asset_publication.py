"""v0.6.1 Task 6: atomic publication of deterministic NetCDF render assets.

``create_render_asset`` 的原子语义：stage 目录（render-assets/ 下隐藏
``.{asset_id}-*``）写齐 + fsync 之前 final 目录绝不可见；``os.replace`` 单点
发布，DB 在 rename 前绝不 ready；任何失败清理 stage 并 ``mark_failed``（清理
异常绝不覆盖业务异常）；ready 行幂等复用同资产同 SHA；既存 final 目录按期望
身份核验——有效复用、无效原子隔离为 ``<asset-id>.corrupt-<uuid>``（损坏证据
绝不自动删除）。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

import geomodeling.platform.render_assets as render_assets
from geomodeling.platform import tables
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.render_assets import (
    create_render_asset,
    resolve_candidate_render_source,
    verify_ready_asset,
)
from geomodeling.platform.repositories import RenderAssetRepository
from geomodeling.platform.schemas import render_asset_id
from test_experiment_runner import make_runtime
from test_render_source_resolution import (
    insert_candidate_chain,
    regular_artifact,
    write_grid_artifact,
)

PACKAGE_FILES = {"volume.nc", "manifest.json", "checksums.sha256"}


def build_source(runtime):
    """真实归属链 + 手工网格工件 → 解析出的候选渲染源（Vx / km/s，含 1 个 NoData）。"""

    candidate_id = insert_candidate_chain(runtime)
    axes, values, is_nodata = regular_artifact()
    is_nodata = is_nodata.copy()
    is_nodata[1, 1, 1] = True
    write_grid_artifact(runtime, candidate_id, axes=axes, values=values, is_nodata=is_nodata)
    return candidate_id, resolve_candidate_render_source(runtime, candidate_id)


def asset_id_of(source) -> str:
    return render_asset_id(
        source_kind=source.source_kind,
        source_id=source.source_id,
        grid_sha256=source.grid_sha256,
    )


def load_row(runtime, asset_id: str):
    with runtime.session() as session:
        row = session.get(tables.RenderAsset, asset_id)
        assert row is not None, f"render asset {asset_id} not persisted"
        session.expunge(row)
        return row


def final_dir_of(runtime, asset_id: str) -> Path:
    return runtime.settings.render_assets_dir / asset_id


def stage_dirs(runtime, asset_id: str) -> list[Path]:
    return list(runtime.settings.render_assets_dir.glob(f".{asset_id}-*"))


def flip_row_to_interrupted(runtime, asset_id: str) -> None:
    """模拟启动恢复写入：rename 成功后崩溃，creating 行被翻为 interrupted。"""

    with runtime.session() as session:
        row = session.get(tables.RenderAsset, asset_id)
        row.status = "interrupted"
        row.netcdf_sha256 = None
        row.asset_dir = None
        row.manifest_json = "{}"
        session.commit()


def read_checksums(package_dir: Path) -> dict[str, str]:
    lines = (package_dir / "checksums.sha256").read_text(encoding="utf-8").strip().splitlines()
    return dict(line.split("  ", 1)[::-1] for line in lines)


# ---------------------------------------------------------------------------
# happy path：ready 行永远指向完整 manifest + volume.nc + checksums.sha256
# ---------------------------------------------------------------------------


def test_create_publishes_complete_ready_asset(tmp_path):
    runtime = make_runtime(tmp_path)
    candidate_id, source = build_source(runtime)

    record, created = create_render_asset(runtime, source, retry_failed=False)

    assert created is True
    asset_id = asset_id_of(source)
    assert record.id == asset_id
    assert record.status == "ready"
    assert record.netcdf_sha256 is not None and len(record.netcdf_sha256) == 64
    assert record.manifest_url == f"/api/render-assets/{asset_id}/manifest"
    assert record.netcdf_url == f"/api/render-assets/{asset_id}/volume.nc"
    assert record.error is None

    final_dir = final_dir_of(runtime, asset_id)
    assert {p.name for p in final_dir.iterdir()} == PACKAGE_FILES
    assert (final_dir / "volume.nc").read_bytes()[:4] == b"CDF\x01"
    assert (
        hashlib.sha256((final_dir / "volume.nc").read_bytes()).hexdigest()
        == record.netcdf_sha256
    )

    row = load_row(runtime, asset_id)
    assert row.status == "ready"
    assert row.asset_dir is not None and not os.path.isabs(row.asset_dir)
    manifest = json.loads(row.manifest_json)
    assert manifest["format"] == "supermap-voxel-netcdf"
    assert manifest["version"] == 2
    assert manifest["renderer"] == "supermap_voxelgrid_netcdf"
    assert manifest["source_kind"] == "candidate_result"
    assert manifest["source_id"] == candidate_id
    assert manifest["property_name"] == "Vx"
    assert manifest["units"] == "km/s"
    assert manifest["netcdf_sha256"] == record.netcdf_sha256
    assert manifest["nodata_count"] == 1
    assert manifest["sdk_target"] == "SuperMap3D 12.1.0"

    assert read_checksums(final_dir) == {
        "volume.nc": record.netcdf_sha256,
        "manifest.json": hashlib.sha256(
            (final_dir / "manifest.json").read_bytes()
        ).hexdigest(),
    }
    assert stage_dirs(runtime, asset_id) == []


# ---------------------------------------------------------------------------
# 原子可见性：rename 前 final 目录不可见、DB 绝不提前 ready
# ---------------------------------------------------------------------------


def test_no_final_dir_before_rename_and_db_ready_only_after(tmp_path, monkeypatch):
    runtime = make_runtime(tmp_path)
    _, source = build_source(runtime)
    asset_id = asset_id_of(source)
    final_dir = final_dir_of(runtime, asset_id)

    real_writer = render_assets.write_netcdf_package
    real_fsync = render_assets.fsync_tree
    real_replace = os.replace
    observed: dict[str, object] = {"writer": None, "fsync": None, "rename_status": []}

    def spy_writer(stage_dir, src, grid, anchor):
        observed["writer"] = final_dir.exists()
        return real_writer(stage_dir, src, grid, anchor)

    def spy_fsync(stage_dir):
        observed["fsync"] = final_dir.exists()
        return real_fsync(stage_dir)

    def spy_replace(src, dst):
        observed["rename_status"].append(load_row(runtime, asset_id).status)
        return real_replace(src, dst)

    monkeypatch.setattr(render_assets, "write_netcdf_package", spy_writer)
    monkeypatch.setattr(render_assets, "fsync_tree", spy_fsync)
    monkeypatch.setattr(os, "replace", spy_replace)

    record, created = create_render_asset(runtime, source, retry_failed=False)

    assert created is True and record.status == "ready"
    assert observed["writer"] is False  # 写入期 final 目录不可见
    assert observed["fsync"] is False  # fsync 期 final 目录仍不可见
    assert observed["rename_status"] == ["creating"]  # rename 前 DB 绝未 ready
    assert load_row(runtime, asset_id).status == "ready"
    assert final_dir.is_dir()


# ---------------------------------------------------------------------------
# 失败边界：stage 清理 + mark_failed + 业务异常不被覆盖
# ---------------------------------------------------------------------------


def test_writer_failure_removes_stage_and_marks_failed(tmp_path, monkeypatch):
    runtime = make_runtime(tmp_path)
    _, source = build_source(runtime)
    asset_id = asset_id_of(source)

    def broken_writer(stage_dir, *_args, **_kwargs):
        stage_dir.mkdir(parents=True, exist_ok=True)
        (stage_dir / "volume.nc").write_bytes(b"partial")
        raise PlatformError(
            "RENDER_NETCDF_WRITE_FAILED", "写入失败", {"stage": "write"}, http_status=500
        )

    monkeypatch.setattr(render_assets, "write_netcdf_package", broken_writer)

    with pytest.raises(PlatformError) as excinfo:
        create_render_asset(runtime, source, retry_failed=False)
    assert excinfo.value.code == "RENDER_NETCDF_WRITE_FAILED"

    assert stage_dirs(runtime, asset_id) == []  # 失败 stage 已清理
    assert not final_dir_of(runtime, asset_id).exists()
    row = load_row(runtime, asset_id)
    assert row.status == "failed"
    assert row.netcdf_sha256 is None
    error = tables.loads_canonical(row.error_json)
    assert error["code"] == "RENDER_NETCDF_WRITE_FAILED"


def test_fsync_failure_cleans_stage_and_marks_failed(tmp_path, monkeypatch):
    runtime = make_runtime(tmp_path)
    _, source = build_source(runtime)
    asset_id = asset_id_of(source)

    def broken_fsync(_stage_dir):
        raise OSError("disk flush failed")

    monkeypatch.setattr(render_assets, "fsync_tree", broken_fsync)

    with pytest.raises(OSError):
        create_render_asset(runtime, source, retry_failed=False)

    assert stage_dirs(runtime, asset_id) == []
    assert not final_dir_of(runtime, asset_id).exists()
    row = load_row(runtime, asset_id)
    assert row.status == "failed"
    assert tables.loads_canonical(row.error_json)["code"] == "RENDER_ASSET_PUBLISH_FAILED"


def test_rename_failure_marks_failed_and_business_error_wins(tmp_path, monkeypatch):
    runtime = make_runtime(tmp_path)
    _, source = build_source(runtime)
    asset_id = asset_id_of(source)

    def locked_replace(_src, _dst):
        raise PermissionError("destination locked")

    monkeypatch.setattr(os, "replace", locked_replace)

    with pytest.raises(PermissionError):
        create_render_asset(runtime, source, retry_failed=False)

    assert stage_dirs(runtime, asset_id) == []
    assert not final_dir_of(runtime, asset_id).exists()
    row = load_row(runtime, asset_id)
    assert row.status == "failed"
    assert tables.loads_canonical(row.error_json)["code"] == "RENDER_ASSET_PUBLISH_FAILED"


# ---------------------------------------------------------------------------
# 并发与幂等
# ---------------------------------------------------------------------------


def test_concurrent_second_claim_returns_in_progress(tmp_path):
    runtime = make_runtime(tmp_path)
    _, source = build_source(runtime)
    with runtime.session() as session:
        record, created = RenderAssetRepository(session).claim(source, retry_failed=False)
    assert created is True  # 他方持有 creating 创建权

    with pytest.raises(PlatformError) as excinfo:
        create_render_asset(runtime, source, retry_failed=False)
    assert excinfo.value.code == "RENDER_ASSET_IN_PROGRESS"
    assert excinfo.value.http_status == 409
    assert load_row(runtime, record.id).status == "creating"  # 行状态不受影响


def test_repeated_ready_creation_returns_same_asset_and_sha(tmp_path):
    runtime = make_runtime(tmp_path)
    _, source = build_source(runtime)

    first, created_first = create_render_asset(runtime, source, retry_failed=False)
    assert created_first is True
    final_dir = final_dir_of(runtime, first.id)
    volume_path = final_dir / "volume.nc"
    volume_bytes = volume_path.read_bytes()
    volume_mtime = volume_path.stat().st_mtime_ns
    manifest_bytes = (final_dir / "manifest.json").read_bytes()

    second, created_second = create_render_asset(runtime, source, retry_failed=False)
    assert created_second is False
    assert second.id == first.id
    assert second.status == "ready"
    assert second.netcdf_sha256 == first.netcdf_sha256
    assert volume_path.read_bytes() == volume_bytes
    assert volume_path.stat().st_mtime_ns == volume_mtime  # 未重写
    assert (final_dir / "manifest.json").read_bytes() == manifest_bytes

    # ready 行绝不因 retry_failed 翻回创建
    third, created_third = create_render_asset(runtime, source, retry_failed=True)
    assert created_third is False
    assert third.id == first.id
    assert third.netcdf_sha256 == first.netcdf_sha256
    assert volume_path.stat().st_mtime_ns == volume_mtime


def test_failed_row_returned_without_retry_then_retry_succeeds(tmp_path, monkeypatch):
    runtime = make_runtime(tmp_path)
    _, source = build_source(runtime)
    asset_id = asset_id_of(source)

    def broken_writer(*_args, **_kwargs):
        raise PlatformError("RENDER_NETCDF_WRITE_FAILED", "写入失败", http_status=500)

    monkeypatch.setattr(render_assets, "write_netcdf_package", broken_writer)
    with pytest.raises(PlatformError):
        create_render_asset(runtime, source, retry_failed=False)
    monkeypatch.undo()

    persisted, created = create_render_asset(runtime, source, retry_failed=False)
    assert created is False
    assert persisted.id == asset_id
    assert persisted.status == "failed"
    assert persisted.error is not None
    assert persisted.error.code == "RENDER_NETCDF_WRITE_FAILED"
    assert not final_dir_of(runtime, asset_id).exists()  # 不产生新文件

    retried, created_retry = create_render_asset(runtime, source, retry_failed=True)
    assert created_retry is True
    assert retried.id == asset_id
    assert retried.status == "ready"
    assert final_dir_of(runtime, asset_id).is_dir()


# ---------------------------------------------------------------------------
# 既存 final 目录：有效复用 / 无效隔离
# ---------------------------------------------------------------------------


def test_interrupted_retry_reuses_valid_final_dir(tmp_path):
    runtime = make_runtime(tmp_path)
    _, source = build_source(runtime)
    first, _ = create_render_asset(runtime, source, retry_failed=False)
    final_dir = final_dir_of(runtime, first.id)
    sentinel = final_dir / "sentinel.keep"
    sentinel.write_text("evidence", encoding="utf-8")
    volume_bytes = (final_dir / "volume.nc").read_bytes()
    flip_row_to_interrupted(runtime, first.id)

    record, created = create_render_asset(runtime, source, retry_failed=True)

    assert created is True
    assert record.status == "ready"
    assert record.netcdf_sha256 == first.netcdf_sha256
    assert sentinel.is_file()  # 复用既有目录而非替换
    assert (final_dir / "volume.nc").read_bytes() == volume_bytes
    assert stage_dirs(runtime, first.id) == []  # 本次 stage 已清理


def test_corrupt_final_dir_quarantined_and_request_failed(tmp_path):
    runtime = make_runtime(tmp_path)
    _, source = build_source(runtime)
    first, _ = create_render_asset(runtime, source, retry_failed=False)
    final_dir = final_dir_of(runtime, first.id)
    payload = bytearray((final_dir / "volume.nc").read_bytes())
    payload[len(payload) // 2] ^= 0xFF
    (final_dir / "volume.nc").write_bytes(bytes(payload))
    flip_row_to_interrupted(runtime, first.id)

    with pytest.raises(PlatformError) as excinfo:
        create_render_asset(runtime, source, retry_failed=True)
    assert excinfo.value.code == "RENDER_ASSET_CORRUPT"
    assert excinfo.value.http_status == 409

    assert not final_dir.exists()
    quarantines = list(runtime.settings.render_assets_dir.glob(f"{first.id}.corrupt-*"))
    assert len(quarantines) == 1
    # 损坏证据完整保留，绝不自动删除
    assert (quarantines[0] / "volume.nc").read_bytes() == bytes(payload)
    assert (quarantines[0] / "manifest.json").is_file()
    assert stage_dirs(runtime, first.id) == []
    row = load_row(runtime, first.id)
    assert row.status == "failed"
    assert tables.loads_canonical(row.error_json)["code"] == "RENDER_ASSET_CORRUPT"


# ---------------------------------------------------------------------------
# verify_ready_asset：ready 行的文件侧复核 fail-closed
# ---------------------------------------------------------------------------


def test_verify_ready_asset_detects_volume_hash_mismatch(tmp_path):
    runtime = make_runtime(tmp_path)
    _, source = build_source(runtime)
    record, _ = create_render_asset(runtime, source, retry_failed=False)
    final_dir = final_dir_of(runtime, record.id)
    payload = bytearray((final_dir / "volume.nc").read_bytes())
    payload[100] ^= 0xFF
    (final_dir / "volume.nc").write_bytes(bytes(payload))

    with pytest.raises(PlatformError) as excinfo:
        verify_ready_asset(runtime, record)
    assert excinfo.value.code == "RENDER_ASSET_CORRUPT"
    assert excinfo.value.http_status == 409

    # 幂等复用路径同样 fail-closed：绝不返回记录或字节
    with pytest.raises(PlatformError) as excinfo2:
        create_render_asset(runtime, source, retry_failed=False)
    assert excinfo2.value.code == "RENDER_ASSET_CORRUPT"


def test_verify_ready_asset_detects_missing_checksums(tmp_path):
    runtime = make_runtime(tmp_path)
    _, source = build_source(runtime)
    record, _ = create_render_asset(runtime, source, retry_failed=False)
    (final_dir_of(runtime, record.id) / "checksums.sha256").unlink()

    with pytest.raises(PlatformError) as excinfo:
        verify_ready_asset(runtime, record)
    assert excinfo.value.code == "RENDER_ASSET_CORRUPT"


def test_verify_ready_asset_detects_identity_tamper_with_rehashed_checksums(tmp_path):
    """哈希链自洽但身份字段被篡改时，仍必须按 RENDER_ASSET_CORRUPT 失败。"""

    runtime = make_runtime(tmp_path)
    _, source = build_source(runtime)
    record, _ = create_render_asset(runtime, source, retry_failed=False)
    final_dir = final_dir_of(runtime, record.id)
    manifest_path = final_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_id"] = "tampered-source"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (final_dir / "checksums.sha256").write_text(
        f"{record.netcdf_sha256}  volume.nc\n"
        f"{hashlib.sha256(manifest_path.read_bytes()).hexdigest()}  manifest.json\n",
        encoding="utf-8",
    )

    with pytest.raises(PlatformError) as excinfo:
        verify_ready_asset(runtime, record)
    assert excinfo.value.code == "RENDER_ASSET_CORRUPT"
