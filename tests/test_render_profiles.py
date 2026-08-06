"""v0.7.0 Batch 2 Task 2：来源驱动的渲染默认值（render_profile）。"""

from __future__ import annotations

import pytest

from geomodeling.platform.errors import PlatformError
from geomodeling.platform.render_profiles import (
    PALETTE_IDS,
    build_render_profile,
)


def test_legacy_defaults_to_log_and_candidate_defaults_to_linear():
    rho = build_render_profile(
        "builtin_legacy", 1.0, 1000.0, property_name="RHO", unit="ohm-m"
    )
    uploaded = build_render_profile(
        "candidate_result", 1.0, 1000.0, property_name="Vx", unit="km/s"
    )
    assert (rho.default_scale, rho.default_palette) == ("log", "native-spectrum")
    assert (uploaded.default_scale, uploaded.default_palette) == ("linear", "viridis")


def test_nonpositive_values_disable_log_without_changing_range():
    profile = build_render_profile(
        "candidate_result", -2.0, 8.0, property_name="value", unit="unknown"
    )
    assert profile.log_available is False
    assert profile.value_range == (-2.0, 8.0)
    assert profile.filter_range == (-2.0, 8.0)


def test_legacy_log_degrades_to_linear_when_unavailable():
    profile = build_render_profile(
        "builtin_legacy", 0.0, 100.0, property_name="RHO", unit="unknown"
    )
    assert profile.log_available is False
    assert profile.default_scale == "linear"
    assert profile.default_palette == "native-spectrum"


def test_profile_defaults_and_public_shape():
    profile = build_render_profile(
        "builtin_legacy", 1.0, 100.0, property_name="RHO", unit="unknown"
    )
    assert profile.lighting is True
    assert profile.gradient_opacity is True
    assert profile.bounding_box is True
    assert profile.opacity == 1.0
    payload = profile.to_public()
    assert payload["property_name"] == "RHO"
    assert payload["unit"] == "unknown"
    assert payload["default_palette"] in PALETTE_IDS
    assert payload["value_range"] == [1.0, 100.0]
    assert payload["filter_range"] == [1.0, 100.0]
    assert payload["log_available"] is True


def test_invalid_range_or_source_kind_fails_closed():
    with pytest.raises(PlatformError):
        build_render_profile("candidate_result", 5.0, 5.0, property_name="v", unit="u")
    with pytest.raises(PlatformError):
        build_render_profile("mystery", 1.0, 5.0, property_name="v", unit="u")
    with pytest.raises(PlatformError):
        build_render_profile("candidate_result", float("nan"), 5.0, property_name="v", unit="u")
