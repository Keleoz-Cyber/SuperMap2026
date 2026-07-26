from collections import Counter
from pathlib import Path

import pytest

from geomodeling.microseismic.config import load_microseismic_config
from geomodeling.microseismic.derivation import DerivationContractError, derive_local_samples
from geomodeling.microseismic.schemas import DerivedVelocitySample, VelocitySample
from geomodeling.microseismic.service import build_audit

from microseismic_fixtures import write_fixture_config, write_fixture_tree


@pytest.fixture()
def fixture_config(tmp_path: Path):
    data_dir = write_fixture_tree(tmp_path)
    config_path = write_fixture_config(tmp_path, data_dir)
    return load_microseismic_config(config_path)


@pytest.fixture()
def fixture_audit(fixture_config):
    return build_audit(fixture_config)


def test_finite_sample_derives_confirmed_local_xyz(fixture_audit, fixture_config):
    finite, invalid = derive_local_samples(fixture_config, fixture_audit)
    row = next(item for item in finite if item.sample_id == "W1:2")
    assert (row.x_local_m, row.y_local_m) == fixture_config.coordinate_lookup()["W1"]
    assert row.depth_m == pytest.approx(row.wl_half_km * 1000)
    assert row.z_local_m == pytest.approx(-row.depth_m)
    assert row.vx_unit == "km/s"
    assert row.source_file == "W1.dat"
    assert row.source_line == 2
    assert len(invalid) == 1
    assert invalid[0].vx_raw_token == "1.#QNAN0"


def test_layer_counts_and_per_line_split(fixture_audit, fixture_config):
    finite, invalid = derive_local_samples(fixture_config, fixture_audit)
    assert len(finite) == 6
    assert len(invalid) == 1
    assert dict(Counter(item.line_id for item in finite)) == {"L1": 4, "L2": 2}
    rejected = invalid[0]
    assert rejected.sample_id == "W2:2"
    assert rejected.point_id == "W2"
    assert rejected.source_file == "W2.dat"
    assert rejected.source_line == 2
    assert rejected.wl_half_km_raw_token == "0.050000"
    assert rejected.vx_raw_token == "1.#QNAN0"
    assert rejected.is_valid is False


def test_excluded_point_never_enters_samples(fixture_audit, fixture_config):
    # The fixture conflict-only point W99 mirrors the real W28 registration.
    finite, invalid = derive_local_samples(fixture_config, fixture_audit)
    assert "W99" not in {item.point_id for item in finite}
    assert "W99" not in {item.point_id for item in invalid}
    formal_ids = set(fixture_config.formal_point_ids())
    assert {item.point_id for item in finite} <= formal_ids


def test_every_formal_point_has_exactly_one_confirmed_coordinate(fixture_audit, fixture_config):
    finite, _ = derive_local_samples(fixture_config, fixture_audit)
    coordinates = fixture_config.coordinate_lookup()
    formal_ids = fixture_config.formal_point_ids()
    assert len(formal_ids) == len(set(formal_ids))
    assert set(formal_ids) <= set(coordinates)
    assert {item.point_id for item in finite} == set(formal_ids)
    for item in finite:
        assert (item.x_local_m, item.y_local_m) == coordinates[item.point_id]


def test_source_traceability_and_rule_metadata(fixture_audit, fixture_config):
    finite, invalid = derive_local_samples(fixture_config, fixture_audit)
    source_by_id = {sample.sample_id: sample for sample in fixture_audit.samples}
    assert len(finite) + len(invalid) == len(fixture_audit.samples)
    for item in [*finite, *invalid]:
        source = source_by_id[item.sample_id]
        assert item.source_file == source.source_file_name
        assert item.source_line == source.source_line_number
        assert item.vx_raw_token == source.vx_raw_token
    for item in finite:
        assert item.coord_type == "local_engineering_m"
        assert item.is_valid is True
        assert item.depth_rule == "DEPTH_M=WL_HALF_KM*1000;down_positive"
        assert item.z_rule == "Z_LOCAL_M=-DEPTH_M;up_positive"
        assert item.rule_version == fixture_config.derivation.rule_version


def test_audit_source_layer_remains_immutable(fixture_audit, fixture_config):
    derive_local_samples(fixture_config, fixture_audit)
    assert all(sample.derived_depth_m is None and sample.derived_z_m is None for sample in fixture_audit.samples)
    assert all(sample.depth_derivation_status == "unconfirmed" for sample in fixture_audit.samples)


def test_from_source_raises_contract_error_on_missing_finite_value():
    sample = VelocitySample(
        sample_id="W1:2",
        point_id="W1",
        line_id="L1",
        source_file_id="microseismic_dat_W1",
        source_file_name="W1.dat",
        source_line_number=2,
        wl_half_km_raw_token="0.050000",
        vx_raw_token=None,
        wl_half_km_value=0.05,
        vx_value=None,
        source_unit="WL/2(km); Vx km/s",
        is_numeric_valid=True,
    )
    with pytest.raises(DerivationContractError):
        DerivedVelocitySample.from_source(sample, x=0.0, y=220.0, depth=50.0, z=-50.0, rule_version="test")
