"""Read-only adapter for the built-in v0.3.1 cases (resistivity & friends).

The legacy cards are merged into the v0.4 case list as immutable entries:
the adapter never creates or mutates SQLite rows for them. ``case_service``
is imported lazily so the platform layer stays importable without the api
extra installed.
"""

from __future__ import annotations

from typing import Any, Iterable

from geomodeling.platform.schemas import CaseRecord

BUILTIN_SOURCE_KIND = "builtin_legacy"
UPLOAD_SOURCE_KIND = "upload"


def legacy_case_cards() -> list[dict[str, Any]]:
    """Immutable v0.3.1 case cards, marked as built-in legacy."""

    from geomodeling.api import case_service  # 避免 platform → api 的模块级反向依赖

    cards: list[dict[str, Any]] = []
    for card in case_service.list_cases():
        merged = dict(card)
        merged["source_kind"] = BUILTIN_SOURCE_KIND
        cards.append(merged)
    return cards


def upload_case_card(record: CaseRecord) -> dict[str, Any]:
    """Normalize a persisted upload case into the home-page card shape."""

    return {
        "case_id": record.id,
        "title": record.name,
        "case_type": record.case_type,
        "status": "active",
        "source_kind": UPLOAD_SOURCE_KIND,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "links": {"detail": f"/api/cases/{record.id}", "publish_status": None},
    }


def merged_case_cards(records: Iterable[CaseRecord]) -> list[dict[str, Any]]:
    """Legacy cards first (stable order), then persisted upload cases."""

    return legacy_case_cards() + [upload_case_card(record) for record in records]
