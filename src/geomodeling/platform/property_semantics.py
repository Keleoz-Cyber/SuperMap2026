"""Authoritative public property semantics for built-in preset cases."""

from __future__ import annotations

from typing import Any


RESISTIVITY_CASE_ID = "resistivity"
RESISTIVITY_VALUE_NAME = "RHO"
RESISTIVITY_VALUE_UNIT = "Ω·m"


def normalize_property_unit(
    *,
    case_id: str | None,
    workspace_kind: str | None,
    value_name: str | None,
    value_unit: Any,
) -> str | None:
    """Return the authoritative unit without guessing user-upload semantics."""

    if (
        case_id == RESISTIVITY_CASE_ID
        and workspace_kind == "builtin_preset"
        and value_name == RESISTIVITY_VALUE_NAME
    ):
        return RESISTIVITY_VALUE_UNIT
    if value_unit is None:
        return None
    return str(value_unit)


def normalize_mapping(
    mapping: dict[str, Any], *, case_id: str | None, workspace_kind: str | None
) -> dict[str, Any]:
    normalized = dict(mapping)
    normalized["value_unit"] = normalize_property_unit(
        case_id=case_id,
        workspace_kind=workspace_kind,
        value_name=str(mapping.get("value_name") or "") or None,
        value_unit=mapping.get("value_unit"),
    )
    return normalized
