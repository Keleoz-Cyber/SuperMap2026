"""Task 6 happy-path: atomic import of a microseismic DAT bundle into the platform.

The portable fixture contributes its own counts (3 DAT files, 6 modeling
nodes); the real 1,911-node contract is asserted only in the ``local_data``
regression at the bottom, where the adjacent read-only bundle is available.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from geomodeling.cli import app
from geomodeling.microseismic.config import load_microseismic_config
from geomodeling.microseismic.platform_adapter import (
    MicroseismicImportBundle,
    create_microseismic_case,
    import_microseismic_dataset,
)
from geomodeling.platform import PlatformRuntime
from geomodeling.platform.ingest import STANDARDIZED_SCHEMA, write_standardized_frame
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.repositories import CaseRepository, DatasetRepository
from geomodeling.platform.settings import PlatformSettings

from microseismic_fixtures import write_dat, write_fixture_config, write_fixture_tree

runner = CliRunner()

REAL_CONFIG_AVAILABLE = load_microseismic_config().data_dir.is_dir()


@pytest.fixture()
def runtime(tmp_path: Path):
    runtime = PlatformRuntime(settings=PlatformSettings(data_dir=tmp_path / "runtime"))
    runtime.initialize()
    yield runtime
    runtime.close()


@pytest.fixture()
def fixture_bundle(tmp_path: Path) -> MicroseismicImportBundle:
    data_dir = write_fixture_tree(tmp_path)
    config_path = write_fixture_config(tmp_path, data_dir)
    return MicroseismicImportBundle(config=load_microseismic_config(config_path), source_dir=data_dir)


def test_import_creates_mapped_dataset_with_unique_node_contract(runtime, fixture_bundle):
    case = create_microseismic_case(runtime)
    record = import_microseismic_dataset(runtime, case.id, fixture_bundle)
    assert record.status == "mapped"
    assert record.profile["source_kind"] == "microseismic_dat_bundle"
    assert record.profile["mapping"]["dimension"] == "3d"
    assert record.profile["mapping"]["value"] == "VX_KM_S"
    frame = pd.read_parquet(runtime.settings.standardized_dataset(case.id, record.id))
    assert frame["is_numeric_valid"].all()
    assert not frame.duplicated(["x", "y", "z"]).any()


def test_import_produces_immutable_dataset_directory_layout(runtime, fixture_bundle):
    case = create_microseismic_case(runtime)
    record = import_microseismic_dataset(runtime, case.id, fixture_bundle)
    dataset_dir = runtime.settings.microseismic_dataset_dir(case.id, record.id)

    source_dir = dataset_dir / "source"
    copied = sorted(path.name for path in source_dir.glob("*.dat"))
    assert copied == ["W1.dat", "W2.dat", "WA.dat"]
    # Copies are byte-identical to the read-only bundle.
    for name in copied:
        assert (source_dir / name).read_bytes() == (fixture_bundle.source_dir / name).read_bytes()
    manifest = json.loads((source_dir / "source_manifest.json").read_text(encoding="utf-8"))
    assert [entry["file_name"] for entry in manifest] == ["W1.dat", "W2.dat", "WA.dat"]
    # record.source_path points at the internal manifest (multi-file authority).
    assert Path(record.source_path) == source_dir / "source_manifest.json"

    derived = dataset_dir / "derived"
    # Layered names embed the portable fixture's own counts, never the real ones.
    assert (derived / "source_records_7.csv").is_file()
    assert (derived / "invalid_records_1.csv").is_file()
    assert (derived / "rejected_3sigma_0.csv").is_file()
    assert (derived / "accepted_modeling_6.csv").is_file()
    assert (derived / "aggregated_nodes_6.csv").is_file()
    assert (derived / "modeling_provenance.parquet").is_file()
    assert (derived / "derivation_report.json").is_file()
    assert runtime.settings.modeling_provenance(case.id, record.id) == derived / "modeling_provenance.parquet"

    # No staging residue survives a successful import.
    staging_root = runtime.settings.microseismic_staging_dir()
    assert not staging_root.exists() or list(staging_root.iterdir()) == []
    # No temporary sibling survives the atomic rename.
    assert [p for p in (runtime.settings.datasets_dir / case.id).iterdir() if p.name != record.id] == []


def test_standardized_frame_matches_modeling_provenance_row_for_row(runtime, fixture_bundle):
    case = create_microseismic_case(runtime)
    record = import_microseismic_dataset(runtime, case.id, fixture_bundle)
    frame = pd.read_parquet(runtime.settings.standardized_dataset(case.id, record.id))
    provenance = pd.read_parquet(runtime.settings.modeling_provenance(case.id, record.id))

    assert list(frame.columns) == STANDARDIZED_SCHEMA
    assert len(frame) == 6  # portable fixture's unique modeling nodes
    # source_row follows the accepted-table first-appearance order, 1-based,
    # exactly as exported by modeling_provenance.parquet.
    assert list(frame["source_row"]) == list(provenance["source_row"]) == [1, 2, 3, 4, 5, 6]
    assert frame["x"].tolist() == provenance["x_local_m"].tolist()
    assert frame["y"].tolist() == provenance["y_local_m"].tolist()
    assert frame["z"].tolist() == provenance["z_local_m"].tolist()
    assert frame["value"].tolist() == provenance["vx_km_s"].tolist()


def test_profile_records_mapping_versions_golden_and_provenance_summary(runtime, fixture_bundle):
    case = create_microseismic_case(runtime)
    record = import_microseismic_dataset(runtime, case.id, fixture_bundle)
    profile = record.profile

    mapping = profile["mapping"]
    assert mapping == {
        "dimension": "3d",
        "x": "X_LOCAL_M",
        "y": "Y_LOCAL_M",
        "z": "Z_LOCAL_M",
        "value": "VX_KM_S",
        "value_name": "Vx",
        "value_unit": "km/s",
        "coordinate_kind": "local_linear",
        "crs_text": None,
    }
    assert profile["dimension"] == "3d"
    assert profile["rule_version"] == "microseismic_local_3d_v0.2b_confirmed_2026-07-20"
    assert profile["adapter_version"] == "0.5.0"
    assert profile["aggregation_method"] == "arithmetic_mean_exact_xyz"
    assert profile["golden"]["passed"] is True
    assert all(check["passed"] for check in profile["golden"]["checks"])
    assert profile["layer_counts"] == {
        "source_records": 7,
        "finite_records": 6,
        "invalid_records": 1,
        "rejected_3sigma": 0,
        "accepted_modeling": 6,
        "aggregated_nodes": 6,
    }
    assert profile["row_count"] == 6
    assert profile["valid_row_count"] == 6
    assert profile["invalid_row_count"] == 0
    assert len(profile["standardized_sha256"]) == 64
    assert Path(record.standardized_path).name == "standardized.parquet"
    assert [entry["file_name"] for entry in profile["source_files"]] == ["W1.dat", "W2.dat", "WA.dat"]
    assert all(len(entry["sha256"]) == 64 for entry in profile["source_files"])
    assert record.version == 1


def test_microseismic_settings_paths_are_deterministic(tmp_path: Path):
    settings = PlatformSettings(data_dir=tmp_path)
    assert settings.microseismic_dataset_dir("case-a", "ds-b") == tmp_path / "datasets" / "case-a" / "ds-b"
    assert settings.microseismic_staging_dir() == tmp_path / "staging" / "microseismic"
    assert settings.modeling_provenance("case-a", "ds-b") == (
        tmp_path / "datasets" / "case-a" / "ds-b" / "derived" / "modeling_provenance.parquet"
    )


def test_write_standardized_frame_round_trip_and_summary(tmp_path: Path):
    frame = pd.DataFrame(
        {
            "source_row": [1, 2],
            "x": [1.0, 2.0],
            "y": [3.0, 4.0],
            "z": [-5.0, -6.0],
            "value": [0.5, 0.6],
            "is_numeric_valid": [True, True],
        }
    )
    target = tmp_path / "nested" / "standardized.parquet"
    summary = write_standardized_frame(target, frame)
    assert summary["row_count"] == 2
    assert summary["valid_row_count"] == 2
    assert summary["invalid_row_count"] == 0
    assert summary["standardized_path"] == str(target)
    reread = pd.read_parquet(target)
    assert list(reread.columns) == STANDARDIZED_SCHEMA
    assert reread.equals(frame)


def test_write_standardized_frame_rejects_nonstandard_schema(tmp_path: Path):
    frame = pd.DataFrame({"source_row": [1], "x": [1.0], "value": [0.5]})
    with pytest.raises(PlatformError):
        write_standardized_frame(tmp_path / "standardized.parquet", frame)


def test_cli_import_case_success_prints_ids_counts_and_gates(tmp_path: Path):
    data_dir = write_fixture_tree(tmp_path)
    config_path = write_fixture_config(tmp_path, data_dir)
    platform_dir = tmp_path / "platform"
    completed = runner.invoke(
        app,
        [
            "microseismic",
            "import-case",
            "--source-dir",
            str(data_dir),
            "--data-dir",
            str(platform_dir),
            "--config",
            str(config_path),
        ],
    )
    assert completed.exit_code == 0, completed.output
    assert "case_id=" in completed.output
    assert "dataset_id=" in completed.output
    assert "source_records=7" in completed.output
    assert "rejected_3sigma=0" in completed.output
    assert "accepted_modeling=6" in completed.output
    assert "modeling_nodes=6" in completed.output
    assert "rule_version=microseismic_local_3d_v0.2b_confirmed_2026-07-20" in completed.output
    assert "golden_passed=True" in completed.output
    assert "validation_passed=True" in completed.output

    runtime = PlatformRuntime(settings=PlatformSettings(data_dir=platform_dir))
    runtime.initialize()
    try:
        with runtime.session() as session:
            cases = CaseRepository(session).list_all()
            assert len(cases) == 1
            assert cases[0].name == "微震速度建模"
            assert cases[0].case_type == "microseismic"
            datasets = DatasetRepository(session).list_for_case(cases[0].id)
            assert len(datasets) == 1
            assert datasets[0].status == "mapped"
    finally:
        runtime.close()


def test_cli_import_case_blocked_contract_exits_1_without_dataset(tmp_path: Path):
    data_dir = write_fixture_tree(tmp_path)
    write_dat(data_dir / "WX.dat", ["        0.100000        1.000000"])  # 未知文件 → 合同失败
    config_path = write_fixture_config(tmp_path, data_dir)
    platform_dir = tmp_path / "platform"
    completed = runner.invoke(
        app,
        [
            "microseismic",
            "import-case",
            "--source-dir",
            str(data_dir),
            "--data-dir",
            str(platform_dir),
            "--config",
            str(config_path),
        ],
    )
    assert completed.exit_code == 1
    assert "validation_passed=False" in completed.output or "FAILED" in completed.output

    runtime = PlatformRuntime(settings=PlatformSettings(data_dir=platform_dir))
    runtime.initialize()
    try:
        with runtime.session() as session:
            cases = CaseRepository(session).list_all()
            assert len(cases) == 1  # 案例保留，数据集不得残留
            assert DatasetRepository(session).list_for_case(cases[0].id) == []
    finally:
        runtime.close()


@pytest.mark.local_data
@pytest.mark.skipif(not REAL_CONFIG_AVAILABLE, reason="microseismic read-only reference data is not available")
def test_real_bundle_import_produces_1911_unique_nodes(tmp_path: Path):
    config = load_microseismic_config()
    runtime = PlatformRuntime(settings=PlatformSettings(data_dir=tmp_path / "runtime"))
    runtime.initialize()
    try:
        case = create_microseismic_case(runtime)
        record = import_microseismic_dataset(
            runtime, case.id, MicroseismicImportBundle(config=config, source_dir=config.data_dir)
        )
        assert record.status == "mapped"
        assert record.profile["layer_counts"] == {
            "source_records": 2006,
            "finite_records": 2005,
            "invalid_records": 1,
            "rejected_3sigma": 80,
            "accepted_modeling": 1925,
            "aggregated_nodes": 1911,
        }
        frame = pd.read_parquet(runtime.settings.standardized_dataset(case.id, record.id))
        assert len(frame) == 1911
        assert frame["is_numeric_valid"].all()
        assert not frame.duplicated(["x", "y", "z"]).any()

        dataset_dir = runtime.settings.microseismic_dataset_dir(case.id, record.id)
        assert len(list((dataset_dir / "source").glob("*.dat"))) == 22
        assert (dataset_dir / "source" / "source_manifest.json").is_file()
        assert (dataset_dir / "derived" / "accepted_modeling_1925.csv").is_file()
        assert (dataset_dir / "derived" / "rejected_3sigma_80.csv").is_file()
        assert (dataset_dir / "derived" / "aggregated_nodes_1911.csv").is_file()
        provenance = pd.read_parquet(runtime.settings.modeling_provenance(case.id, record.id))
        assert len(provenance) == 1911
        assert list(frame["source_row"]) == list(provenance["source_row"])
    finally:
        runtime.close()
