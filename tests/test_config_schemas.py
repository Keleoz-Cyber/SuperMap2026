from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from geomodeling.config import load_config
from geomodeling.microseismic.config import load_microseismic_config
from geomodeling.schemas import ModelMetadata, ModelStatus, ResultCategory, SuperMapResultRegistration


def test_default_config_loads():
    config = load_config()
    assert config.expected["standardized_rows"] == 17549
    assert config.expected["validation_rows"] == 1722
    assert len(config.models) == 5
    assert config.prediction_files()["Kriging 20m/40点"].name == "RHO_KRIG_CV_VALID_40.csv"


def test_default_resistivity_csv_resolves_from_nested_worktree():
    config = load_config()
    standardized = config.resolve_path(config.paths["standardized"])
    assert standardized is not None
    assert standardized.name == "地下电阻率节点_标准化.csv"
    # The adjacent data package is local-only, but when present it must be
    # found from both the main checkout and a nested integration worktree.
    if standardized.parent.exists():
        assert standardized.is_file()


def test_resolve_path_logs_diagnostics(caplog):
    import logging

    config = load_config()
    with caplog.at_level(logging.WARNING, logger="geomodeling.config"):
        missing = config.resolve_path("no_such_dir/nonexistent_file_zzz.csv")
    assert missing is not None and not missing.exists()
    assert any("配置路径不存在" in record.message for record in caplog.records)
    warning = next(r for r in caplog.records if "配置路径不存在" in r.message)
    # 诊断必须列出实际尝试过的根目录，便于启动时定位 worktree 路径问题
    assert ".worktrees" in warning.message or str(missing.parent) in warning.message


def test_model_status_is_fixed():
    assert {status.value for status in ModelStatus} == {"created", "running", "succeeded", "failed", "invalidated"}


def test_model_metadata_rejects_dsi_method():
    with pytest.raises(ValidationError):
        ModelMetadata(
            model_id="bad",
            method="DSI",
            input_dataset_id="rho_training_v1",
            input_sha256="0" * 64,
            crs={"type": "local_engineering", "epsg": None},
            axis={"horizontal_unit": "m", "vertical_unit": "m", "z_positive": "up"},
            grid={},
            generated_at=datetime.now(timezone.utc),
        )


def test_supermap_registration_prevents_false_success():
    with pytest.raises(ValidationError):
        SuperMapResultRegistration(
            dataset="EMPTY_BUT_SUCCESS",
            model_id="rho_kriging_20m_n40_v1",
            dataset_type="isosurface",
            method="KRIGING_ORDINARY",
            datasource_alias="expore1",
            status="succeeded",
            result_category=ResultCategory.FORMAL,
            object_count=0,
            openable=True,
        )


def test_microseismic_derivation_contract_is_typed_and_versioned():
    derivation = load_microseismic_config().derivation
    assert derivation.rule_version == "microseismic_local_3d_v0.2b_confirmed_2026-07-20"
    assert derivation.adapter_version == "0.5.0"
    assert derivation.depth_multiplier == 1000.0
    assert derivation.z_multiplier == -1.0
    assert derivation.vx_unit == "km/s"
    assert derivation.expected_rejected == 80
    assert derivation.expected_accepted == 1925
    assert derivation.expected_conflict_groups == 13
    assert derivation.expected_conflict_rows == 27


def test_microseismic_golden_hash_pattern_rejects_non_lowercase_hex():
    derivation = load_microseismic_config().derivation
    payload = derivation.model_dump()
    payload["golden"]["accepted_sha256"] = "A" * 64
    with pytest.raises(ValidationError):
        type(derivation).model_validate(payload)
