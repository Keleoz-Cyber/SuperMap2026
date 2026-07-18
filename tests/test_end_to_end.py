import pytest
from typer.testing import CliRunner

from geomodeling.cli import app

pytestmark = pytest.mark.local_data

runner = CliRunner()


def test_run_all_end_to_end(tmp_path):
    output = tmp_path / "e2e"
    result = runner.invoke(app, ["run-all", "-o", str(output), "--udbx-path", "D:/data/expore1.udbx"])
    assert result.exit_code == 0, result.output
    assert (output / "registry" / "datasets" / "rho_standardized_v1.validation.json").exists()
    assert (output / "metrics" / "metric_summaries.json").exists()
    assert (output / "registry" / "supermap" / "RHO_ISO_77_K40.json").exists()
    assert (output / "reports" / "metric_summaries.md").exists()
    assert (output / "reports" / "supermap_result_inventory.json").exists()
    assert (output / "reports" / "models" / "rho_kriging_20m_n40_v1.json").exists()
