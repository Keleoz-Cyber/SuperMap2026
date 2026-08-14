"""把成果网格事实翻译为受控的地质属性解释。

本模块不推断新的数值、不调用外部模型，也不把分位异常升级为已确认地质
对象。所有专业措辞均来自版本化规则；没有匹配规则时安全降级为通用分析。
"""

from __future__ import annotations

from collections.abc import Sequence

from geomodeling.platform.result_analysis_contracts import (
    ComponentPreview,
    DomainInterpretation,
    DomainInterpretationCard,
    SpatialTarget,
)

RULE_VERSION = "geological_interpretation.v1"


def resolve_domain_profile(variable_name: str, variable_unit: str) -> str:
    """按属性身份识别规则集；只接受登记过的字段和单位别名。"""

    name = variable_name.strip().lower()
    unit = variable_unit.strip().lower().replace(" ", "")
    if name == "rho" and unit in {"ω·m", "ωm", "ohm_m", "ohm·m"}:
        return "resistivity"
    if name in {"vx", "vx_km_s"} and unit == "km/s":
        return "microseismic_velocity"
    if name in {"ch4", "ch4_content", "gas", "gas_content"} and unit == "ml/g":
        return "gas_content"
    return "generic_3d"


def _support_label(component: ComponentPreview) -> str:
    return "模型中覆盖约"


def _format_number(value: float, decimals: int = 2) -> str:
    """把界面数值写成常规小数，避免科学计数法和无意义的尾零。"""

    return f"{value:,.{decimals}f}".rstrip("0").rstrip(".")


def _component_summary(component: ComponentPreview, direction: str) -> str:
    depth = ""
    if len(component.bounds) >= 3:
        z0, z1 = component.bounds[2]
        depth = f"位于 Z={_format_number(z0)}～{_format_number(z1)}，"
    boundary = "，范围延伸到模型边缘" if component.touches_grid_boundary else "，没有碰到模型边缘"
    extreme_label = "谷值" if direction == "low" else "峰值"
    extreme_value = component.value_min if direction == "low" else component.value_max
    return (
        f"{depth}{_support_label(component)} {_format_number(component.support_measure)}，"
        f"{extreme_label} {_format_number(extreme_value, 3)}{boundary}"
    )


def _evidence(component: ComponentPreview) -> list[str]:
    return [
        f"区域 {component.label}",
        f"覆盖 {component.support_node_count} 个网格点",
        f"数值 {component.value_min:g}～{component.value_max:g}",
        f"中心位置 ({', '.join(f'{value:g}' for value in component.centroid)})",
    ]


def _rule_copy(profile: str, direction: str) -> dict[str, object]:
    rules: dict[tuple[str, str], dict[str, object]] = {
        ("resistivity", "low"): {
            "title": "低阻异常区",
            "interpretations": ["这一带的电阻率明显偏低，常见于含水、裂隙较多、黏土富集或其他导电介质"],
            "impacts": ["如果钻孔或水文资料也显示异常，应优先检查这里的含水和构造情况"],
            "actions": ["先对照钻孔、水文记录和其他物探结果，再决定是否现场复测"],
            "limitations": ["低阻有多种成因，不能只凭低阻结果判断这里有水"],
        },
        ("resistivity", "high"): {
            "title": "高阻异常区",
            "interpretations": ["这一带的电阻率明显偏高，常见于较致密、较干燥的介质或高阻岩性"],
            "impacts": ["它可以帮助判断岩性或含水条件是否发生变化"],
            "actions": ["对照岩性、构造和钻孔记录，看看高阻变化能否相互印证"],
            "limitations": ["高阻也有多种成因，不能只凭这张图判断岩体完整或干燥"],
        },
        ("microseismic_velocity", "low"): {
            "title": "低速度异常区",
            "interpretations": ["速度偏低常见于介质较松散、破碎、裂隙或孔隙较多，也可能受流体影响"],
            "impacts": ["这里值得优先检查是否存在结构较弱或介质变化明显的地段"],
            "actions": ["先检查测线覆盖，再对照岩性、钻孔和其他物探资料"],
            "limitations": ["不能用这张速度图判断微震事件是否活跃，也不能直接把异常区当成断层"],
        },
        ("microseismic_velocity", "high"): {
            "title": "高速度异常区",
            "interpretations": ["速度偏高常见于较致密的介质，也可能与岩性或应力状态变化有关"],
            "impacts": ["这类变化可用于辅助划分不同的介质结构"],
            "actions": ["对照岩性、应力资料和测线位置，确认高速度变化是否可靠"],
            "limitations": ["速度高不等于一定更稳定，这份数据也没有震源能量和时间变化信息"],
        },
        ("gas_content", "high"): {
            "title": "高瓦斯含量区",
            "interpretations": ["模型显示这里的瓦斯含量比周围更高，可能存在局部富集"],
            "impacts": ["这类位置应优先安排复测，并纳入抽采和通风方案核对"],
            "actions": ["对照瓦斯压力、钻孔、抽采和通风记录，再按矿区标准判断"],
            "limitations": ["这里是模型中的相对高值，不是法定危险等级，不能替代矿井安全评价"],
        },
        ("gas_content", "low"): {
            "title": "低瓦斯含量区",
            "interpretations": ["模型显示这里的瓦斯含量比周围更低"],
            "impacts": ["它可以帮助了解含量变化，但不能直接说明这里安全"],
            "actions": ["检查采样覆盖和钻孔深度，确认低值不是由测点稀疏造成的"],
            "limitations": ["低含量不等于安全，现场仍要按矿区规定监测和评价"],
        },
    }
    return rules[(profile, direction)]


def _card(profile: str, direction: str, component: ComponentPreview) -> DomainInterpretationCard:
    rule = _rule_copy(profile, direction)
    limitations = list(rule["limitations"])
    if component.touches_grid_boundary:
        limitations.append("这片区域延伸到模型边缘，实际范围可能比图上更大")
    return DomainInterpretationCard(
        id=f"domain-{direction}-{component.component_id}",
        component_id=component.component_id,
        direction=direction,
        title=f"{rule['title']} {component.label}",
        summary=_component_summary(component, direction),
        evidence=_evidence(component),
        possible_interpretations=list(rule["interpretations"]),
        potential_impacts=list(rule["impacts"]),
        recommended_actions=list(rule["actions"]),
        confidence="exploratory",
        limitations=limitations,
        spatial_target=SpatialTarget(kind="component", component_id=component.component_id),
    )


def build_domain_interpretation(
    *,
    variable_name: str,
    variable_unit: str,
    high_components: Sequence[ComponentPreview],
    low_components: Sequence[ComponentPreview],
) -> DomainInterpretation:
    """生成按属性分类的研判摘要，不改变任何建模结果。"""

    profile = resolve_domain_profile(variable_name, variable_unit)
    if profile == "generic_3d":
        return DomainInterpretation(
            rule_version=RULE_VERSION,
            profile="generic_3d",
            panel_label="规则研判",
            narrative_label="通用三维属性分析",
            status="not_applicable",
            overview="这个字段还没有对应的地质解释规则，当前只展示数值分布。",
            cards=[],
            global_limitations=["如需自动解释，请先说明这个字段的实际含义和判断规则"],
        )

    labels = {
        "resistivity": "地下电性结构",
        "microseismic_velocity": "介质速度结构",
        "gas_content": "煤层瓦斯含量分区",
    }
    order = ("high", "low") if profile == "gas_content" else ("low", "high")
    groups = {"high": high_components, "low": low_components}
    cards: list[DomainInterpretationCard] = []
    for direction in order:
        cards.extend(_card(profile, direction, component) for component in groups[direction][:3])

    if cards:
        lead = cards[0]
        overview = f"共找到 {len(cards)} 个值得复核的区域。先看{lead.title}：{lead.summary}。"
    else:
        overview = "按当前设置没有找到连续、明显的高低值区域。"

    global_limitations = ["这些高低值按模型自身的数值分布划分，尚未经过现场确认"]
    if profile == "resistivity":
        global_limitations.append("电阻率异常可能有多种成因，需要对照地质、水文和钻孔资料")
    elif profile == "microseismic_velocity":
        global_limitations.append("这里展示的是速度分布，不包含微震事件的位置、时间和能量")
    else:
        global_limitations.append("系统还没有矿区正式阈值，因此不会给出危险等级、安全等级或储量判断")

    return DomainInterpretation(
        rule_version=RULE_VERSION,
        profile=profile,
        panel_label="地质研判",
        narrative_label=labels[profile],
        status="exploratory",
        overview=overview,
        cards=cards,
        global_limitations=global_limitations,
    )


__all__ = ["RULE_VERSION", "build_domain_interpretation", "resolve_domain_profile"]
