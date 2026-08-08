"""v0.8.0 第二批：分析 profile 领域注册表。

按 dataset ``profile_json.mapping`` 的 ``value_name``/``value_unit``/字段名/
``dimension`` 判定可启用的专属分析模块，**绝不使用 case_id**（设计 §4：
前端按 profile 渲染，不按案例 ID 写条件分支）。注册表只声明「可以展示
什么」与所需字段，不写入任何统计结果——统计计算在 ``statistics.py``，
API 响应模型在 ``schemas.py``，本模块不反向依赖它们。
"""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AnalysisDisabledReason",
    "AnalysisModuleSpec",
    "AnalysisProfile",
    "GAS_VALUE_NAMES",
    "MICROSEISMIC_VALUE_NAME",
    "MICROSEISMIC_VALUE_UNIT",
    "PROFILE_GAS_CONTENT",
    "PROFILE_GENERIC_3D",
    "PROFILE_MICROSEISMIC_VELOCITY",
    "PROFILE_RESISTIVITY",
    "PROFILE_VERSION",
    "RESISTIVITY_VALUE_NAME",
    "resolve_analysis_profile",
]

PROFILE_VERSION = 1

PROFILE_RESISTIVITY = "resistivity"
PROFILE_MICROSEISMIC_VELOCITY = "microseismic_velocity"
PROFILE_GAS_CONTENT = "gas_content"
PROFILE_GENERIC_3D = "generic_3d"

RESISTIVITY_VALUE_NAME = "RHO"
MICROSEISMIC_VALUE_NAME = "Vx"
# 微震 Vx 单位恒为 km/s，绝不静默换算；单位不符一律降级 generic
MICROSEISMIC_VALUE_UNIT = "km/s"
# 瓦斯字段合同待定（设计 §5.3）：先注册判定规则，数据合同到位后冻结
GAS_VALUE_NAMES = frozenset({"ch4", "gas", "gas_content"})

_PROFILE_LABELS = {
    PROFILE_RESISTIVITY: "电阻率专业分析",
    PROFILE_MICROSEISMIC_VELOCITY: "微震速度专业分析",
    PROFILE_GAS_CONTENT: "瓦斯含量专业分析",
}


class _RegistryModel(BaseModel):
    """领域注册表模型：冻结、禁止未知键（与 API 层 ContractModel 分层）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class AnalysisModuleSpec(_RegistryModel):
    """单个分析模块的能力声明（不携带任何统计结果）。

    ``required_fields`` 使用 mapping 角色（``x``/``y``/``z``/``value``），
    不绑定具体源列名；``requires_3d`` 为真时 2D 数据一律不启用该模块。
    """

    module_id: str
    specialized: bool
    requires_3d: bool
    required_fields: list[str] = Field(default_factory=list)
    description: str


class AnalysisDisabledReason(_RegistryModel):
    """某专属 profile 未启用的逐条原因：机器可读缺失项 + 展示文案。"""

    profile_id: str
    missing: list[str] = Field(default_factory=list)
    reason: str


class AnalysisProfile(_RegistryModel):
    """一次解析得到的分析 profile：能力清单与禁用理由，不含统计结果。"""

    profile_id: str
    profile_version: int = PROFILE_VERSION
    specialized: bool
    dimension: str = "3d"
    modules: list[str] = Field(default_factory=list)
    module_specs: list[AnalysisModuleSpec] = Field(default_factory=list)
    disabled_reasons: list[AnalysisDisabledReason] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 模块能力声明（仅声明可展示内容与所需字段，不写统计结果）
# ---------------------------------------------------------------------------


def _spec(
    module_id: str,
    *,
    specialized: bool,
    requires_3d: bool,
    required_fields: list[str],
    description: str,
) -> AnalysisModuleSpec:
    return AnalysisModuleSpec(
        module_id=module_id,
        specialized=specialized,
        requires_3d=requires_3d,
        required_fields=required_fields,
        description=description,
    )


def _base_specs() -> list[AnalysisModuleSpec]:
    """所有 profile 共用的基础模块（设计 §5.4：质量与基础统计）。"""

    return [
        _spec(
            "quality",
            specialized=False,
            requires_3d=False,
            required_fields=["x", "y", "value"],
            description="数据质量：有限性、缺失与重复坐标检查",
        ),
        _spec(
            "statistics",
            specialized=False,
            requires_3d=False,
            required_fields=["value"],
            description="基础统计：计数、范围、均值、中位数与分位数",
        ),
    ]


def _generic_extra_specs() -> list[AnalysisModuleSpec]:
    """自定义数据通用模块（设计 §5.4：分布、空间范围、通用剖面、模型指标）。"""

    return [
        _spec(
            "distribution",
            specialized=False,
            requires_3d=False,
            required_fields=["value"],
            description="属性值分布直方图",
        ),
        _spec(
            "spatial_extent",
            specialized=False,
            requires_3d=False,
            required_fields=["x", "y"],
            description="空间范围与覆盖摘要",
        ),
        _spec(
            "profile_slices",
            specialized=False,
            requires_3d=False,
            required_fields=["x", "y", "value"],
            description="X/Y/Z 剖面统计（2D 数据仅 X/Y）",
        ),
        _spec(
            "model_comparison",
            specialized=False,
            requires_3d=False,
            required_fields=[],
            description="已物化成果的模型指标对比（仅展示实际存在的算法，不重算）",
        ),
    ]


def _resistivity_specs() -> list[AnalysisModuleSpec]:
    specs = _base_specs() + [
        _spec(
            "distribution",
            specialized=True,
            requires_3d=True,
            required_fields=["value"],
            description="RHO 值分布（默认对数尺度展示，同时保留原始值统计）",
        ),
        _spec(
            "spatial_anomaly",
            specialized=True,
            requires_3d=True,
            required_fields=["x", "y", "z", "value"],
            description="高阻/低阻空间异常区间（阈值来源必须明示）",
        ),
        _spec(
            "depth_slices",
            specialized=True,
            requires_3d=True,
            required_fields=["z", "value"],
            description="各 Z 层异常面积/体积占比与深度变化",
        ),
        _spec(
            "profile_slices",
            specialized=False,
            requires_3d=False,
            required_fields=["x", "y", "z", "value"],
            description="X/Y/Z 方向变化率和剖面统计",
        ),
        _spec(
            "model_comparison",
            specialized=False,
            requires_3d=False,
            required_fields=[],
            description="三种插值算法的误差、空间差异和结果身份对比",
        ),
    ]
    return specs


def _microseismic_specs() -> list[AnalysisModuleSpec]:
    return _base_specs() + [
        _spec(
            "distribution",
            specialized=True,
            requires_3d=True,
            required_fields=["value"],
            description="Vx 有效值分布、分位数和异常区间",
        ),
        _spec(
            "axis_trends",
            specialized=True,
            requires_3d=True,
            required_fields=["x", "y", "z", "value"],
            description="X/Y/Z 方向速度均值、中位数和趋势变化",
        ),
        _spec(
            "gradient",
            specialized=True,
            requires_3d=True,
            required_fields=["x", "y", "z", "value"],
            description="速度梯度/局部变化强度（仅有限值参与）",
        ),
        _spec(
            "spatial_anomaly",
            specialized=True,
            requires_3d=True,
            required_fields=["x", "y", "z", "value"],
            description="空间高值/低值区域及其体积占比",
        ),
        _spec(
            "profile_slices",
            specialized=False,
            requires_3d=False,
            required_fields=["x", "y", "z", "value"],
            description="X/Y/Z 剖面统计",
        ),
        _spec(
            "model_comparison",
            specialized=False,
            requires_3d=False,
            required_fields=[],
            description="IDW、普通 Kriging、DSI-like 指标对比（仅展示实际存在的算法）",
        ),
    ]


def _gas_specs() -> list[AnalysisModuleSpec]:
    """瓦斯 profile（设计 §5.3）：只承诺真实字段可支持的能力。"""

    return _base_specs() + [
        _spec(
            "distribution",
            specialized=True,
            requires_3d=True,
            required_fields=["value"],
            description="瓦斯含量分布",
        ),
        _spec(
            "threshold_zones",
            specialized=True,
            requires_3d=True,
            required_fields=["value"],
            description="含量阈值区（阈值来源必须明示）",
        ),
        _spec(
            "depth_slices",
            specialized=True,
            requires_3d=True,
            required_fields=["z", "value"],
            description="含量深度变化",
        ),
        _spec(
            "spatial_anomaly",
            specialized=True,
            requires_3d=True,
            required_fields=["x", "y", "z", "value"],
            description="含量空间聚集",
        ),
        _spec(
            "profile_slices",
            specialized=False,
            requires_3d=False,
            required_fields=["x", "y", "z", "value"],
            description="X/Y/Z 剖面统计",
        ),
        _spec(
            "model_comparison",
            specialized=False,
            requires_3d=False,
            required_fields=[],
            description="已物化成果的模型指标对比（不重算）",
        ),
    ]


_SPECIALIZED_SPECS = {
    PROFILE_RESISTIVITY: _resistivity_specs,
    PROFILE_MICROSEISMIC_VELOCITY: _microseismic_specs,
    PROFILE_GAS_CONTENT: _gas_specs,
}


# ---------------------------------------------------------------------------
# profile 判定
# ---------------------------------------------------------------------------


def _unmet_requirements(
    profile_id: str, *, value_name: str, value_unit: str, is_3d: bool
) -> list[str]:
    """逐条列出某专属 profile 未满足的判定要求（缺失字段或 3D 前提）。"""

    unmet: list[str] = []
    if profile_id == PROFILE_RESISTIVITY:
        if value_name != RESISTIVITY_VALUE_NAME:
            unmet.append(f"value_name={RESISTIVITY_VALUE_NAME}")
    elif profile_id == PROFILE_MICROSEISMIC_VELOCITY:
        if value_name != MICROSEISMIC_VALUE_NAME:
            unmet.append(f"value_name={MICROSEISMIC_VALUE_NAME}")
        elif value_unit != MICROSEISMIC_VALUE_UNIT:
            unmet.append(f"value_unit={MICROSEISMIC_VALUE_UNIT}")
    elif profile_id == PROFILE_GAS_CONTENT:
        if value_name.lower() not in GAS_VALUE_NAMES:
            unmet.append("value_name∈{CH4,gas,gas_content}")
    if not unmet and not is_3d:
        unmet.append("dimension=3d")
    return unmet


def _disabled_reasons(
    *, value_name: str, value_unit: str, is_3d: bool, dimension: str
) -> list[AnalysisDisabledReason]:
    """为 generic 降级逐条给出各专属 profile 未启用的原因（设计 §5.4）。"""

    reasons: list[AnalysisDisabledReason] = []
    for profile_id, label in _PROFILE_LABELS.items():
        unmet = _unmet_requirements(
            profile_id, value_name=value_name, value_unit=value_unit, is_3d=is_3d
        )
        if unmet == ["dimension=3d"]:
            reason = f"{label}要求 3D 数据，当前 dimension={dimension}，未启用"
        else:
            reason = f"{'、'.join(unmet)} 缺失，未启用{label}"
        reasons.append(
            AnalysisDisabledReason(profile_id=profile_id, missing=unmet, reason=reason)
        )
    return reasons


def _build_specialized(profile_id: str, *, dimension: str) -> AnalysisProfile:
    specs = _SPECIALIZED_SPECS[profile_id]()
    return AnalysisProfile(
        profile_id=profile_id,
        specialized=True,
        dimension=dimension,
        modules=[spec.module_id for spec in specs],
        module_specs=specs,
    )


def _build_generic(
    *, value_name: str, value_unit: str, is_3d: bool, dimension: str
) -> AnalysisProfile:
    specs = _base_specs() + _generic_extra_specs()
    return AnalysisProfile(
        profile_id=PROFILE_GENERIC_3D,
        specialized=False,
        dimension=dimension,
        modules=[spec.module_id for spec in specs],
        module_specs=specs,
        disabled_reasons=_disabled_reasons(
            value_name=value_name,
            value_unit=value_unit,
            is_3d=is_3d,
            dimension=dimension,
        ),
    )


def resolve_analysis_profile(profile: Mapping[str, Any]) -> AnalysisProfile:
    """按 dataset ``profile_json.mapping`` 解析分析 profile，绝不读取 case_id。

    判定输入仅限 ``mapping`` 的 ``value_name``/``value_unit``/字段名/
    ``dimension``：``value_name=="RHO"`` → 电阻率；``value_name=="Vx"`` 且
    ``value_unit=="km/s"`` → 微震速度；``value_name`` 指示瓦斯含量
    （CH4/gas，合同待定仅注册）→ 瓦斯；其余 → ``generic_3d`` 并逐条给出
    各专属 profile 的禁用理由。专属模块声明需要 3D，显式非 3D 的
    ``dimension`` 一律降级 generic。真实 mapping 由 ``FieldMapping`` 合同
    强制携带 ``dimension``；缺省按 3d 宽容处理，仅显式非 3d 触发降级。
    """

    mapping = profile.get("mapping") if isinstance(profile, Mapping) else None
    if not isinstance(mapping, Mapping):
        mapping = {}
    value_name = str(mapping.get("value_name") or "").strip()
    raw_unit = mapping.get("value_unit")
    value_unit = str(raw_unit).strip() if raw_unit is not None else ""
    raw_dimension = mapping.get("dimension")
    dimension = str(raw_dimension).strip().lower() if raw_dimension else "3d"
    is_3d = dimension == "3d"

    matched: str | None = None
    if value_name == RESISTIVITY_VALUE_NAME:
        matched = PROFILE_RESISTIVITY
    elif (
        value_name == MICROSEISMIC_VALUE_NAME and value_unit == MICROSEISMIC_VALUE_UNIT
    ):
        matched = PROFILE_MICROSEISMIC_VELOCITY
    elif value_name.lower() in GAS_VALUE_NAMES:
        matched = PROFILE_GAS_CONTENT

    if matched is not None and is_3d:
        return _build_specialized(matched, dimension=dimension)
    return _build_generic(
        value_name=value_name, value_unit=value_unit, is_3d=is_3d, dimension=dimension
    )
