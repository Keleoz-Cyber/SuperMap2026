"""v0.7.0 Batch 2 Task 2：来源驱动的渲染默认值（render_profile）。

``render_profile`` 是根据来源登记信息和权威网格摘要计算的公开 DTO（不新增
可漂移的持久化副本）：

- ``builtin_legacy``（内置电阻率登记元数据）默认 ``log`` + ``native-spectrum``；
- 其余来源（候选成果，含微震预置与用户上传）默认 ``linear`` + ``viridis``；
- 权威有效值不全为正时 ``log_available=False``，对数请求降级为 linear，
  绝不丢弃或平移 <=0 的原始值强行开启；
- 色带只能是固定版本化 ID（前端唯一定义颜色节点），未知 ID/来源类型
  fail-closed。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from geomodeling.platform.errors import PlatformError

RENDER_PROFILE_INVALID = "RENDER_PROFILE_INVALID"

PaletteId = Literal["native-spectrum", "viridis", "turbo", "coolwarm", "grayscale"]
ScaleMode = Literal["linear", "log"]

PALETTE_IDS = ("native-spectrum", "viridis", "turbo", "coolwarm", "grayscale")

_SOURCE_DEFAULTS: dict[str, tuple[ScaleMode, PaletteId]] = {
    "builtin_legacy": ("log", "native-spectrum"),
    "candidate_result": ("linear", "viridis"),
}


@dataclass(frozen=True)
class RenderProfile:
    property_name: str
    unit: str
    default_scale: ScaleMode
    default_palette: PaletteId
    log_available: bool
    value_range: tuple[float, float]
    filter_range: tuple[float, float]
    lighting: bool = True
    gradient_opacity: bool = True
    bounding_box: bool = True
    opacity: float = 1.0

    def to_public(self) -> dict[str, Any]:
        """公共 DTO：值域用 JSON 数组形态（无元组）。"""

        payload = asdict(self)
        payload["value_range"] = [self.value_range[0], self.value_range[1]]
        payload["filter_range"] = [self.filter_range[0], self.filter_range[1]]
        return payload


def build_render_profile(
    source_kind: str,
    valid_min: float,
    valid_max: float,
    *,
    property_name: str,
    unit: str | None,
) -> RenderProfile:
    """按来源类型与权威有效值域构造默认值；输入异常 fail-closed。"""

    if source_kind not in _SOURCE_DEFAULTS:
        raise PlatformError(
            RENDER_PROFILE_INVALID,
            "不支持的渲染来源类型",
            {"source_kind": source_kind},
            http_status=409,
        )
    lo, hi = float(valid_min), float(valid_max)
    if not (lo == lo and hi == hi) or not (lo < hi):
        raise PlatformError(
            RENDER_PROFILE_INVALID,
            "权威有效值域必须有限且严格递增",
            {"valid_min": valid_min, "valid_max": valid_max},
            http_status=409,
        )
    log_available = lo > 0
    requested, palette = _SOURCE_DEFAULTS[source_kind]
    scale: ScaleMode = requested if requested != "log" or log_available else "linear"
    return RenderProfile(
        property_name=property_name,
        unit=unit or "unknown",
        default_scale=scale,
        default_palette=palette,
        log_available=log_available,
        value_range=(lo, hi),
        filter_range=(lo, hi),
    )
