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
    return "网格支持体积" if component.support_unit == "volume_coordinate_unit3" else "网格支持面积"


def _component_summary(component: ComponentPreview, direction: str) -> str:
    depth = ""
    if len(component.bounds) >= 3:
        z0, z1 = component.bounds[2]
        depth = f"Z={z0:g}～{z1:g}；"
    boundary = "，并接触模型边界" if component.touches_grid_boundary else "，未接触模型边界"
    extreme_label = "谷值" if direction == "low" else "峰值"
    extreme_value = component.value_min if direction == "low" else component.value_max
    return (
        f"{depth}{_support_label(component)} {component.support_measure:g}，"
        f"{extreme_label} {extreme_value:g}{boundary}"
    )


def _evidence(component: ComponentPreview) -> list[str]:
    return [
        f"异常体 {component.label}",
        f"有效网格节点 {component.support_node_count}",
        f"属性范围 {component.value_min:g}～{component.value_max:g}",
        f"中心坐标 ({', '.join(f'{value:g}' for value in component.centroid)})",
    ]


def _rule_copy(profile: str, direction: str) -> dict[str, object]:
    rules: dict[tuple[str, str], dict[str, object]] = {
        ("resistivity", "low"): {
            "title": "低阻异常区",
            "interpretations": ["可能与含水、裂隙发育、黏土富集或其他导电介质有关"],
            "impacts": ["提示地下介质电性结构存在差异，可作为水文与构造核查的优先区域"],
            "actions": ["结合钻孔、水文资料和其他物探成果进行交叉验证"],
            "limitations": ["低电阻率具有多解性，不能直接认定为含水区"],
        },
        ("resistivity", "high"): {
            "title": "高阻异常区",
            "interpretations": ["可能与较致密、较干燥介质或高阻岩性有关"],
            "impacts": ["提示地下介质电性分区，可辅助识别岩性或含水条件变化"],
            "actions": ["结合岩性、构造和钻孔资料核查高阻成因"],
            "limitations": ["高电阻率不能单独证明岩体完整、干燥或特定岩性"],
        },
        ("microseismic_velocity", "low"): {
            "title": "低速度异常区",
            "interpretations": ["可能与松散、破碎、裂隙、孔隙或流体条件差异有关"],
            "impacts": ["提示介质传播特性发生变化，可作为结构薄弱区复核线索"],
            "actions": ["结合测线覆盖、岩性、钻孔与其他地球物理资料核查"],
            "limitations": ["速度异常不代表微震事件活跃度，也不能直接认定为断层"],
        },
        ("microseismic_velocity", "high"): {
            "title": "高速度异常区",
            "interpretations": ["可能与较致密、较完整介质或岩性、应力状态差异有关"],
            "impacts": ["提示介质力学与传播性质分区，可作为后续结构解释线索"],
            "actions": ["结合岩性、应力与测线几何资料复核异常成因"],
            "limitations": ["高速度不等于高稳定性，也不提供震源能量或时间演化证据"],
        },
        ("gas_content", "high"): {
            "title": "高瓦斯含量区",
            "interpretations": ["模型显示该区域瓦斯含量相对较高，可能形成局部富集特征"],
            "impacts": ["可作为钻孔复核、抽采和通风方案布置的重点复核区域"],
            "actions": ["结合矿区分级阈值、瓦斯压力、钻孔、抽采与通风资料核查"],
            "limitations": ["分位高值不是法定危险等级，不能直接替代矿井安全评价"],
        },
        ("gas_content", "low"): {
            "title": "低瓦斯含量区",
            "interpretations": ["模型显示该区域瓦斯含量相对较低"],
            "impacts": ["可用于理解含量空间分区，但不能据此认定为安全区域"],
            "actions": ["复核采样覆盖与钻孔深度，避免把稀疏区外推结果作为现场结论"],
            "limitations": ["低含量不等于安全等级，仍需执行矿区规定的监测与评价"],
        },
    }
    return rules[(profile, direction)]


def _card(profile: str, direction: str, component: ComponentPreview) -> DomainInterpretationCard:
    rule = _rule_copy(profile, direction)
    limitations = list(rule["limitations"])
    if component.touches_grid_boundary:
        limitations.append("该异常体接触模型边界，空间范围可能被截断")
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
            overview="当前属性未匹配受控专业规则库，仅展示数值事实，不生成专业地质结论。",
            cards=[],
            global_limitations=["自定义属性的专业含义需由用户提供可追溯规则"],
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
        overview = f"识别出 {len(cards)} 个可解释异常体；优先关注{lead.title}。{lead.summary}"
    else:
        overview = "当前分位阈值和最小支持度条件下未识别出可解释异常体。"

    global_limitations = ["当前结论来自完整成果网格的 p25/p75 分位异常，仅用于探索性解释"]
    if profile == "resistivity":
        global_limitations.append("电阻率异常具有多解性，必须结合地质、水文与钻孔资料")
    elif profile == "microseismic_velocity":
        global_limitations.append("当前数据是速度场，不包含事件位置、时间或能量信息")
    else:
        global_limitations.append("未登记矿区权威阈值，不生成危险等级、安全等级或储量结论")

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
