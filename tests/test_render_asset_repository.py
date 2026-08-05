"""RenderAssetRepository state-machine tests (SQLite v6).

All transitions are compare-and-update: ready/interrupted/failed rows are
never blindly overwritten, ``claim`` is idempotent on the five-column source
identity, and uniqueness races roll back and re-read the winning row.
Everything runs against a tmp_path PlatformRuntime.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from geomodeling.platform import PlatformRuntime
from geomodeling.platform.errors import INVALID_STATUS_TRANSITION, PlatformError
from geomodeling.platform.render_contracts import RenderGridSource
from geomodeling.platform.repositories import RenderAssetRepository
from geomodeling.platform.schemas import (
    FORMAT_VERSION,
    RENDERER,
    STATUS_CREATING,
    STATUS_FAILED,
    STATUS_INTERRUPTED,
    STATUS_READY,
    RenderAssetRecord,
    render_asset_id,
)
from geomodeling.platform.tables import ERROR_PROCESS_RESTARTED, RenderAsset

from test_platform_repositories import create_case, create_succeeded_candidate

GRID_SHA = "a" * 64
OTHER_GRID_SHA = "b" * 64
NETCDF_SHA = "c" * 64


def make_runtime(tmp_path: Path) -> PlatformRuntime:
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    return runtime


def make_source(
    *,
    source_kind: str = "builtin_legacy",
    source_id: str = "resistivity",
    grid_sha256: str = GRID_SHA,
) -> RenderGridSource:
    return RenderGridSource(
        source_kind=source_kind,  # type: ignore[arg-type]
        source_id=source_id,
        grid_path=Path(f"render-sources/{source_kind}/{source_id}/{grid_sha256}/grid.npz"),
        grid_sha256=grid_sha256,
        property_name="RHO",
        units="unknown",
        coordinate_kind="local_linear",
        dimension="3d",
    )


def claim(
    runtime: PlatformRuntime, source: RenderGridSource, *, retry_failed: bool = False
) -> tuple[RenderAssetRecord, bool]:
    with runtime.session() as session:
        return RenderAssetRepository(session).claim(source, retry_failed=retry_failed)


def mark_ready(runtime: PlatformRuntime, asset_id: str, **overrides) -> RenderAssetRecord:
    kwargs = {
        "netcdf_sha256": NETCDF_SHA,
        "asset_dir": "render-assets/" + asset_id,
        "manifest": {"format": "supermap-voxel-netcdf", "version": 2},
    }
    kwargs.update(overrides)
    with runtime.session() as session:
        return RenderAssetRepository(session).mark_ready(asset_id, **kwargs)


def mark_failed(runtime: PlatformRuntime, asset_id: str, **overrides) -> RenderAssetRecord:
    kwargs = {"code": "RENDER_NETCDF_WRITE_FAILED", "message": "写入失败", "details": {"stage": "write"}}
    kwargs.update(overrides)
    with runtime.session() as session:
        return RenderAssetRepository(session).mark_failed(asset_id, **kwargs)


def load_row(runtime: PlatformRuntime, asset_id: str) -> RenderAsset:
    with runtime.session() as session:
        row = session.get(RenderAsset, asset_id)
        assert row is not None, f"render asset {asset_id} not persisted"
        session.expunge(row)
        return row


def row_count(runtime: PlatformRuntime) -> int:
    with runtime.session() as session:
        return session.query(RenderAsset).count()


def test_render_asset_id_formula_is_pinned():
    # 逐字段拼接（NUL 分隔），与设计 §2.2 的 payload 公式逐字一致。
    payload = f"candidate_result\0cand-1\0{GRID_SHA}\0supermap_voxelgrid_netcdf\0{FORMAT_VERSION}"
    expected = f"nc-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:32]}"
    assert (
        render_asset_id(source_kind="candidate_result", source_id="cand-1", grid_sha256=GRID_SHA)
        == expected
    )
    assert expected.startswith("nc-") and len(expected) == 3 + 32
    assert RENDERER == "supermap_voxelgrid_netcdf"
    assert FORMAT_VERSION == 2


def test_claim_missing_source_creates_creating_row(tmp_path):
    runtime = make_runtime(tmp_path)
    source = make_source()

    record, created = claim(runtime, source)

    assert created is True
    assert record.id == render_asset_id(
        source_kind="builtin_legacy", source_id="resistivity", grid_sha256=GRID_SHA
    )
    assert record.source_kind == "builtin_legacy"
    assert record.source_id == "resistivity"
    assert record.renderer == RENDERER
    assert record.status == STATUS_CREATING
    assert record.grid_sha256 == GRID_SHA
    assert record.netcdf_sha256 is None
    assert record.manifest_url is None
    assert record.netcdf_url is None
    assert record.error is None

    row = load_row(runtime, record.id)
    assert row.status == "creating"
    assert row.renderer == "supermap_voxelgrid_netcdf"
    assert row.format_version == FORMAT_VERSION
    assert row.manifest_json == "{}"
    assert row.error_json is None
    assert row.candidate_result_id is None  # builtin_legacy 不挂候选外键
    runtime.close()


def test_claim_candidate_source_binds_candidate_fk(tmp_path):
    runtime = make_runtime(tmp_path)
    case_id = create_case(runtime)
    candidate_id = create_succeeded_candidate(runtime, case_id)
    source = make_source(source_kind="candidate_result", source_id=candidate_id)

    record, created = claim(runtime, source)

    assert created is True
    assert load_row(runtime, record.id).candidate_result_id == candidate_id
    runtime.close()


def test_claim_existing_creating_reuses_row_without_creating(tmp_path):
    runtime = make_runtime(tmp_path)
    source = make_source()
    first, created = claim(runtime, source)
    assert created is True

    second, created = claim(runtime, source)

    assert created is False
    assert second.id == first.id
    assert second.status == STATUS_CREATING
    assert row_count(runtime) == 1
    runtime.close()


def test_claim_uniqueness_race_rolls_back_and_rereads_winner(tmp_path, monkeypatch):
    runtime = make_runtime(tmp_path)
    source = make_source()
    winner, created = claim(runtime, source)
    assert created is True

    # 模拟竞态：首次身份查找未命中（并发者尚未提交），插入撞五列唯一约束后
    # 必须回滚并重读胜出者，而不是向调用方抛错或覆盖既有行。
    real_get = RenderAssetRepository._get_by_identity
    calls = {"n": 0}

    def first_read_misses(self, src):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return real_get(self, src)

    monkeypatch.setattr(RenderAssetRepository, "_get_by_identity", first_read_misses)
    record, created = claim(runtime, source)

    assert created is False
    assert record.id == winner.id
    assert record.status == STATUS_CREATING
    assert calls["n"] == 2  # 首次未命中 + 回滚后重读胜出者
    assert row_count(runtime) == 1
    runtime.close()


def test_mark_ready_transitions_creating_to_ready(tmp_path):
    runtime = make_runtime(tmp_path)
    record, _ = claim(runtime, make_source())
    manifest = {"format": "supermap-voxel-netcdf", "version": 2, "grid_sha256": GRID_SHA}

    ready = mark_ready(runtime, record.id, manifest=manifest)

    assert ready.status == STATUS_READY
    assert ready.netcdf_sha256 == NETCDF_SHA
    assert ready.manifest_url == f"/api/render-assets/{record.id}/manifest"
    assert ready.netcdf_url == f"/api/render-assets/{record.id}/volume.nc"
    assert ready.error is None

    row = load_row(runtime, record.id)
    assert row.status == "ready"
    assert row.netcdf_sha256 == NETCDF_SHA
    assert row.asset_dir == "render-assets/" + record.id
    assert row.manifest_json == json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    assert row.error_json is None
    runtime.close()


def test_mark_ready_rejects_non_creating_states(tmp_path):
    runtime = make_runtime(tmp_path)
    record, _ = claim(runtime, make_source())
    mark_failed(runtime, record.id)

    with pytest.raises(PlatformError) as excinfo:
        mark_ready(runtime, record.id)
    assert excinfo.value.code == INVALID_STATUS_TRANSITION
    assert excinfo.value.http_status == 409

    row = load_row(runtime, record.id)
    assert row.status == "failed"  # 失败现状不被就绪结果覆盖
    assert row.netcdf_sha256 is None

    with pytest.raises(PlatformError) as excinfo:
        mark_ready(runtime, "nc-ghost")
    assert excinfo.value.code == "RENDER_ASSET_NOT_FOUND"
    assert excinfo.value.http_status == 404
    runtime.close()


def test_mark_failed_transitions_creating_to_failed(tmp_path):
    runtime = make_runtime(tmp_path)
    record, _ = claim(runtime, make_source())

    failed = mark_failed(runtime, record.id)

    assert failed.status == STATUS_FAILED
    assert failed.error is not None
    assert failed.error.code == "RENDER_NETCDF_WRITE_FAILED"
    assert failed.error.message == "写入失败"
    assert failed.error.details == {"stage": "write"}
    assert failed.netcdf_sha256 is None
    assert failed.manifest_url is None
    assert failed.netcdf_url is None

    row = load_row(runtime, record.id)
    assert row.status == "failed"
    assert json.loads(row.error_json) == {
        "code": "RENDER_NETCDF_WRITE_FAILED",
        "message": "写入失败",
        "details": {"stage": "write"},
    }
    runtime.close()


def test_mark_failed_rejects_non_creating_states(tmp_path):
    runtime = make_runtime(tmp_path)
    record, _ = claim(runtime, make_source())
    mark_ready(runtime, record.id)

    with pytest.raises(PlatformError) as excinfo:
        mark_failed(runtime, record.id)
    assert excinfo.value.code == INVALID_STATUS_TRANSITION
    assert excinfo.value.http_status == 409
    assert load_row(runtime, record.id).status == "ready"  # ready 终态不被失败覆盖
    runtime.close()


def test_startup_recovery_marks_creating_interrupted_and_preserves_terminal_rows(tmp_path):
    runtime = make_runtime(tmp_path)
    creating, _ = claim(runtime, make_source(source_id="src-creating", grid_sha256="1" * 64))
    ready, _ = claim(runtime, make_source(source_id="src-ready", grid_sha256="2" * 64))
    failed, _ = claim(runtime, make_source(source_id="src-failed", grid_sha256="3" * 64))
    mark_ready(runtime, ready.id)
    mark_failed(runtime, failed.id)

    flipped = runtime.recover_interrupted_runs()

    assert flipped == 1  # 只有 creating 资产被原子翻转
    with runtime.session() as session:
        repo = RenderAssetRepository(session)
        recovered = repo.get_for_source("builtin_legacy", "src-creating")
        assert recovered.status == STATUS_INTERRUPTED
        assert recovered.error is not None
        assert recovered.error.code == ERROR_PROCESS_RESTARTED
        assert recovered.error.message == "render asset creation interrupted"
        assert repo.get_for_source("builtin_legacy", "src-ready").status == STATUS_READY
        assert repo.get_for_source("builtin_legacy", "src-failed").status == STATUS_FAILED
    runtime.close()


def test_claim_failed_requires_retry_flag(tmp_path):
    runtime = make_runtime(tmp_path)
    source = make_source()
    record, _ = claim(runtime, source)
    mark_failed(runtime, record.id)

    reused, created = claim(runtime, source, retry_failed=False)

    assert created is False
    assert reused.id == record.id
    assert reused.status == STATUS_FAILED
    assert reused.error is not None
    assert reused.error.code == "RENDER_NETCDF_WRITE_FAILED"
    assert load_row(runtime, record.id).status == "failed"
    runtime.close()


def test_claim_failed_with_retry_flips_to_creating_and_clears_failure(tmp_path):
    runtime = make_runtime(tmp_path)
    source = make_source()
    record, _ = claim(runtime, source)
    mark_failed(runtime, record.id)

    reclaimed, created = claim(runtime, source, retry_failed=True)

    assert created is True
    assert reclaimed.id == record.id  # 同一身份复用同一行，不产生新行
    assert reclaimed.status == STATUS_CREATING
    assert reclaimed.error is None
    row = load_row(runtime, record.id)
    assert row.status == "creating"
    assert row.error_json is None
    assert row.netcdf_sha256 is None
    assert row.asset_dir is None
    assert row.manifest_json == "{}"
    assert row_count(runtime) == 1
    runtime.close()


def test_claim_ready_is_idempotent_reuse_and_retry_never_recreates(tmp_path):
    runtime = make_runtime(tmp_path)
    source = make_source()
    record, _ = claim(runtime, source)
    mark_ready(runtime, record.id)

    again, created = claim(runtime, source, retry_failed=False)
    assert created is False
    assert again.status == STATUS_READY
    assert again.netcdf_sha256 == NETCDF_SHA

    # ready → creating 禁止：即使显式 retry_failed=true 也不翻回。
    retried, created = claim(runtime, source, retry_failed=True)
    assert created is False
    assert retried.status == STATUS_READY
    row = load_row(runtime, record.id)
    assert row.status == "ready"
    assert row.netcdf_sha256 == NETCDF_SHA
    assert row_count(runtime) == 1
    runtime.close()


def test_claim_interrupted_requires_retry_flag(tmp_path):
    runtime = make_runtime(tmp_path)
    source = make_source()
    record, _ = claim(runtime, source)
    runtime.recover_interrupted_runs()

    kept, created = claim(runtime, source, retry_failed=False)
    assert created is False
    assert kept.status == STATUS_INTERRUPTED
    assert kept.error is not None
    assert kept.error.code == ERROR_PROCESS_RESTARTED

    reclaimed, created = claim(runtime, source, retry_failed=True)
    assert created is True
    assert reclaimed.id == record.id
    assert reclaimed.status == STATUS_CREATING
    assert reclaimed.error is None
    runtime.close()


def test_get_for_source_returns_latest_asset(tmp_path):
    runtime = make_runtime(tmp_path)
    older, _ = claim(runtime, make_source(grid_sha256=GRID_SHA))
    newer, _ = claim(runtime, make_source(grid_sha256=OTHER_GRID_SHA))
    # 强制可区分时间戳，避免 created_at 并列影响排序断言。
    with runtime.session() as session:
        row = session.get(RenderAsset, older.id)
        row.created_at = "2026-08-01T00:00:00+00:00"
        session.commit()

    with runtime.session() as session:
        record = RenderAssetRepository(session).get_for_source("builtin_legacy", "resistivity")

    assert record.id == newer.id
    assert record.grid_sha256 == OTHER_GRID_SHA
    runtime.close()


def test_get_for_source_missing_raises_not_found(tmp_path):
    runtime = make_runtime(tmp_path)
    with runtime.session() as session:
        with pytest.raises(PlatformError) as excinfo:
            RenderAssetRepository(session).get_for_source("builtin_legacy", "ghost")
    assert excinfo.value.code == "RENDER_ASSET_NOT_FOUND"
    assert excinfo.value.http_status == 404
    runtime.close()


def test_get_ready_returns_ready_record(tmp_path):
    runtime = make_runtime(tmp_path)
    record, _ = claim(runtime, make_source())
    mark_ready(runtime, record.id)

    with runtime.session() as session:
        ready = RenderAssetRepository(session).get_ready(record.id)

    assert ready.status == STATUS_READY
    assert ready.netcdf_sha256 == NETCDF_SHA
    assert ready.netcdf_url == f"/api/render-assets/{record.id}/volume.nc"
    runtime.close()


def test_get_ready_rejects_non_ready_and_missing(tmp_path):
    runtime = make_runtime(tmp_path)
    record, _ = claim(runtime, make_source())

    with runtime.session() as session:
        with pytest.raises(PlatformError) as excinfo:
            RenderAssetRepository(session).get_ready(record.id)
        assert excinfo.value.code == "RENDER_ASSET_NOT_READY"
        assert excinfo.value.http_status == 409
        with pytest.raises(PlatformError) as excinfo:
            RenderAssetRepository(session).get_ready("nc-ghost")
        assert excinfo.value.code == "RENDER_ASSET_NOT_FOUND"
        assert excinfo.value.http_status == 404
    runtime.close()


def test_public_record_never_serializes_asset_dir(tmp_path):
    runtime = make_runtime(tmp_path)
    record, _ = claim(runtime, make_source())
    absolute_dir = (tmp_path / "render-assets" / record.id).as_posix()
    ready = mark_ready(runtime, record.id, asset_dir=absolute_dir)

    dumped = ready.model_dump()
    assert set(dumped) == {
        "id",
        "source_kind",
        "source_id",
        "renderer",
        "status",
        "grid_sha256",
        "netcdf_sha256",
        "manifest_url",
        "netcdf_url",
        "error",
    }
    raw_json = ready.model_dump_json()
    assert "asset_dir" not in raw_json
    assert absolute_dir not in raw_json  # 内部目录值也不经任何字段泄露
    assert load_row(runtime, record.id).asset_dir == absolute_dir  # 仅服务端行内可见
    runtime.close()
