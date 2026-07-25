from pathlib import Path

from geomodeling.microseismic.config import load_microseismic_config

from microseismic_fixtures import write_fixture_config, write_fixture_tree

REAL_ACCEPTED_SHA256 = "4f7a0886b54bb1776e9d7ca98299f8f86e67897ba19236fb151c3fc9e2ae1513"
REAL_REJECTED_SHA256 = "3752b2f62de4e56121b7af66c205ccf3984270d332636335e559e7e2745872b1"


def test_v05_config_has_complete_local_geometry_and_rules():
    config = load_microseismic_config()
    coordinates = config.coordinate_lookup()
    assert len(coordinates) == 22
    assert coordinates["W16"] == (0.0, 0.0)
    assert coordinates["W5"] == (0.0, 220.0)
    assert coordinates["W24"] == (960.0, 0.0)
    assert "W28" not in coordinates
    assert config.derivation.sigma_ddof == 1
    assert config.derivation.sigma_threshold == 3
    assert config.derivation.aggregation_method == "arithmetic_mean_exact_xyz"
    assert config.derivation.golden.accepted_sha256 == (
        "4f7a0886b54bb1776e9d7ca98299f8f86e67897ba19236fb151c3fc9e2ae1513"
    )
    assert config.derivation.expected_modeling_nodes == 1911


def test_with_data_dir_redirects_source_without_mutating_original(tmp_path: Path):
    config = load_microseismic_config()
    redirected = config.with_data_dir(tmp_path / "bundle")
    assert redirected.data_dir == (tmp_path / "bundle").resolve()
    assert redirected.source["data_dir"] == str((tmp_path / "bundle").resolve())
    assert config.data_dir != redirected.data_dir
    assert redirected.coordinate_lookup() == config.coordinate_lookup()


def test_fixture_config_has_fixture_specific_derivation_contract(tmp_path: Path):
    data_dir = write_fixture_tree(tmp_path)
    config_path = write_fixture_config(tmp_path, data_dir)
    config = load_microseismic_config(config_path)
    coordinates = config.coordinate_lookup()
    assert set(coordinates) == {"W1", "W2", "WA"}
    assert "W99" not in coordinates
    derivation = config.derivation
    # Counts follow the fixture's own 7 source rows (6 finite), not the real
    # 2006/1925/80/1911 contract.
    assert derivation.expected_rejected == 0
    assert derivation.expected_accepted == 6
    assert derivation.expected_conflict_groups == 0
    assert derivation.expected_conflict_rows == 0
    assert derivation.expected_modeling_nodes == 6
    assert derivation.golden.accepted_sha256 != REAL_ACCEPTED_SHA256
    assert derivation.golden.rejected_sha256 != REAL_REJECTED_SHA256
