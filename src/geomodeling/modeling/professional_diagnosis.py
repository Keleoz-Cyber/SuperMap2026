"""Bounded anisotropy candidate suggestions from directional fits (design §7.1).

``suggest_anisotropy`` 只比较 ``supported`` 方向拟合，按拟合 range 从长到
短取至多 3 个候选主方向；每个候选披露次方向（无向方位角最接近主方向
+90° 的水平方向）、垂向方向（3D，|dip| ≥ 45° 中倾角最大者）、range 比
例、使用的方向 bin 与点对数、稳定性警告。候选 ``status`` 恒为
``diagnostic_suggestion`` —— 平台不自动宣称地质主方向、不写确认记录、
不改实验参数；确认（或「保持各向同性」）是后续任务的显式用户操作。
``unsupported_insufficient_pairs`` 方向只披露、不参与比较（§17 禁止静默
改全向或外推主方向）。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from geomodeling.modeling.professional_contracts import DirectionSpec
from geomodeling.modeling.variogram import VariogramFitEvidence
from geomodeling.platform.schemas import ContractModel, Dimension

__all__ = [
    "STATUS_DIAGNOSTIC_SUGGESTION",
    "STATUS_SUPPORTED",
    "STATUS_UNSUPPORTED_INSUFFICIENT_PAIRS",
    "WARN_NO_SUPPORTED_DIRECTION",
    "WARN_RANGE_AT_UPPER_BOUND",
    "WARN_SINGLE_SUPPORTED_DIRECTION",
    "WARN_VERTICAL_UNSUPPORTED",
    "WARN_WEAK_RANGE_CONTRAST",
    "AnisotropyCandidate",
    "AnisotropySuggestion",
    "DirectionalFit",
    "suggest_anisotropy",
]

STATUS_SUPPORTED = "supported"
STATUS_UNSUPPORTED_INSUFFICIENT_PAIRS = "unsupported_insufficient_pairs"
STATUS_DIAGNOSTIC_SUGGESTION = "diagnostic_suggestion"

WARN_NO_SUPPORTED_DIRECTION = "no_supported_direction"
WARN_SINGLE_SUPPORTED_DIRECTION = "single_supported_direction"
WARN_VERTICAL_UNSUPPORTED = "vertical_direction_unsupported"
WARN_RANGE_AT_UPPER_BOUND = "range_at_disclosed_upper_bound"
WARN_WEAK_RANGE_CONTRAST = "weak_range_contrast"

#: 候选数量硬上限（§18：参数组合设硬上限）。
_MAX_CANDIDATES = 3
#: 垂向角色门槛：|dip| ≥ 45° 的方向才可作为垂向候选。
_VERTICAL_DIP_MIN_DEG = 45.0
#: range 比例低于该值视为弱各向异性对比（稳定性警告）。
_WEAK_CONTRAST_RATIO = 1.25
#: range 达到披露上界（相对容差）视为滞后窗内不可识别。
_UPPER_BOUND_REL_TOL = 1e-9


class DirectionalFit(ContractModel):
    """单个方向的拟合披露：``supported`` 携带证据，``unsupported`` 仅披露。

    ``direction_id`` 是调用方分配的稳定身份（如 ``az000``/``v000``），
    候选通过它回指来源方向；``used_pair_count`` 为该方向进入拟合的点对
    总数（unsupported 时为实际不足的点对数）。
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True, frozen=True)

    direction_id: str = Field(min_length=1)
    direction: DirectionSpec
    status: Literal["supported", "unsupported_insufficient_pairs"]
    fit: VariogramFitEvidence | None
    used_pair_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_fit(self) -> "DirectionalFit":
        if self.status == STATUS_SUPPORTED and self.fit is None:
            raise ValueError("supported 方向必须携带拟合证据")
        if self.status == STATUS_UNSUPPORTED_INSUFFICIENT_PAIRS and self.fit is not None:
            raise ValueError("unsupported 方向不得携带拟合证据")
        return self


class AnisotropyCandidate(ContractModel):
    """单条各向异性假设的不可变披露（§7.1）；恒为诊断建议，从不确认。

    ``major_*`` 为候选主方向（该候选内拟合 range 最长者）；
    ``secondary_*``/``vertical_*`` 披露次方向与垂向支持（无支持方向时
    为 None/0）；``major_minor_range_ratio``/``major_vertical_range_ratio``
    为主方向 range 与次/垂向 range 之比（无比较方向时为 None）。
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True, frozen=True)

    status: Literal["diagnostic_suggestion"] = STATUS_DIAGNOSTIC_SUGGESTION
    rank: int = Field(ge=1)
    major_direction_id: str
    major_azimuth_deg: float
    major_dip_deg: float | None
    major_range: float = Field(gt=0)
    secondary_direction_id: str | None
    secondary_range: float | None
    secondary_support_pairs: int = Field(ge=0)
    vertical_direction_id: str | None
    vertical_range: float | None
    vertical_support_pairs: int = Field(ge=0)
    major_minor_range_ratio: float | None
    major_vertical_range_ratio: float | None
    used_direction_ids: list[str]
    used_bin_indices: list[int]
    used_pair_count: int = Field(ge=0)
    warnings: list[str]


class AnisotropySuggestion(ContractModel):
    """方向拟合比较结果：至多 3 个候选 + 参与/跳过方向披露。

    本记录只是建议：不包含确认字段，不产生实验参数变更。
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True, frozen=True)

    candidates: list[AnisotropyCandidate] = Field(max_length=_MAX_CANDIDATES)
    compared_direction_ids: list[str]
    skipped_direction_ids: list[str]
    warnings: list[str]


def _undirected_azimuth_separation(a: float, b: float) -> float:
    """无向方位角夹角（度），范围 [0, 90]。"""

    return abs((a - b + 90.0) % 180.0 - 90.0)


def _is_vertical(direction: DirectionSpec) -> bool:
    return direction.dip_deg is not None and abs(float(direction.dip_deg)) >= _VERTICAL_DIP_MIN_DEG


def _range_at_disclosed_upper_bound(fit: VariogramFitEvidence) -> bool:
    upper = fit.bounds["range"][1]
    return fit.range >= upper * (1.0 - _UPPER_BOUND_REL_TOL)


def suggest_anisotropy(direction_fits: Sequence[DirectionalFit]) -> AnisotropySuggestion:
    """比较 supported 方向拟合，返回至多 3 个诊断候选（§7.1）。

    纯函数：不写确认记录、不改实验参数、不修改输入。候选主方向按拟合
    range 降序（等长按 ``direction_id`` 稳定排序）；次方向为无向方位角
    最接近主方向 +90° 的水平 supported 方向（等距时取 range 较短者）；
    垂向为 |dip| ≥ 45° 的 supported 方向中倾角最大者（仅 3D）。
    """

    fits = list(direction_fits)
    supported = [f for f in fits if f.status == STATUS_SUPPORTED]
    skipped = [f.direction_id for f in fits if f.status != STATUS_SUPPORTED]
    compared = [f.direction_id for f in supported]
    if not supported:
        return AnisotropySuggestion(
            candidates=[],
            compared_direction_ids=[],
            skipped_direction_ids=skipped,
            warnings=[WARN_NO_SUPPORTED_DIRECTION],
        )

    ranked = sorted(supported, key=lambda f: (-f.fit.range, f.direction_id))
    candidates: list[AnisotropyCandidate] = []
    for rank, major in enumerate(ranked[:_MAX_CANDIDATES], start=1):
        others = [f for f in supported if f.direction_id != major.direction_id]
        is_3d = major.direction.dimension == Dimension.THREE_D
        secondary = min(
            (f for f in others if not _is_vertical(f.direction)),
            key=lambda f: (
                _undirected_azimuth_separation(
                    f.direction.azimuth_deg, major.direction.azimuth_deg + 90.0
                ),
                f.fit.range,
                f.direction_id,
            ),
            default=None,
        )
        vertical = (
            min(
                (f for f in others if _is_vertical(f.direction)),
                key=lambda f: (-abs(float(f.direction.dip_deg)), f.direction_id),
                default=None,
            )
            if is_3d
            else None
        )
        used = [major] + [f for f in (secondary, vertical) if f is not None]
        minor_ratio = (
            major.fit.range / secondary.fit.range if secondary is not None else None
        )
        vertical_ratio = (
            major.fit.range / vertical.fit.range if vertical is not None else None
        )

        warnings: list[str] = []
        if len(supported) == 1:
            warnings.append(WARN_SINGLE_SUPPORTED_DIRECTION)
        if is_3d and vertical is None:
            warnings.append(WARN_VERTICAL_UNSUPPORTED)
        if any(_range_at_disclosed_upper_bound(f.fit) for f in used):
            warnings.append(WARN_RANGE_AT_UPPER_BOUND)
        present_ratios = [r for r in (minor_ratio, vertical_ratio) if r is not None]
        if present_ratios and max(present_ratios) < _WEAK_CONTRAST_RATIO:
            warnings.append(WARN_WEAK_RANGE_CONTRAST)

        candidates.append(
            AnisotropyCandidate(
                rank=rank,
                major_direction_id=major.direction_id,
                major_azimuth_deg=float(major.direction.azimuth_deg),
                major_dip_deg=(
                    float(major.direction.dip_deg)
                    if major.direction.dip_deg is not None
                    else None
                ),
                major_range=major.fit.range,
                secondary_direction_id=(
                    secondary.direction_id if secondary is not None else None
                ),
                secondary_range=secondary.fit.range if secondary is not None else None,
                secondary_support_pairs=(
                    secondary.used_pair_count if secondary is not None else 0
                ),
                vertical_direction_id=(
                    vertical.direction_id if vertical is not None else None
                ),
                vertical_range=vertical.fit.range if vertical is not None else None,
                vertical_support_pairs=(
                    vertical.used_pair_count if vertical is not None else 0
                ),
                major_minor_range_ratio=minor_ratio,
                major_vertical_range_ratio=vertical_ratio,
                used_direction_ids=[f.direction_id for f in used],
                used_bin_indices=list(major.fit.used_bin_indices),
                used_pair_count=sum(f.used_pair_count for f in used),
                warnings=warnings,
            )
        )
    return AnisotropySuggestion(
        candidates=candidates,
        compared_direction_ids=compared,
        skipped_direction_ids=skipped,
        warnings=[],
    )
