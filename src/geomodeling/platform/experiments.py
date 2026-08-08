"""Experiment search expansion: manual and bounded grid search.

Manual mode expands to exactly one candidate. Grid mode takes the Cartesian
product of discrete candidate values (or an explicit list of parameter
dictionaries) and is hard-capped at 50 combinations. Every candidate gets a
stable fingerprint: SHA-256 of its canonical
algorithm/parameter/validation/grid JSON.

v0.6（设计 §4.2/§5.1/§7.2/§8.2）：实验可携带三个可选专业输入——不可变确认
快照（仅普通 Kriging）、搜索邻域与经验不确定性配置。
``resolve_professional_context`` 在创建期完成全部前置校验并把确认解析为
规范化上下文（确认指纹、模型与参数策略、规范各向异性变换、邻域与不确定
性配置）；展开候选时专业输入合并进候选参数，并连同标准化数据 SHA-256、
折分计划指纹一起进入候选指纹的规范化哈希。legacy 实验（无专业输入）的
展开结果与指纹逐位不变。
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from geomodeling.modeling.anisotropy import KrigingAnisotropySpec
from geomodeling.modeling.professional_contracts import (
    EmpiricalUncertaintySpec,
    NeighborhoodSpec,
)
from geomodeling.platform.errors import (
    PROFESSIONAL_DIAGNOSIS_NOT_SUCCEEDED,
    PlatformError,
)
from geomodeling.platform.repositories import (
    ProfessionalConfirmationRepository,
    ProfessionalDiagnosticRepository,
)
from geomodeling.platform.schemas import Algorithm
from geomodeling.platform.tables import RunStatus

SEARCH_TOO_LARGE = "SEARCH_TOO_LARGE"
MAX_GRID_CANDIDATES = 50

# v0.6 专业实验错误码（稳定公共编码；PROFESSIONAL_CONFIG_INVALID 与
# platform.professional 的诊断/异常配置失败共用同一字符串）。
PROFESSIONAL_CONFIG_INVALID = "PROFESSIONAL_CONFIG_INVALID"


def _finite_number(value: Any, field: str, *, default: float | None = None) -> float:
    """Convert to finite float, applying default for None; raise ValueError on failure."""
    if value is None and default is not None:
        return default
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} 必须是有限数值") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} 必须是有限数值")
    return result


def _positive_ratio(value: Any, field: str, *, default: float | None = None) -> float:
    """Like _finite_number but also requires > 0."""
    result = _finite_number(value, field, default=default)
    if result <= 0:
        raise ValueError(f"{field} 必须大于 0")
    return result
PROFESSIONAL_CAPABILITY_NOT_APPLICABLE = "PROFESSIONAL_CAPABILITY_NOT_APPLICABLE"
PROFESSIONAL_CONFIRMATION_DATASET_MISMATCH = "PROFESSIONAL_CONFIRMATION_DATASET_MISMATCH"
PROFESSIONAL_CONFIRMATION_REQUIRED = "PROFESSIONAL_CONFIRMATION_REQUIRED"
PROFESSIONAL_Z_SCALE_CONFLICT = "PROFESSIONAL_Z_SCALE_CONFLICT"


@dataclass(frozen=True)
class CandidateDefinition:
    index: int
    algorithm: str
    parameters: dict[str, Any]
    fingerprint: str


def _fingerprint(
    algorithm: str,
    parameters: dict[str, Any],
    search: dict[str, Any],
    professional: dict[str, Any] | None = None,
) -> str:
    payload: dict[str, Any] = {
        "algorithm": algorithm,
        "parameters": parameters,
        "grid": search.get("grid"),
        "validation": search.get("validation"),
    }
    if professional is not None:
        # 设计 §4.2：标准化数据 SHA-256、确认快照指纹、搜索邻域、折分计划
        # 指纹与不确定性配置全部入哈希；各向异性变换与其余模型参数已随
        # 合并后的 parameters 进入。不哈希数据库时间戳或路径。
        payload["professional"] = {
            "dataset_sha256": professional.get("dataset_sha256"),
            "confirmation_fingerprint": professional.get("confirmation_fingerprint"),
            "neighborhood": professional.get("neighborhood"),
            "empirical_uncertainty": professional.get("empirical_uncertainty"),
            "validation_fingerprint": professional.get("validation_fingerprint"),
        }
    canonical = json.dumps(
        payload,
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


def _merge_professional_parameters(
    algorithm: str, parameters: dict[str, Any], professional: dict[str, Any] | None
) -> dict[str, Any]:
    """把专业上下文落地为候选参数；legacy（``professional=None``）原样返回。

    搜索邻域注入两种算法。专业 Kriging 候选再叠加确认快照：模型类型与
    参数策略（automatic_candidate → 折内 auto 拟合，基础参数里的人工三元
    组被覆盖；manual → 固定 nugget/sill/range，确认快照已标记 user
    prior）与确认的规范各向异性变换。
    """

    if professional is None:
        return parameters
    merged = dict(parameters)
    neighborhood = professional.get("neighborhood")
    if neighborhood is not None:
        merged["neighborhood"] = neighborhood
    if algorithm == Algorithm.ORDINARY_KRIGING.value and professional.get("confirmation_id"):
        merged["variogram_model"] = professional["model"]
        if professional.get("parameter_strategy") == "manual":
            merged["variogram_mode"] = "manual"
            merged.update(professional["manual_parameters"])
        else:
            merged["variogram_mode"] = "auto"
            for key in ("nugget", "sill", "range"):
                merged.pop(key, None)
        anisotropy = professional.get("anisotropy")
        if anisotropy is not None:
            merged["anisotropy"] = anisotropy
    return merged


def expand_candidates(search: dict[str, Any]) -> list[CandidateDefinition]:
    """Expand an experiment's search definition into candidate definitions."""

    algorithm = Algorithm(search["algorithm"]).value
    mode = search.get("search_mode", "manual")
    raw = search.get("parameters") or {}
    professional = search.get("professional")

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

    definitions: list[CandidateDefinition] = []
    for index, parameters in enumerate(combos):
        merged = _merge_professional_parameters(algorithm, parameters, professional)
        definitions.append(
            CandidateDefinition(
                index=index,
                algorithm=algorithm,
                parameters=merged,
                fingerprint=_fingerprint(algorithm, merged, search, professional),
            )
        )
    return definitions


# ---------------------------------------------------------------------------
# v0.6 专业输入解析：创建期前置校验与规范化上下文
# ---------------------------------------------------------------------------


def _canonical_neighborhood(raw: dict[str, Any]) -> dict[str, Any]:
    try:
        return NeighborhoodSpec.model_validate(raw).model_dump(mode="json")
    except ValidationError as exc:
        raise PlatformError(
            PROFESSIONAL_CONFIG_INVALID, "搜索邻域配置非法", {"reason": str(exc)[:300]}
        ) from exc


def _canonical_uncertainty(raw: dict[str, Any]) -> dict[str, Any]:
    try:
        return EmpiricalUncertaintySpec.model_validate(raw).model_dump(mode="json")
    except ValidationError as exc:
        raise PlatformError(
            PROFESSIONAL_CONFIG_INVALID, "经验不确定性配置非法", {"reason": str(exc)[:300]}
        ) from exc


def _iter_parameter_dicts(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        return [raw]
    return []


def _assert_no_legacy_z_scale(parameters: Any) -> None:
    """legacy 非默认 ``z_scale`` 与专业确认各向异性互斥（§7.2）：前置拒绝。

    Task 8 的参数校验在插值器入口拒绝叠加；实验层在创建期前置拒绝，避免
    确定失败的候选进入运行。覆盖 manual 单组/列表与 grid 候选值列表。
    """

    for params in _iter_parameter_dicts(parameters):
        z_scale = params.get("z_scale")
        values = z_scale if isinstance(z_scale, list) else [z_scale]
        for value in values:
            if value is None:
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                # 非数值由插值器参数契约拒绝，不在此判定冲突
                continue
            if numeric != 1.0:
                raise PlatformError(
                    PROFESSIONAL_Z_SCALE_CONFLICT,
                    "legacy 非默认 z_scale 与专业确认各向异性不得叠加："
                    "专业 Kriging 候选的 z_scale 必须保持默认 1",
                    {"z_scale": value},
                    http_status=409,
                )


def _confirmation_anisotropy_spec(
    anisotropy: dict[str, Any], dimension: str
) -> KrigingAnisotropySpec:
    """把确认的各向异性选择构造为规范 ``KrigingAnisotropySpec``（§7.2）。

    「保持各向同性」生成规范各向同性变换（旋转为 0、比例全 1，与旧各向
    同性距离逐位等价）；否则主向尺度比固定为 1，次/垂向尺度比取确认
    range 比的倒数。

    v0.7.0 整改：三维确认的 ``dip_deg``、``roll_deg`` 和
    ``major_vertical_ratio`` 允许 null/缺失，分别规范化为 0.0、0.0、1.0。
    ``azimuth_deg`` 和 ``major_minor_ratio`` 仍为必填。所有角度必须有限，
    所有比例必须有限且大于 0。
    """

    if anisotropy.get("keep_isotropic"):
        return KrigingAnisotropySpec.isotropic(dimension)
    try:
        minor_ratio = _positive_ratio(anisotropy.get("major_minor_ratio"), "major_minor_ratio")
        azimuth = _finite_number(anisotropy.get("azimuth_deg"), "azimuth_deg")
        if dimension == "3d":
            vertical_ratio = _positive_ratio(
                anisotropy.get("major_vertical_ratio"), "major_vertical_ratio",
                default=1.0,
            )
            return KrigingAnisotropySpec(
                dimension=dimension,
                azimuth_deg=azimuth,
                dip_deg=_finite_number(anisotropy.get("dip_deg"), "dip_deg", default=0.0),
                roll_deg=_finite_number(anisotropy.get("roll_deg"), "roll_deg", default=0.0),
                major_scale=1.0,
                minor_scale=1.0 / minor_ratio,
                vertical_scale=1.0 / vertical_ratio,
            )
        return KrigingAnisotropySpec(
            dimension=dimension,
            azimuth_deg=azimuth,
            major_scale=1.0,
            minor_scale=1.0 / minor_ratio,
        )
    except (ValueError, ZeroDivisionError) as exc:
        raise PlatformError(
            PROFESSIONAL_CONFIG_INVALID,
            "确认各向异性配置非法，请返回空间结构分析重新确认",
            {"reason": str(exc)[:300]},
            http_status=409,
        ) from exc


def resolve_professional_context(
    session, request, dataset
) -> dict[str, Any] | None:
    """解析实验的专业输入，返回规范化上下文；legacy 请求返回 ``None``。

    规则（设计 §4.2/§5.1/§7.2/§8.2）：

    - 三字段全缺 → legacy，行为与指纹逐位不变；
    - IDW 携带确认 → 409 ``PROFESSIONAL_CAPABILITY_NOT_APPLICABLE``
      （确认只由 Kriging 诊断产生）；
    - Kriging 专业模式（确认非空）：确认必须存在（404）、属于 succeeded
      诊断（409）、诊断的数据版本与实验一致
      （409 ``PROFESSIONAL_CONFIRMATION_DATASET_MISMATCH``），且不得叠加
      legacy 非默认 ``z_scale``（409 ``PROFESSIONAL_Z_SCALE_CONFLICT``）；
    - Kriging 携带邻域/经验不确定性但缺确认 →
      409 ``PROFESSIONAL_CONFIRMATION_REQUIRED``（专业 Kriging 候选的
      confirmation_id 必填，§5.1）。
    """

    confirmation_id = request.professional_confirmation_id
    if confirmation_id is None and request.neighborhood is None and request.empirical_uncertainty is None:
        return None

    algorithm = Algorithm(request.algorithm)
    if confirmation_id is not None and algorithm != Algorithm.ORDINARY_KRIGING:
        raise PlatformError(
            PROFESSIONAL_CAPABILITY_NOT_APPLICABLE,
            "IDW 不适用变异函数确认快照（确认只由 Kriging 诊断产生）",
            {"algorithm": algorithm.value},
            http_status=409,
        )
    if confirmation_id is None and algorithm == Algorithm.ORDINARY_KRIGING:
        raise PlatformError(
            PROFESSIONAL_CONFIRMATION_REQUIRED,
            "专业 Kriging 候选必须引用匹配数据版本的不可变确认快照",
            {"algorithm": algorithm.value},
            http_status=409,
        )

    neighborhood = (
        _canonical_neighborhood(request.neighborhood)
        if request.neighborhood is not None
        else None
    )
    empirical_uncertainty = (
        _canonical_uncertainty(request.empirical_uncertainty)
        if request.empirical_uncertainty is not None
        else None
    )
    context: dict[str, Any] = {
        "confirmation_id": None,
        "confirmation_fingerprint": None,
        "model": None,
        "parameter_strategy": None,
        "manual_parameters": None,
        "anisotropy": None,
        "neighborhood": neighborhood,
        "empirical_uncertainty": empirical_uncertainty,
    }
    if confirmation_id is None:
        return context

    confirmation = ProfessionalConfirmationRepository(session).get(confirmation_id)
    diagnosis = ProfessionalDiagnosticRepository(session).get(confirmation.diagnostic_id)
    if diagnosis.status != RunStatus.SUCCEEDED.value:
        raise PlatformError(
            PROFESSIONAL_DIAGNOSIS_NOT_SUCCEEDED,
            "只有成功诊断的确认快照才能驱动专业实验",
            {"diagnosis_id": diagnosis.id, "status": diagnosis.status},
            http_status=409,
        )
    if diagnosis.dataset_version_id != request.dataset_version_id:
        raise PlatformError(
            PROFESSIONAL_CONFIRMATION_DATASET_MISMATCH,
            "确认快照所属诊断的数据版本与实验数据集不一致",
            {
                "confirmation_id": confirmation_id,
                "diagnosis_dataset_version_id": diagnosis.dataset_version_id,
                "dataset_version_id": request.dataset_version_id,
            },
            http_status=409,
        )
    _assert_no_legacy_z_scale(request.parameters)

    config = confirmation.config
    mapping = (dataset.profile or {}).get("mapping", {})
    dimension = "3d" if mapping.get("dimension") == "3d" else "2d"
    anisotropy = _confirmation_anisotropy_spec(config.get("anisotropy") or {}, dimension)
    context.update(
        {
            "confirmation_id": confirmation.id,
            "confirmation_fingerprint": confirmation.fingerprint,
            "model": config.get("model"),
            "parameter_strategy": config.get("parameter_strategy"),
            "manual_parameters": config.get("manual_parameters"),
            "anisotropy": anisotropy.model_dump(mode="json"),
        }
    )
    return context
