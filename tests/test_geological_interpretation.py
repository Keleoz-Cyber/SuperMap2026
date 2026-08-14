"""地质属性解释规则：把既有数值翻译成自然、可复核的现场提示。"""

from __future__ import annotations

from geomodeling.platform.geological_interpretation import (
    build_domain_interpretation,
)
from geomodeling.platform.result_analysis_contracts import ComponentPreview


def _component(component_id: int, label: str, value: float) -> ComponentPreview:
    return ComponentPreview(
        rank=1,
        label=label,
        component_id=component_id,
        direction="high",
        support_node_count=8,
        support_measure=64000.0,
        support_unit="volume_coordinate_unit3",
        bounds=[[0.0, 20.0], [10.0, 30.0], [-600.0, -420.0]],
        centroid=[10.0, 20.0, -510.0],
        value_min=value - 2.0,
        value_max=value,
        value_mean=value - 1.0,
        touches_grid_boundary=False,
    )


def test_resistivity_prefers_low_component_and_keeps_multisolution_boundary():
    interpretation = build_domain_interpretation(
        variable_name="RHO",
        variable_unit="Ω·m",
        high_components=[_component(1, "高-A", 120.0)],
        low_components=[_component(1_000_001, "低-A", 12.0)],
    )

    assert interpretation.profile == "resistivity"
    assert interpretation.panel_label == "地质研判"
    assert interpretation.status == "exploratory"
    assert interpretation.cards[0].component_id == 1_000_001
    assert interpretation.cards[0].direction == "low"
    assert "谷值 10" in interpretation.cards[0].summary
    assert "模型中覆盖约 64,000" in interpretation.cards[0].summary
    assert "网格支持体积" not in interpretation.cards[0].summary
    assert "峰值" not in interpretation.cards[0].summary
    assert "含水" in "".join(interpretation.cards[0].possible_interpretations)
    assert "不能只凭低阻结果判断这里有水" in "".join(interpretation.cards[0].limitations)
    assert "先看低阻异常区" in interpretation.overview
    assert "探索性解释" not in "".join(interpretation.global_limitations)


def test_microseismic_velocity_describes_medium_not_event_activity():
    interpretation = build_domain_interpretation(
        variable_name="VX_KM_S",
        variable_unit="km/s",
        high_components=[_component(1, "高-A", 3.2)],
        low_components=[_component(1_000_001, "低-A", 0.8)],
    )

    assert interpretation.profile == "microseismic_velocity"
    assert interpretation.cards[0].direction == "low"
    text = interpretation.model_dump_json()
    assert "裂隙" in text
    assert "不能用这张速度图判断微震事件是否活跃" in text
    assert "检查测线覆盖" in text
    assert "已确认断层" not in text


def test_gas_prioritizes_high_content_without_inventing_risk_grade():
    interpretation = build_domain_interpretation(
        variable_name="CH4_content",
        variable_unit="ml/g",
        high_components=[_component(1, "高-A", 24.0)],
        low_components=[_component(1_000_001, "低-A", 0.5)],
    )

    assert interpretation.profile == "gas_content"
    assert interpretation.cards[0].direction == "high"
    assert "优先安排复测" in "".join(interpretation.cards[0].potential_impacts)
    assert "对照瓦斯压力、钻孔、抽采和通风记录" in "".join(
        interpretation.cards[0].recommended_actions
    )
    assert "危险等级" in "".join(interpretation.global_limitations)
    assert all(card.confidence == "exploratory" for card in interpretation.cards)


def test_generic_variable_has_safe_not_applicable_fallback():
    interpretation = build_domain_interpretation(
        variable_name="CUSTOM",
        variable_unit="unknown",
        high_components=[_component(1, "高-A", 8.0)],
        low_components=[_component(1_000_001, "低-A", 2.0)],
    )

    assert interpretation.profile == "generic_3d"
    assert interpretation.panel_label == "规则研判"
    assert interpretation.status == "not_applicable"
    assert interpretation.cards == []
    assert "还没有对应的地质解释规则" in interpretation.overview
