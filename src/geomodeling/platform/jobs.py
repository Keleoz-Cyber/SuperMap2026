"""Job helpers: quality gate enforcement for experiment creation."""

from __future__ import annotations

from typing import Any

from geomodeling.platform.errors import PlatformError

QUALITY_GATE_FAILED = "QUALITY_GATE_FAILED"


def assert_quality_gate(profile: dict[str, Any]) -> None:
    """Experiments may only be created from a usable dataset.

    A blocked quality report or missing evaluation rejects creation; open
    warnings must have been explicitly confirmed first.
    """

    quality = (profile or {}).get("quality")
    if quality is None:
        raise PlatformError(
            QUALITY_GATE_FAILED,
            "尚未执行质量校验，不能创建实验",
            {"reason": "quality_not_evaluated"},
            http_status=409,
        )
    status = quality.get("status")
    if status == "blocked":
        raise PlatformError(
            QUALITY_GATE_FAILED,
            "质量校验被阻断（存在阻断项），不能创建实验",
            {"reason": "quality_blocked", "issues": quality.get("issues", [])},
            http_status=409,
        )
    if status == "warnings" and not quality.get("confirmed"):
        raise PlatformError(
            QUALITY_GATE_FAILED,
            "质量警告尚未确认，不能创建实验",
            {"reason": "warnings_not_confirmed"},
            http_status=409,
        )
