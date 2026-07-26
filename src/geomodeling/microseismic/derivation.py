from __future__ import annotations

from .config import MicroseismicConfig
from .schemas import (
    DerivationContractError,
    DerivedVelocitySample,
    InvalidDerivedSample,
    MicroseismicAuditResult,
)

__all__ = ["DerivationContractError", "derive_local_samples"]


def derive_local_samples(
    config: MicroseismicConfig,
    audit: MicroseismicAuditResult,
) -> tuple[list[DerivedVelocitySample], list[InvalidDerivedSample]]:
    """Convert finite v0.2a audit samples to confirmed local XYZ/Vx rows.

    depth_m = wl_half_km * depth_multiplier (positive down, for analysis);
    z_local_m = depth_m * z_multiplier (positive up, for 3D display).
    Non-finite source records keep their raw tokens in the invalid layer and
    never enter statistics. The immutable audit samples are never mutated.
    """
    coordinates = config.coordinate_lookup()
    finite: list[DerivedVelocitySample] = []
    invalid: list[InvalidDerivedSample] = []
    for sample in audit.samples:
        if not sample.is_numeric_valid:
            invalid.append(
                InvalidDerivedSample.from_source(sample, rule_version=config.derivation.rule_version)
            )
            continue
        x, y = coordinates[sample.point_id]
        depth = float(sample.wl_half_km_value) * config.derivation.depth_multiplier
        finite.append(
            DerivedVelocitySample.from_source(
                sample,
                x=x,
                y=y,
                depth=depth,
                z=depth * config.derivation.z_multiplier,
                rule_version=config.derivation.rule_version,
            )
        )
    return finite, invalid
