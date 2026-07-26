"""Task 6 compensation: a failed microseismic import leaves nothing behind.

Injection points mirror the v0.4.1 upload compensation suite: derivation,
the final-directory atomic replace, the database profile update, and cleanup
itself. Whatever fails, no ``pending://microseismic`` row, no formal dataset
directory and no staging directory may survive, and the original business
exception must be the one that propagates — cleanup failures are logged only.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import pytest

import geomodeling.microseismic.platform_adapter as adapter
from geomodeling.microseismic.config import load_microseismic_config
from geomodeling.microseismic.platform_adapter import (
    MICROSEISMIC_DERIVATION_FAILED,
    MicroseismicImportBundle,
    create_microseismic_case,
    import_microseismic_dataset,
)
from geomodeling.platform import PlatformRuntime
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.repositories import DatasetRepository
from geomodeling.platform.settings import PlatformSettings

from microseismic_fixtures import write_fixture_config, write_fixture_tree


@pytest.fixture()
def runtime(tmp_path: Path):
    runtime = PlatformRuntime(settings=PlatformSettings(data_dir=tmp_path / "runtime"))
    runtime.initialize()
    yield runtime
    runtime.close()


@pytest.fixture()
def case(runtime):
    return create_microseismic_case(runtime)


@pytest.fixture()
def fixture_bundle(tmp_path: Path) -> MicroseismicImportBundle:
    data_dir = write_fixture_tree(tmp_path)
    config_path = write_fixture_config(tmp_path, data_dir)
    return MicroseismicImportBundle(config=load_microseismic_config(config_path), source_dir=data_dir)


def _assert_no_residue(runtime: PlatformRuntime, case_id: str) -> None:
    """No pending dataset row, no files under datasets/, no staging dirs."""

    with runtime.session() as session:
        assert DatasetRepository(session).list_for_case(case_id) == []
    datasets_root = runtime.settings.datasets_dir
    leftovers = list(datasets_root.rglob("*")) if datasets_root.exists() else []
    assert leftovers == [], f"残留数据集目录：{leftovers}"
    staging_root = runtime.settings.microseismic_staging_dir()
    staged = list(staging_root.rglob("*")) if staging_root.exists() else []
    assert staged == [], f"残留暂存目录：{staged}"


def test_derivation_failure_leaves_no_row_or_directories(runtime, case, fixture_bundle, monkeypatch):
    def failing_derive(config, source_dir, output_dir):
        raise RuntimeError("derive boom (simulated)")

    monkeypatch.setattr(adapter, "derive_from_directory", failing_derive)

    with pytest.raises(RuntimeError, match="derive boom"):
        import_microseismic_dataset(runtime, case.id, fixture_bundle)
    _assert_no_residue(runtime, case.id)


def test_golden_gate_failure_creates_nothing(runtime, case, fixture_bundle):
    broken = fixture_bundle.config.model_copy(
        update={"derivation": fixture_bundle.config.derivation.model_copy(update={"expected_accepted": 999})}
    )
    bundle = MicroseismicImportBundle(config=broken, source_dir=fixture_bundle.source_dir)

    with pytest.raises(PlatformError) as excinfo:
        import_microseismic_dataset(runtime, case.id, bundle)
    assert excinfo.value.code == MICROSEISMIC_DERIVATION_FAILED
    failed_names = [check["name"] for check in excinfo.value.details["failed_checks"]]
    assert "golden_accepted_count" in failed_names
    _assert_no_residue(runtime, case.id)


def test_final_directory_replace_failure_compensates(runtime, case, fixture_bundle, monkeypatch):
    def failing_replace(src, dst):
        raise OSError("disk full (simulated)")

    monkeypatch.setattr(adapter, "_replace_directory", failing_replace)

    with pytest.raises(OSError, match="disk full"):
        import_microseismic_dataset(runtime, case.id, fixture_bundle)
    _assert_no_residue(runtime, case.id)


def test_profile_update_failure_compensates(runtime, case, fixture_bundle, monkeypatch):
    def failing_update(runtime_, dataset_id, **kwargs):
        raise RuntimeError("profile boom (simulated)")

    monkeypatch.setattr(adapter, "_update_dataset_record", failing_update)

    with pytest.raises(RuntimeError, match="profile boom"):
        import_microseismic_dataset(runtime, case.id, fixture_bundle)
    _assert_no_residue(runtime, case.id)


def test_cleanup_failure_never_masks_original_exception(runtime, case, fixture_bundle, monkeypatch, caplog):
    """目录清理抛 PermissionError 时，暴露的仍是最初的业务异常（PR #6 回归点）。"""

    def failing_update(runtime_, dataset_id, **kwargs):
        raise RuntimeError("profile boom (simulated)")

    monkeypatch.setattr(adapter, "_update_dataset_record", failing_update)

    original_rmtree = shutil.rmtree

    def raising_rmtree(path, *args, **kwargs):
        if runtime.settings.datasets_dir in Path(path).parents:
            raise PermissionError("directory locked (simulated)")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(adapter.shutil, "rmtree", raising_rmtree)

    with caplog.at_level(logging.ERROR, logger="geomodeling.microseismic.platform_adapter"):
        with pytest.raises(RuntimeError, match="profile boom"):
            import_microseismic_dataset(runtime, case.id, fixture_bundle)

    # 数据库行已补偿删除；清理失败只记日志（含堆栈），不覆盖业务异常。
    with runtime.session() as session:
        assert DatasetRepository(session).list_for_case(case.id) == []
    compensation_logs = [
        record for record in caplog.records if "compensation" in record.getMessage() and record.exc_info
    ]
    assert compensation_logs, "清理失败必须留下带堆栈的日志"
    # 清理确实失败了：正式目录残留是被允许的（已记录），绝不悄悄成功。
    assert list(runtime.settings.datasets_dir.rglob("*"))
