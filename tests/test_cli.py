import pytest
from typer.testing import CliRunner

from geomodeling.cli import app

pytestmark = pytest.mark.local_data

runner = CliRunner()


def test_cli_help_lists_professional_group():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "professional" in result.output


def test_cli_validate_data(tmp_path):
    result = runner.invoke(app, ["validate-data", "-o", str(tmp_path / "validate")])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "validate" / "registry" / "datasets" / "rho_standardized_v1.json").exists()
    assert (tmp_path / "validate" / "reports" / "train_validation_split.json").exists()


def test_cli_compute_metrics(tmp_path):
    result = runner.invoke(app, ["compute-metrics", "-o", str(tmp_path / "metrics")])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "metrics" / "metrics" / "metric_summaries.json").exists()
    assert (tmp_path / "metrics" / "reports" / "metric_summaries.md").exists()


def test_cli_register_supermap_results(tmp_path):
    result = runner.invoke(app, ["register-supermap-results", "-o", str(tmp_path / "supermap"), "--udbx-path", "D:/data/expore1.udbx"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "supermap" / "registry" / "supermap" / "RHO_KRIG_FINAL_20M_40.json").exists()
    assert (tmp_path / "supermap" / "reports" / "supermap_result_inventory.md").exists()


def test_cli_microseismic_derive_real_data(tmp_path):
    result = runner.invoke(app, ["microseismic", "derive", "-o", str(tmp_path / "derive")])
    assert result.exit_code == 0, result.output
    assert "source_records=2006" in result.output
    assert "finite=2005" in result.output
    assert "invalid=1" in result.output
    assert "rejected_3sigma=80" in result.output
    assert "accepted_modeling=1925" in result.output
    assert "modeling_nodes=1911" in result.output
    assert "golden_passed=True" in result.output
    out_dir = tmp_path / "derive"
    assert (out_dir / "source_records_2006.csv").is_file()
    assert (out_dir / "invalid_records_1.csv").is_file()
    assert (out_dir / "rejected_3sigma_80.csv").is_file()
    assert (out_dir / "accepted_modeling_1925.csv").is_file()
    assert (out_dir / "aggregated_nodes_1911.csv").is_file()
    assert (out_dir / "modeling_provenance.parquet").is_file()
    assert (out_dir / "derivation_report.json").is_file()
