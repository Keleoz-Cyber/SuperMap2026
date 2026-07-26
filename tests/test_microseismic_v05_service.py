import json
from hashlib import sha256
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from geomodeling.cli import app
from geomodeling.microseismic.config import load_microseismic_config
from geomodeling.microseismic.service import derive_from_directory
from geomodeling.platform.errors import PlatformError

from microseismic_fixtures import write_dat, write_fixture_config, write_fixture_tree

runner = CliRunner()


@pytest.fixture()
def fixture_config(tmp_path: Path):
    data_dir = write_fixture_tree(tmp_path)
    config_path = write_fixture_config(tmp_path, data_dir)
    return load_microseismic_config(config_path)


def test_derive_exports_all_layers_and_unblocks_downstream(fixture_config, tmp_path):
    result, outputs = derive_from_directory(
        fixture_config,
        fixture_config.data_dir,
        tmp_path / "out",
    )
    assert result.validation.passed is True
    assert result.downstream_gates == {
        "geometry_blocked": False,
        "cleaning_blocked": False,
        "interpolation_blocked": False,
    }
    assert set(outputs) >= {
        "source_records", "invalid_records", "rejected_3sigma",
        "accepted_modeling", "aggregated_nodes", "modeling_provenance",
        "derivation_report",
    }


def test_layer_file_names_embed_actual_counts(fixture_config, tmp_path):
    # Portable fixtures must never claim the real 2006/1925/80/1911 counts, so
    # the layered CSV names embed the counts produced by this run.
    _, outputs = derive_from_directory(fixture_config, fixture_config.data_dir, tmp_path / "out")
    assert outputs["source_records"].name == "source_records_7.csv"
    assert outputs["invalid_records"].name == "invalid_records_1.csv"
    assert outputs["rejected_3sigma"].name == "rejected_3sigma_0.csv"
    assert outputs["accepted_modeling"].name == "accepted_modeling_6.csv"
    assert outputs["aggregated_nodes"].name == "aggregated_nodes_6.csv"
    assert outputs["modeling_provenance"].name == "modeling_provenance.parquet"
    assert outputs["derivation_report"].name == "derivation_report.json"


def test_exported_canonical_bytes_match_fixture_golden(fixture_config, tmp_path):
    _, outputs = derive_from_directory(fixture_config, fixture_config.data_dir, tmp_path / "out")
    golden = fixture_config.derivation.golden
    assert sha256(outputs["accepted_modeling"].read_bytes()).hexdigest() == golden.accepted_sha256
    assert sha256(outputs["rejected_3sigma"].read_bytes()).hexdigest() == golden.rejected_sha256


def test_aggregated_nodes_csv_columns(fixture_config, tmp_path):
    _, outputs = derive_from_directory(fixture_config, fixture_config.data_dir, tmp_path / "out")
    nodes = pd.read_csv(outputs["aggregated_nodes"])
    assert list(nodes.columns) == [
        "POINT_ID", "LINE_ID", "X_LOCAL_M", "Y_LOCAL_M", "Z_LOCAL_M", "VX_KM_S",
        "SOURCE_SAMPLE_IDS", "SAMPLE_COUNT", "VX_MIN_KM_S", "VX_MAX_KM_S", "VX_SAMPLE_STD_KM_S",
    ]
    assert len(nodes) == 6


def test_modeling_provenance_source_row_is_stable(fixture_config, tmp_path):
    result, outputs = derive_from_directory(fixture_config, fixture_config.data_dir, tmp_path / "out")
    frame = pd.read_parquet(outputs["modeling_provenance"])
    # 1-based index of each node in first-appearance order within the accepted
    # golden table; the platform standardized.parquet reuses the same source_row.
    assert list(frame["source_row"]) == [1, 2, 3, 4, 5, 6]
    assert frame["sample_count"].sum() == 6
    assert set(frame["point_id"]) == {"W1", "W2", "WA"}
    first_appearance: list[tuple[float, float, float]] = []
    for row in result.filtered.accepted:
        key = (row.x_local_m, row.y_local_m, row.z_local_m)
        if key not in first_appearance:
            first_appearance.append(key)
    assert list(zip(frame["x_local_m"], frame["y_local_m"], frame["z_local_m"])) == first_appearance


def test_derivation_report_declares_rules_counts_and_gates(fixture_config, tmp_path):
    _, outputs = derive_from_directory(fixture_config, fixture_config.data_dir, tmp_path / "out")
    report = json.loads(outputs["derivation_report"].read_text(encoding="utf-8"))
    assert report["rule_version"] == fixture_config.derivation.rule_version
    assert report["adapter_version"] == fixture_config.derivation.adapter_version
    assert report["aggregation_method"] == "arithmetic_mean_exact_xyz"
    assert report["layer_counts"] == {
        "source_records": 7,
        "finite_records": 6,
        "invalid_records": 1,
        "rejected_3sigma": 0,
        "accepted_modeling": 6,
        "aggregated_nodes": 6,
    }
    assert report["golden"]["passed"] is True
    assert report["validation_passed"] is True
    assert report["downstream_gates"] == {
        "geometry_blocked": False,
        "cleaning_blocked": False,
        "interpolation_blocked": False,
    }
    assert report["coordinates"]["depth_rule"] == "DEPTH_M=WL_HALF_KM*1000;down_positive"
    assert report["coordinates"]["z_rule"] == "Z_LOCAL_M=-DEPTH_M;up_positive"
    assert report["coordinates"]["vx_unit"] == "km/s"
    assert "1-based" in report["source_row_rule"]
    assert report["artifacts"]["accepted_modeling"]["rows"] == 6
    assert report["artifacts"]["accepted_modeling"]["sha256"] == fixture_config.derivation.golden.accepted_sha256


def test_derive_accepts_explicit_source_dir(fixture_config, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    for path in fixture_config.data_dir.glob("*.dat"):
        (elsewhere / path.name).write_bytes(path.read_bytes())
    result, _ = derive_from_directory(fixture_config, elsewhere, tmp_path / "out")
    assert result.validation.passed is True
    assert result.audit.counts["source_record_total"] == 7


def test_derive_golden_failure_still_exports_and_blocks(fixture_config, tmp_path):
    broken = fixture_config.model_copy(
        update={"derivation": fixture_config.derivation.model_copy(update={"expected_accepted": 999})}
    )
    result, outputs = derive_from_directory(broken, fixture_config.data_dir, tmp_path / "out")
    assert result.golden.passed is False
    assert result.validation.passed is False
    assert result.downstream_gates == {
        "geometry_blocked": True,
        "cleaning_blocked": True,
        "interpolation_blocked": True,
    }
    assert outputs["accepted_modeling"].is_file()
    assert outputs["derivation_report"].is_file()


def test_cli_derive_success_prints_layer_counts(tmp_path: Path):
    data_dir = write_fixture_tree(tmp_path)
    config_path = write_fixture_config(tmp_path, data_dir)
    out_dir = tmp_path / "out"
    completed = runner.invoke(
        app,
        ["microseismic", "derive", "--config", str(config_path), "--source-dir", str(data_dir), "-o", str(out_dir)],
    )
    assert completed.exit_code == 0, completed.output
    assert "source_records=7" in completed.output
    assert "finite=6" in completed.output
    assert "invalid=1" in completed.output
    assert "rejected_3sigma=0" in completed.output
    assert "accepted_modeling=6" in completed.output
    assert "modeling_nodes=6" in completed.output
    assert "golden_passed=True" in completed.output
    assert (out_dir / "derivation_report.json").is_file()
    assert (out_dir / "modeling_provenance.parquet").is_file()


def test_cli_derive_wrong_file_set_exits_1_but_writes_diagnostics(tmp_path: Path):
    data_dir = write_fixture_tree(tmp_path)
    write_dat(data_dir / "WX.dat", ["        0.100000        1.000000"])
    config_path = write_fixture_config(tmp_path, data_dir)
    out_dir = tmp_path / "out"
    completed = runner.invoke(
        app,
        ["microseismic", "derive", "--config", str(config_path), "--source-dir", str(data_dir), "-o", str(out_dir)],
    )
    assert completed.exit_code == 1
    assert "validation_passed=False" in completed.output
    report_path = out_dir / "derivation_report.json"
    assert report_path.is_file()
    assert (out_dir / "accepted_modeling_6.csv").is_file()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["validation_passed"] is False
    assert report["downstream_gates"] == {
        "geometry_blocked": True,
        "cleaning_blocked": True,
        "interpolation_blocked": True,
    }


def test_cli_run_audit_exports_v05_derivation_layers(tmp_path: Path):
    data_dir = write_fixture_tree(tmp_path)
    config_path = write_fixture_config(tmp_path, data_dir)
    out_dir = tmp_path / "out"
    completed = runner.invoke(app, ["microseismic", "run-audit", "--config", str(config_path), "-o", str(out_dir)])
    assert completed.exit_code == 0, completed.output
    # Old audit artifacts keep their file names.
    assert (out_dir / "velocity_samples.csv").is_file()
    assert (out_dir / "microseismic_validation.json").is_file()
    # The confirmed v0.5 contract appends the derivation layers.
    assert (out_dir / "accepted_modeling_6.csv").is_file()
    assert (out_dir / "rejected_3sigma_0.csv").is_file()
    assert (out_dir / "aggregated_nodes_6.csv").is_file()
    assert (out_dir / "modeling_provenance.parquet").is_file()
    assert (out_dir / "derivation_report.json").is_file()


def test_run_audit_reports_state_confirmed_facts(tmp_path: Path):
    data_dir = write_fixture_tree(tmp_path)
    config_path = write_fixture_config(tmp_path, data_dir)
    out_dir = tmp_path / "out"
    completed = runner.invoke(app, ["microseismic", "run-audit", "--config", str(config_path), "-o", str(out_dir)])
    assert completed.exit_code == 0, completed.output
    summary = (out_dir / "microseismic_audit_summary.md").read_text(encoding="utf-8")
    assert "geometry_blocked: False" in summary
    assert "cleaning_blocked: False" in summary
    assert "interpolation_blocked: False" in summary
    quality = (out_dir / "microseismic_data_quality.md").read_text(encoding="utf-8")
    assert "cannot: reconstruct 2D/3D coordinates" not in quality


def test_derive_fails_closed_on_insufficient_finite_rows(tmp_path: Path):
    # 全包只有 1 条有限记录（<= sigma_ddof=1）：派生必须在进入 3σ 统计前
    # 收口为结构化 PlatformError（API/适配器路径得 4xx 封套），
    # 绝不让裸 ZeroDivisionError 以 500 收场。
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    write_dat(data_dir / "W1.dat", ["        0.050000        0.524804"])
    write_dat(data_dir / "W2.dat", ["        0.050000        1.#QNAN0"])
    write_dat(data_dir / "WA.dat", ["        0.100000        1.#QNAN0"], trailing_nul=False)
    config = load_microseismic_config(write_fixture_config(tmp_path, data_dir))
    with pytest.raises(PlatformError) as excinfo:
        derive_from_directory(config, data_dir, tmp_path / "out")
    error = excinfo.value
    assert error.code == "MICROSEISMIC_INSUFFICIENT_FINITE"
    assert error.http_status == 422
    assert error.details["finite_total"] == 1
    assert error.details["ddof"] == config.derivation.sigma_ddof
