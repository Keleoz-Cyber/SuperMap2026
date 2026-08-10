"""v0.9.0 Task 10: AI assisted result review API (design §9.5).

POST /api/results/{result_id}/ai-analysis — explicit generate (quick|review)
GET  /api/results/{result_id}/ai-analysis/latest — read-only latest record
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from geomodeling.api.deps import get_platform_runtime
from geomodeling.platform import PlatformRuntime
from geomodeling.platform.ai_analysis import (
    generate_ai_analysis,
    get_latest_ai_analysis,
)
from geomodeling.platform.ai_analysis_contracts import AIAnalysisRequest
from geomodeling.platform.repositories import require_active_candidate

router = APIRouter(tags=["v0.9-ai-analysis"])


@router.post("/api/results/{result_id}/ai-analysis", status_code=201)
def create_ai_analysis(
    result_id: str,
    request: AIAnalysisRequest,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    require_active_candidate(runtime, result_id)
    record = generate_ai_analysis(
        runtime,
        result_id,
        mode=request.mode,
        regenerate=request.regenerate,
    )
    return record.model_dump(mode="json")


@router.get("/api/results/{result_id}/ai-analysis/latest")
def get_latest(
    result_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    require_active_candidate(runtime, result_id)
    record = get_latest_ai_analysis(runtime, result_id)
    if record is None:
        from geomodeling.platform.errors import PlatformError

        raise PlatformError(
            "AI_ANALYSIS_NOT_FOUND",
            "尚无 AI 辅助分析记录",
            {"result_id": result_id},
            http_status=404,
        )
    return record.model_dump(mode="json")
