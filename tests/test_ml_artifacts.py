from __future__ import annotations

import json

import numpy as np
import pytest

from geomodeling.platform.errors import PlatformError
from geomodeling.platform.ml_artifacts import (
    load_ml_field,
    read_ml_fields_manifest,
    write_ml_fields,
)


def _axes():
    return (np.arange(2.0), np.arange(3.0), np.arange(4.0))


def test_random_forest_fields_round_trip_with_grid_binding(tmp_path):
    values = np.arange(24, dtype="float64").reshape(2, 3, 4) / 10
    manifest = write_ml_fields(
        tmp_path,
        algorithm="random_forest_spatial",
        axes=_axes(),
        fields={"model_dispersion": values},
        main_grid_sha256="a" * 64,
        property_unit="km/s",
    )

    assert manifest["main_grid_sha256"] == "a" * 64
    assert list(manifest["fields"]) == ["model_dispersion"]
    assert len(manifest["fields"]["model_dispersion"]["sha256"]) == 64
    loaded, nodata = load_ml_field(tmp_path, "model_dispersion", expected_grid_sha256="a" * 64)
    assert np.array_equal(loaded, values)
    assert not nodata.any()


def test_residual_fields_require_exact_shape_and_semantics(tmp_path):
    shape = (2, 3, 4)
    baseline = np.full(shape, 10.0)
    correction = np.linspace(-1.0, 1.0, 24).reshape(shape)
    dispersion = np.full(shape, 0.25)

    manifest = write_ml_fields(
        tmp_path,
        algorithm="kriging_rf_residual",
        axes=_axes(),
        fields={
            "model_dispersion": dispersion,
            "kriging_baseline": baseline,
            "residual_correction": correction,
        },
        main_grid_sha256="b" * 64,
        property_unit="Ω·m",
    )

    assert set(manifest["fields"]) == {
        "model_dispersion",
        "kriging_baseline",
        "residual_correction",
    }
    assert manifest["fields"]["residual_correction"]["palette_intent"] == "diverging_zero_centered"
    with pytest.raises(PlatformError) as caught:
        write_ml_fields(
            tmp_path / "bad",
            algorithm="kriging_rf_residual",
            axes=_axes(),
            fields={"model_dispersion": np.zeros((2, 2, 2))},
            main_grid_sha256="b" * 64,
            property_unit="Ω·m",
        )
    assert caught.value.code == "ML_ARTIFACT_INVALID"


def test_corrupt_field_or_grid_identity_fails_closed(tmp_path):
    write_ml_fields(
        tmp_path,
        algorithm="random_forest_spatial",
        axes=_axes(),
        fields={"model_dispersion": np.ones((2, 3, 4))},
        main_grid_sha256="c" * 64,
        property_unit=None,
    )
    (tmp_path / "ml_fields.npz").write_bytes(b"corrupt")

    with pytest.raises(PlatformError) as caught:
        read_ml_fields_manifest(tmp_path, expected_grid_sha256="c" * 64)
    assert caught.value.code == "ML_ARTIFACT_INVALID"

    manifest = json.loads((tmp_path / "ml_fields.json").read_text(encoding="utf-8"))
    assert manifest["main_grid_sha256"] == "c" * 64


def test_nonfinite_values_must_be_declared_nodata(tmp_path):
    values = np.ones((2, 3, 4))
    values[0, 0, 0] = np.nan
    with pytest.raises(PlatformError) as caught:
        write_ml_fields(
            tmp_path,
            algorithm="random_forest_spatial",
            axes=_axes(),
            fields={"model_dispersion": values},
            main_grid_sha256="d" * 64,
            property_unit=None,
        )
    assert caught.value.code == "ML_ARTIFACT_INVALID"

    manifest = write_ml_fields(
        tmp_path / "declared",
        algorithm="random_forest_spatial",
        axes=_axes(),
        fields={"model_dispersion": values},
        nodata={"model_dispersion": ~np.isfinite(values)},
        main_grid_sha256="d" * 64,
        property_unit=None,
    )
    loaded, mask = load_ml_field(
        tmp_path / "declared", "model_dispersion", expected_grid_sha256="d" * 64
    )
    assert manifest["fields"]["model_dispersion"]["nodata_count"] == 1
    assert mask.sum() == 1
    assert np.isnan(loaded[0, 0, 0])
