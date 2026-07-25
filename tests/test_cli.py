import pytest
from typer.testing import CliRunner

from geomodeling.cli import app

pytestmark = pytest.mark.local_data

runner = CliRunner()


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

