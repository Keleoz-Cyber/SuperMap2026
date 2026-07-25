"""Experiment search expansion: manual and bounded grid search.

Manual mode expands to exactly one candidate. Grid mode takes the Cartesian
product of discrete candidate values (or an explicit list of parameter
dictionaries) and is hard-capped at 50 combinations. Every candidate gets a
stable fingerprint: SHA-256 of its canonical
algorithm/parameter/validation/grid JSON.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass
from typing import Any

from geomodeling.platform.errors import PlatformError
from geomodeling.platform.schemas import Algorithm

SEARCH_TOO_LARGE = "SEARCH_TOO_LARGE"
MAX_GRID_CANDIDATES = 50


@dataclass(frozen=True)
class CandidateDefinition:
    index: int
    algorithm: str
    parameters: dict[str, Any]
    fingerprint: str


def _fingerprint(algorithm: str, parameters: dict[str, Any], search: dict[str, Any]) -> str:
    canonical = json.dumps(
        {
            "algorithm": algorithm,
            "parameters": parameters,
            "grid": search.get("grid"),
            "validation": search.get("validation"),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _combinations(space: dict[str, list[Any]]) -> list[dict[str, Any]]:
    keys = sorted(space)
    if not keys:
        return []
    combos = []
    for values in itertools.product(*(space[key] for key in keys)):
        combos.append(dict(zip(keys, values)))
    return combos


def expand_candidates(search: dict[str, Any]) -> list[CandidateDefinition]:
    """Expand an experiment's search definition into candidate definitions."""

    algorithm = Algorithm(search["algorithm"]).value
    mode = search.get("search_mode", "manual")
    raw = search.get("parameters") or {}

    if mode == "manual":
        if isinstance(raw, list):
            if len(raw) != 1:
                raise PlatformError(
                    SEARCH_TOO_LARGE,
                    f"manual 模式只允许一个参数组合（收到 {len(raw)} 个）",
                    {"candidates": len(raw)},
                    http_status=409,
                )
            combos = [dict(raw[0])]
        else:
            combos = [dict(raw)]
    else:
        if isinstance(raw, list):
            combos = [dict(item) for item in raw]
        else:
            if any(not isinstance(v, list) for v in raw.values()):
                raise PlatformError(
                    SEARCH_TOO_LARGE,
                    "grid 模式的参数值必须为离散候选值列表",
                    {"parameters": raw},
                    http_status=400,
                )
            combos = _combinations(raw)
        if not combos:
            raise PlatformError(
                SEARCH_TOO_LARGE,
                "grid 模式产生了 0 个候选组合",
                {"candidates": 0},
                http_status=409,
            )
        if len(combos) > MAX_GRID_CANDIDATES:
            raise PlatformError(
                SEARCH_TOO_LARGE,
                f"网格搜索组合数 {len(combos)} 超过硬上限 {MAX_GRID_CANDIDATES}",
                {"candidates": len(combos), "max": MAX_GRID_CANDIDATES},
                http_status=409,
            )

    return [
        CandidateDefinition(
            index=index,
            algorithm=algorithm,
            parameters=parameters,
            fingerprint=_fingerprint(algorithm, parameters, search),
        )
        for index, parameters in enumerate(combos)
    ]
