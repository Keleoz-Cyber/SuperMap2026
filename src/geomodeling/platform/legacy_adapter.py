"""Read-only adapter for the built-in v0.3.1 cases (resistivity & friends).

The legacy cards are merged into the v0.4 case list as immutable entries:
the adapter never creates or mutates SQLite rows for them. ``case_service``
is imported lazily so the platform layer stays importable without the api
extra installed.

v0.7.0：统一案例工作台身份（``workspace_kind`` + ``capabilities``）：
legacy 卡 → ``builtin_legacy``；持久化 Case 的 ``config_json.workspace_kind``
为 ``builtin_preset`` → 预置身份；其余持久化 Case → ``user_upload``。
旧 DAT 流程的 legacy 微震卡由 ``builtin_preset`` 预置描述符取代，不再
出现在案例列表。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from geomodeling.platform.microseismic_preset import (
    PRESET_CASE_ID,
    PRESET_VERSION,
    TRACKED_CSV_SHA256,
)
from geomodeling.platform.schemas import CaseRecord, FeaturedResultLink

BUILTIN_SOURCE_KIND = "builtin_legacy"
UPLOAD_SOURCE_KIND = "upload"

LEGACY_WORKSPACE_KIND = "builtin_legacy"
PRESET_WORKSPACE_KIND = "builtin_preset"
UPLOAD_WORKSPACE_KIND = "user_upload"

#: 旧 DAT 流程的 legacy 微震卡 ID（由预置案例取代，不再出现在案例卡列表）
LEGACY_MICROSEISMIC_CARD_ID = "microseismic"

#: 旧 S3M 流程的 legacy 电阻率卡 ID（seed 为 builtin_preset 后由统一 seed 卡取代；
#: 未 seed 的运行库保持 legacy 卡现状，退役见 v0.8.0 后续任务）
LEGACY_RESISTIVITY_CARD_ID = "resistivity"

#: 预置卡 provenance 兜底常量：微震 seed 尚未写 data_form/value_unit 等键时
#: 保持 v0.7.0 既有文案，绝不回归；新预置（电阻率）由 seed 写入自己的键。
_PRESET_PROVENANCE_FALLBACK = {
    "data_form": "三维 X/Y/Z/Vx（局部测线坐标）",
    "value_unit": "km/s",
    "coordinate_kind": "local_linear",
    "badge": "CSV 预置 · 官方普通克里金成果",
}


def _capabilities(
    *, data_summary: bool, experiments: bool, official_result: bool, native_volume: bool
) -> dict[str, bool]:
    return {
        "data_summary": data_summary,
        "experiments": experiments,
        "official_result": official_result,
        "native_volume": native_volume,
    }


def _legacy_workspace_fields(card: Mapping[str, Any]) -> dict[str, Any]:
    """legacy 卡的工作台字段：只读摘要 + 原生体渲染能力（电阻率）。"""

    return {
        "workspace_kind": LEGACY_WORKSPACE_KIND,
        "capabilities": _capabilities(
            data_summary=True,
            experiments=False,
            official_result=False,
            native_volume=card.get("case_id") == "resistivity",
        ),
        "primary_dataset": None,
        "official_result": None,
        "provenance_summary": {
            "data_form": card.get("data_form"),
            "coordinate": card.get("coordinate"),
            "unit_note": card.get("unit_note"),
        },
    }


def preset_workspace_card() -> dict[str, Any]:
    """未 seed 预置案例的不可变描述符：可见但能力全 false。"""

    return {
        "case_id": PRESET_CASE_ID,
        "title": "微震速度",
        "case_type": "generic",
        "status": "initialization_required",
        "source_kind": "builtin_preset",
        "workspace_kind": PRESET_WORKSPACE_KIND,
        "capabilities": _capabilities(
            data_summary=False, experiments=False, official_result=False, native_volume=False
        ),
        "primary_dataset": None,
        "official_result": None,
        "featured_result": None,
        "provenance_summary": {
            "preset_version": PRESET_VERSION,
            "source_sha256": TRACKED_CSV_SHA256,
            "data_form": "三维 X/Y/Z/Vx（局部测线坐标）",
            "value_unit": "km/s",
            "coordinate_kind": "local_linear",
            "badge": "CSV 预置 · 官方普通克里金成果",
        },
        "links": {"detail": None, "publish_status": None},
    }


def workspace_case_card(
    record: CaseRecord,
    *,
    featured_result: FeaturedResultLink | None = None,
    primary_dataset: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """持久化案例（预置/上传）的统一工作台卡。"""

    config = record.config if isinstance(record.config, dict) else {}
    is_preset = config.get("workspace_kind") == PRESET_WORKSPACE_KIND
    kind = PRESET_WORKSPACE_KIND if is_preset else UPLOAD_WORKSPACE_KIND
    featured = featured_result.model_dump(mode="json") if featured_result is not None else None
    provenance: dict[str, Any] = {}
    if is_preset:
        # provenance 键由 seed 写入 Case config_json（v0.8.0 电阻率散点预置）；
        # 未写这些键的早期预置 seed（微震）用既有常量兜底，文案逐位不回归。
        provenance = {
            "preset_version": config.get("preset_version"),
            "source_sha256": config.get("source_sha256"),
            "data_form": config.get("data_form") or _PRESET_PROVENANCE_FALLBACK["data_form"],
            "value_unit": config.get("value_unit")
            or _PRESET_PROVENANCE_FALLBACK["value_unit"],
            "coordinate_kind": config.get("coordinate_kind")
            or _PRESET_PROVENANCE_FALLBACK["coordinate_kind"],
            "badge": config.get("badge") or _PRESET_PROVENANCE_FALLBACK["badge"],
        }
    elif primary_dataset is not None:
        mapping = (primary_dataset.get("profile") or {}).get("mapping") or {}
        provenance = {
            "value_name": mapping.get("value_name"),
            "value_unit": mapping.get("value_unit"),
            "coordinate_kind": mapping.get("coordinate_kind"),
        }
    return {
        "case_id": record.id,
        "title": record.name,
        "case_type": record.case_type,
        "status": "active",
        "source_kind": kind if is_preset else UPLOAD_SOURCE_KIND,
        "workspace_kind": kind,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "capabilities": _capabilities(
            data_summary=primary_dataset is not None,
            experiments=primary_dataset is not None,
            official_result=featured is not None,
            native_volume=bool(featured and featured.get("materialized")),
        ),
        "primary_dataset": primary_dataset,
        "official_result": featured,
        "featured_result": featured,
        "provenance_summary": provenance,
        "links": {"detail": f"/api/cases/{record.id}", "publish_status": None},
    }


def legacy_case_cards(exclude_ids: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """Immutable v0.3.1 case cards, marked as built-in legacy.

    v0.7.0：旧 DAT 流程的 legacy 微震卡由预置案例取代，不在此列出。
    v0.8.0：``exclude_ids`` 传入已 seed 为 ``builtin_preset`` 的持久化案例
    ID（如电阻率），对应 legacy 卡让位给统一 seed 卡（同微震跳过模式）。
    """

    from geomodeling.api import case_service  # 避免 platform → api 的模块级反向依赖

    excluded = {LEGACY_MICROSEISMIC_CARD_ID} | set(exclude_ids or ())
    cards: list[dict[str, Any]] = []
    for card in case_service.list_cases():
        if card.get("case_id") in excluded:
            continue
        merged = dict(card)
        merged["source_kind"] = BUILTIN_SOURCE_KIND
        merged.update(_legacy_workspace_fields(merged))
        cards.append(merged)
    return cards


def upload_case_card(
    record: CaseRecord,
    *,
    featured_result: FeaturedResultLink | None = None,
    primary_dataset: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize a persisted case into the unified workspace card shape."""

    return workspace_case_card(
        record, featured_result=featured_result, primary_dataset=primary_dataset
    )


def merged_case_cards(
    records: Iterable[CaseRecord],
    featured_results: Mapping[str, FeaturedResultLink | None] | None = None,
    primary_datasets: Mapping[str, dict[str, Any] | None] | None = None,
) -> list[dict[str, Any]]:
    """Legacy cards first (stable order), preset descriptor/seeded card, then uploads."""

    featured = featured_results or {}
    datasets = primary_datasets or {}
    persisted = list(records)
    # v0.8.0：已 seed 为 builtin_preset 的持久化案例（如电阻率）与同名 legacy 卡
    # 冲突时，legacy 卡让位——否则 builtin_ids 过滤会让统一 seed 卡从列表消失；
    # 未 seed 的运行库不含这类持久化行，legacy 卡照旧（退役见后续任务）。
    seeded_preset_ids = {
        record.id
        for record in persisted
        if isinstance(record.config, dict)
        and record.config.get("workspace_kind") == PRESET_WORKSPACE_KIND
    }
    cards = legacy_case_cards(exclude_ids=seeded_preset_ids)
    builtin_ids = {card["case_id"] for card in cards}
    if not any(record.id == PRESET_CASE_ID for record in persisted):
        cards.append(preset_workspace_card())
    cards += [
        upload_case_card(
            record,
            featured_result=featured.get(record.id),
            primary_dataset=datasets.get(record.id),
        )
        for record in persisted
        # builtin 身份由适配器卡片唯一承载；数据库中同 id 的行（如剖面导出的
        # FK 支撑行）只是运行记录，绝不能再生成一张上传卡
        if record.id not in builtin_ids
    ]
    return cards
