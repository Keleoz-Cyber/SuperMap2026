"""Answer presets: declarative case templates for the v0.4 workflow.

Presets describe expected dimension, semantic fields, value unit, coordinate
kind, recommended parameter grids and demo copy. They are pure data (JSON in
``config/presets/``), never contain absolute paths, and never auto-import
private data — an ``upload_required`` preset still needs the user to upload
the derived standardized file and pass the current quality gates, while a
``domain_adapter`` preset names one whitelisted adapter (no plugin loading)
that runs its own contract and golden gates.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from geomodeling.platform.errors import PlatformError

PRESET_INVALID = "PRESET_INVALID"

PRESET_DIR = Path("config/presets")

# 嵌入式绝对路径形态：Windows 盘符与 UNC 可出现在文本任意位置；
# POSIX 绝对路径只认串首（避免误伤单位/比例文本）。
_EMBEDDED_ABS_PATH_RE = re.compile(r"[A-Za-z]:[\\/]|\\\\")
_POSIX_ABS_START_RE = re.compile(r"^/")

_ALLOWED_SOURCES = frozenset({"builtin_legacy", "upload_required", "domain_adapter"})
# domain_adapter 预设必须声明已登记的领域适配器；此处仅白名单校验，
# 不做通用插件加载。
_ALLOWED_DOMAIN_ADAPTERS = frozenset({"microseismic_dat_v05"})
_ALLOWED_DIMENSIONS = frozenset({"2d", "3d"})
# geographic 未投影不可建模（质量门禁一致）；预设不声明它
_ALLOWED_COORDINATE_KINDS = frozenset({"local_linear", "projected"})

_REQUIRED_KEYS = frozenset(
    {
        "preset_id",
        "title",
        "source",
        "dimension",
        "semantic_fields",
        "value_unit",
        "coordinate_kind",
        "recommended_search",
        "demo_copy",
        "boundaries",
    }
)

MAX_PRESET_COMBINATIONS = 50


def _scan_absolute_paths(value: Any, trail: str = "$") -> str | None:
    """递归扫描预设内容；返回首个绝对路径形态字段的路径表达式。"""

    if isinstance(value, str):
        if _EMBEDDED_ABS_PATH_RE.search(value) or _POSIX_ABS_START_RE.match(value):
            return trail
        return None
    if isinstance(value, dict):
        for key, item in value.items():
            hit = _scan_absolute_paths(item, f"{trail}.{key}")
            if hit:
                return hit
    if isinstance(value, list):
        for idx, item in enumerate(value):
            hit = _scan_absolute_paths(item, f"{trail}[{idx}]")
            if hit:
                return hit
    return None


def _combination_count(parameters: dict[str, Any]) -> int:
    count = 1
    for value in parameters.values():
        count *= len(value) if isinstance(value, list) else 1
    return count


def _fail(message: str, details: dict[str, Any]) -> None:
    raise PlatformError(PRESET_INVALID, message, details, http_status=400)


def load_preset(source: str | Path) -> dict[str, Any]:
    """Load and validate one preset by name (``config/presets/``) or path."""

    if isinstance(source, Path) or (isinstance(source, str) and source.endswith(".json")):
        path = Path(source)
        name = path.stem
    else:
        name = source
        path = PRESET_DIR / f"{name}.json"
    if not path.exists():
        _fail("预设不存在", {"preset": name})

    try:
        preset = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _fail("预设不是合法 JSON", {"preset": name, "error": str(exc)})

    missing = sorted(_REQUIRED_KEYS - preset.keys())
    if missing:
        _fail("预设缺少必填键", {"preset": name, "missing": missing})
    if preset["source"] not in _ALLOWED_SOURCES:
        _fail("预设 source 非法", {"preset": name, "source": preset["source"]})
    if preset["source"] == "domain_adapter":
        adapter_id = preset.get("adapter_id")
        if adapter_id not in _ALLOWED_DOMAIN_ADAPTERS:
            _fail("预设 adapter_id 未登记", {"preset": name, "adapter_id": adapter_id})
    if preset["dimension"] not in _ALLOWED_DIMENSIONS:
        _fail("预设 dimension 非法", {"preset": name, "dimension": preset["dimension"]})
    if preset["coordinate_kind"] not in _ALLOWED_COORDINATE_KINDS:
        _fail(
            "预设 coordinate_kind 非法（geographic 未投影不可建模）",
            {"preset": name, "coordinate_kind": preset["coordinate_kind"]},
        )
    if not isinstance(preset["boundaries"], list):
        _fail("预设 boundaries 必须为列表", {"preset": name})

    leaked = _scan_absolute_paths(preset)
    if leaked:
        _fail("预设不得包含本机绝对路径", {"preset": name, "field": leaked})

    search = preset["recommended_search"]
    count = _combination_count(search.get("parameters") or {})
    if not 1 <= count <= MAX_PRESET_COMBINATIONS:
        _fail(
            "推荐搜索组合数超出上限",
            {"preset": name, "combinations": count, "max": MAX_PRESET_COMBINATIONS},
        )

    search_grids = preset.get("search_grids")
    if search_grids is not None:
        if not isinstance(search_grids, dict) or not search_grids:
            _fail("预设 search_grids 必须为非空映射", {"preset": name})
        for algorithm, parameters in search_grids.items():
            if not isinstance(parameters, dict):
                _fail(
                    "预设 search_grids 参数必须为映射",
                    {"preset": name, "algorithm": algorithm},
                )
            grid_count = _combination_count(parameters)
            if not 1 <= grid_count <= MAX_PRESET_COMBINATIONS:
                _fail(
                    "推荐搜索组合数超出上限",
                    {
                        "preset": name,
                        "algorithm": algorithm,
                        "combinations": grid_count,
                        "max": MAX_PRESET_COMBINATIONS,
                    },
                )
    return preset


def list_presets() -> list[str]:
    """Names of every preset shipped under ``config/presets/``."""

    if not PRESET_DIR.exists():
        return []
    return sorted(path.stem for path in PRESET_DIR.glob("*.json"))
