"""v0.7.0 Batch 1：微震速度 CSV 预置源合同。

受控 CSV（``data/presets/microseismic/microseismic-vx-1911.csv``）是用户指定
标准化文件的原字节拷贝：9 列表头含 SAMPLE_IDS/POINT_ID/LINE_ID/N_MERGED
溯源列与 DEPTH_M 参照列；建模只使用 4 个建模列
``X_LOCAL_M/Y_LOCAL_M/Z_LOCAL_M/VX_KM_S``（Vx 单位恒为 km/s，绝不静默换算）。

加载器 fail-closed：完整表头、1911 行、全部数值列有限、XYZ 唯一；任何
不匹配抛出 ``PRESET_SOURCE_INVALID``。本模块绝不向公共层返回本机源路径。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from geomodeling.platform.errors import (
    PRESET_BASELINE_INVALID,
    PRESET_SOURCE_INVALID,
    PlatformError,
)

PRESET_CASE_ID = "builtin-microseismic-vx-1911"
PRESET_VERSION = "microseismic-vx-1911/v1"

#: 受控 CSV 完整表头（原字节拷贝的 9 列合同；溯源列随文件保留为证据）
SOURCE_COLUMNS = (
    "SAMPLE_IDS",
    "POINT_ID",
    "LINE_ID",
    "X_LOCAL_M",
    "Y_LOCAL_M",
    "DEPTH_M",
    "Z_LOCAL_M",
    "VX_KM_S",
    "N_MERGED",
)

#: 建模列（顺序固定）：局部线性坐标 + Vx
REQUIRED_COLUMNS = ("X_LOCAL_M", "Y_LOCAL_M", "Z_LOCAL_M", "VX_KM_S")

#: 数值列有限性合同（溯源 ID 列不参与数值校验）
_NUMERIC_COLUMNS = ("X_LOCAL_M", "Y_LOCAL_M", "DEPTH_M", "Z_LOCAL_M", "VX_KM_S", "N_MERGED")

EXPECTED_ROW_COUNT = 1911

DEFAULT_PRESET_CSV = Path("data/presets/microseismic/microseismic-vx-1911.csv")

#: 入库受控字节身份（.gitattributes `*.csv text eol=lf` 归一化后的 LF 形态；
#: 与仓库既有黄金 CSV 合同同一口径，任何平台检出字节一致）
TRACKED_CSV_SHA256 = "ea3917c2ee228953f39122fc52b864d802de9c9835f07a57c4c88585a501e510"
TRACKED_CSV_BYTES = 108_938

#: 溯源：用户指定原始标准化文件的身份（原始 CRLF 字节形态；仅作审计记录，
#: 运行时绝不读取该路径）
ORIGINAL_SOURCE_NAME = "微震局部三维点_3Sigma_去重均值_1911.csv"
ORIGINAL_SOURCE_SHA256 = "4011de85e1fa7e49999fc5ae66a73e00a59dbec372a417ae0728d0a338c7765e"
ORIGINAL_SOURCE_BYTES = 110_850


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class PresetSource:
    """已验证的微震预置源：建模框架 + 摘要指纹（无本机路径）。"""

    frame: pd.DataFrame
    sha256: str
    row_count: int
    columns: tuple[str, ...]
    source_columns: tuple[str, ...]
    value_unit: str = "km/s"
    coordinate_kind: str = "local_linear"


def load_microseismic_preset(path: Path) -> PresetSource:
    """加载并验证受控微震预置 CSV；任何合同违反 fail-closed。"""

    if not path.is_file():
        raise PlatformError(
            PRESET_SOURCE_INVALID,
            "微震预置 CSV 不存在或不可读",
            {"reason": "missing_file"},
            http_status=409,
        )
    try:
        raw = pd.read_csv(path, encoding="utf-8-sig")
    except Exception as exc:  # noqa: BLE001 - 统一翻译为稳定合同错误
        raise PlatformError(
            PRESET_SOURCE_INVALID,
            "微震预置 CSV 解析失败",
            {"reason": type(exc).__name__},
            http_status=409,
        ) from exc
    if tuple(raw.columns) != SOURCE_COLUMNS:
        raise PlatformError(
            PRESET_SOURCE_INVALID,
            "微震预置 CSV 表头合同不匹配",
            {"expected_columns": list(SOURCE_COLUMNS)},
            http_status=409,
        )
    if len(raw) != EXPECTED_ROW_COUNT:
        raise PlatformError(
            PRESET_SOURCE_INVALID,
            "微震预置 CSV 行数合同不匹配",
            {"expected_rows": EXPECTED_ROW_COUNT, "actual_rows": len(raw)},
            http_status=409,
        )
    numeric = raw.loc[:, _NUMERIC_COLUMNS].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric.to_numpy(dtype="float64")).all():
        raise PlatformError(
            PRESET_SOURCE_INVALID,
            "微震预置 CSV 含非有限数值",
            {"columns": list(_NUMERIC_COLUMNS)},
            http_status=409,
        )
    modeling = raw.loc[:, REQUIRED_COLUMNS].apply(pd.to_numeric, errors="coerce")
    if modeling.iloc[:, :3].duplicated().any():
        raise PlatformError(
            PRESET_SOURCE_INVALID,
            "微震预置 CSV 含重复 XYZ 坐标",
            {"columns": list(REQUIRED_COLUMNS[:3])},
            http_status=409,
        )
    return PresetSource(
        frame=modeling.astype("float64"),
        sha256=_sha256(path),
        row_count=len(modeling),
        columns=REQUIRED_COLUMNS,
        source_columns=SOURCE_COLUMNS,
    )


# ---------------------------------------------------------------------------
# Task 2：官方普通克里金候选矩阵、分析与基线验证
# ---------------------------------------------------------------------------

import json  # noqa: E402
from typing import Any  # noqa: E402

from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator  # noqa: E402
from geomodeling.modeling.metrics import common_valid_mask, compute_metrics  # noqa: E402
from geomodeling.modeling.splits import build_spatial_splits  # noqa: E402
from geomodeling.platform.schemas import SpatialValidationSpec  # noqa: E402
from geomodeling.platform.tables import dumps_canonical  # noqa: E402

#: 固定 27 成员候选矩阵（设计 §5.2；不得扩展为插件式搜索空间）
VARIOGRAM_MODELS = ("spherical", "exponential", "gaussian")
NEIGHBOR_COUNTS = (12, 24, 36)
Z_SCALES = (0.5, 1.0, 2.0)

#: 固定空间 5 折交叉验证合同（种子钉死，报告/基线均记录）
VALIDATION_CONTRACT = {"method": "spatial_kfold", "folds": 5, "seed": 20260723}

#: 官方网格分辨率（米）：三轴统一 50 m（沿用 v0.5 正式网格约定）
GRID_RESOLUTION_M = 50.0
GRID_MAX_CELLS = 1_000_000

BASELINE_SCHEMA = "v0.7.0-microseismic-official-baseline/v1"
REPORT_SCHEMA = "v0.7.0-microseismic-candidate-report/v1"
DEFAULT_BASELINE_PATH = Path("config/presets/microseismic-official-baseline.json")

SELECTION_RULE = ("rmse_asc", "mae_asc", "r2_desc", "canonical_params_asc")


def preset_candidate_matrix() -> list[dict[str, Any]]:
    """固定 27 成员普通克里金候选矩阵（确定性顺序）。"""

    return [
        {"variogram_model": model, "neighbor_count": neighbors, "z_scale": z_scale}
        for model in VARIOGRAM_MODELS
        for neighbors in NEIGHBOR_COUNTS
        for z_scale in Z_SCALES
    ]


@dataclass(frozen=True)
class PresetCandidateReport:
    """候选分析报告：全部 27 个候选的公共有效集指标 + 指纹。"""

    candidates: tuple[dict[str, Any], ...]
    source_sha256: str
    validation: dict[str, Any]
    common_valid_count: int
    sha256: str


def analyze_preset_candidates(source: PresetSource) -> PresetCandidateReport:
    """在已验证源上执行固定候选矩阵的空间折分评估（纯计算，不落库）。

    复用生产普通克里金插值器与公共有效集指标合同：逐折仅训练集拟合、
    验证集预测；27 个候选的公共有效掩膜上交并集后复算指标。候选失败
    记录结构化 error 并继续（排名时自动排除），绝不静默通过。
    """

    frame = source.frame.rename(
        columns={"X_LOCAL_M": "x", "Y_LOCAL_M": "y", "Z_LOCAL_M": "z", "VX_KM_S": "value"}
    )
    points = frame[["x", "y", "z"]].to_numpy(dtype="float64")
    values = frame["value"].to_numpy(dtype="float64")
    folds = build_spatial_splits(
        points, "3d", SpatialValidationSpec.model_validate(VALIDATION_CONTRACT)
    )

    interpolator = OrdinaryKrigingInterpolator()
    predictions_by_candidate: dict[str, dict[int, tuple[float, bool]]] = {}
    errors: dict[str, str] = {}
    for params in preset_candidate_matrix():
        key = dumps_canonical(params)
        try:
            validated = interpolator.validate_parameters(params, "3d")
            per_row: dict[int, tuple[float, bool]] = {}
            for fold in folds:
                fitted = interpolator.fit(
                    points[fold.training_indices], values[fold.training_indices], validated
                )
                batch = fitted.predict(
                    points[fold.validation_indices], cancel=lambda: False
                )
                for pos, row_index in enumerate(fold.validation_indices):
                    per_row[int(row_index)] = (float(batch.values[pos]), bool(batch.is_nodata[pos]))
            predictions_by_candidate[key] = per_row
        except Exception as exc:  # noqa: BLE001 - 候选失败结构化记录，不中断矩阵
            errors[key] = type(exc).__name__

    # 公共有效掩膜：全部成功候选的验证预测逐点求交
    n_rows = len(frame)
    succeeded = [k for k in predictions_by_candidate if k not in errors]
    mask_input: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for key in succeeded:
        per_row = predictions_by_candidate[key]
        preds = np.array([per_row[i][0] for i in range(n_rows)], dtype="float64")
        nodata = np.array([per_row[i][1] for i in range(n_rows)], dtype="bool")
        mask_input[key] = (preds, nodata)
    shared_mask = common_valid_mask(mask_input)

    candidates: list[dict[str, Any]] = []
    for params in preset_candidate_matrix():
        key = dumps_canonical(params)
        if key in errors:
            candidates.append({"params": params, "metrics": None, "error": errors[key]})
            continue
        preds, nodata = mask_input[key]
        summary = compute_metrics(values, preds, shared_mask, is_nodata=nodata)
        metrics = {
            "rmse": summary.rmse,
            "mae": summary.mae,
            "r2": summary.r2,
            "bias": summary.bias,
            "coverage": summary.coverage,
            "common_valid_count": summary.common_valid_count,
        }
        candidates.append({"params": params, "metrics": metrics, "error": None})

    payload = {
        "schema": REPORT_SCHEMA,
        "preset_version": PRESET_VERSION,
        "source_sha256": source.sha256,
        "validation": VALIDATION_CONTRACT,
        "selection_rule": list(SELECTION_RULE),
        "common_valid_count": int(shared_mask.sum()),
        "candidates": candidates,
    }
    return PresetCandidateReport(
        candidates=tuple(candidates),
        source_sha256=source.sha256,
        validation=dict(VALIDATION_CONTRACT),
        common_valid_count=int(shared_mask.sum()),
        sha256=hashlib.sha256(dumps_canonical(payload).encode("utf-8")).hexdigest(),
    )


def report_to_json(report: PresetCandidateReport) -> dict[str, Any]:
    """报告落盘形态（canonical JSON 的字典源；sha 与该形态一致）。"""

    return {
        "schema": REPORT_SCHEMA,
        "preset_version": PRESET_VERSION,
        "source_sha256": report.source_sha256,
        "validation": report.validation,
        "selection_rule": list(SELECTION_RULE),
        "common_valid_count": report.common_valid_count,
        "candidates": list(report.candidates),
        "sha256": report.sha256,
    }


def rank_preset_candidates(candidates: list[dict[str, Any]] | tuple[dict[str, Any], ...]):
    """排名：仅有限公共指标候选参与；rmse→mae→r2→规范化参数字节序。"""

    eligible = []
    for entry in candidates:
        metrics = entry.get("metrics")
        if not metrics:
            continue
        rmse = float(metrics.get("rmse", "nan"))
        mae = float(metrics.get("mae", "nan"))
        r2 = float(metrics.get("r2", "nan"))
        if not (np.isfinite(rmse) and np.isfinite(mae) and np.isfinite(r2)):
            continue
        eligible.append(entry)
    return sorted(
        eligible,
        key=lambda entry: (
            float(entry["metrics"]["rmse"]),
            float(entry["metrics"]["mae"]),
            -float(entry["metrics"]["r2"]),
            dumps_canonical(entry["params"]),
        ),
    )


@dataclass(frozen=True)
class OfficialBaseline:
    """评审冻结的官方基线（不可变；指纹与选择可复算）。"""

    schema: str
    source_sha256: str
    candidate_report_sha256: str
    validation: dict[str, Any]
    selection_rule: tuple[str, ...]
    winner: dict[str, Any]
    grid: dict[str, Any]
    selection_reason: str
    sha256: str


def load_official_baseline(path: Path = DEFAULT_BASELINE_PATH) -> OfficialBaseline:
    if not path.is_file():
        raise PlatformError(
            PRESET_BASELINE_INVALID,
            "官方基线文件不存在",
            {"reason": "missing_baseline"},
            http_status=409,
        )
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return OfficialBaseline(
            schema=doc["schema"],
            source_sha256=doc["source_sha256"],
            candidate_report_sha256=doc["candidate_report_sha256"],
            validation=doc["validation"],
            selection_rule=tuple(doc["selection_rule"]),
            winner=doc["winner"],
            grid=doc["grid"],
            selection_reason=doc["selection_reason"],
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    except PlatformError:
        raise
    except Exception as exc:  # noqa: BLE001 - 统一翻译为稳定合同错误
        raise PlatformError(
            PRESET_BASELINE_INVALID,
            "官方基线文件解析失败",
            {"reason": type(exc).__name__},
            http_status=409,
        )


def _grid_cells(bounds: list[list[float]], resolution: list[float]) -> int:
    """与 ``modeling.grid._axis_nodes`` 同一口径：最近节点数规则。"""

    cells = 1
    for (lo, hi), res in zip(bounds, resolution):
        cells *= max(2, int(round((hi - lo) / res)) + 1)
    return cells


def verify_official_baseline(
    source: PresetSource,
    baseline: OfficialBaseline,
    *,
    report: PresetCandidateReport | None = None,
) -> None:
    """验证基线与受控源/候选报告的身份链；任何不匹配 fail-closed。"""

    def reject(reason: str) -> None:
        raise PlatformError(
            PRESET_BASELINE_INVALID,
            "官方基线与受控输入不一致",
            {"reason": reason},
            http_status=409,
        )

    if baseline.schema != BASELINE_SCHEMA:
        reject("schema")
    if baseline.source_sha256 != source.sha256:
        reject("source_sha256")
    if tuple(baseline.selection_rule) != SELECTION_RULE:
        reject("selection_rule")
    if baseline.validation != VALIDATION_CONTRACT:
        reject("validation")
    sha = baseline.candidate_report_sha256
    if (
        not isinstance(sha, str)
        or len(sha) != 64
        or any(c not in "0123456789abcdef" for c in sha)
    ):
        reject("candidate_report_sha256")
    winner_params = baseline.winner.get("parameters") if baseline.winner else None
    if baseline.winner.get("algorithm") != "ordinary_kriging" or winner_params not in (
        preset_candidate_matrix()
    ):
        reject("winner_parameters")
    metrics = baseline.winner.get("metrics") or {}
    if not all(
        np.isfinite(float(metrics.get(name, "nan"))) for name in ("rmse", "mae", "r2", "bias")
    ):
        reject("winner_metrics")

    bounds = baseline.grid.get("bounds")
    resolution = baseline.grid.get("resolution")
    max_cells = int(baseline.grid.get("max_cells", 0))
    if (
        not isinstance(bounds, list)
        or len(bounds) != 3
        or not isinstance(resolution, list)
        or len(resolution) != 3
        or any(not (hi > lo) or res <= 0 for (lo, hi), res in zip(bounds, resolution))
    ):
        reject("grid_contract")
    cells = _grid_cells(bounds, resolution)
    if cells <= 0 or cells > max_cells or max_cells > GRID_MAX_CELLS:
        reject("grid_cells")
    for idx, col in enumerate(REQUIRED_COLUMNS[:3]):
        lo, hi = float(bounds[idx][0]), float(bounds[idx][1])
        if lo > float(source.frame[col].min()) or hi < float(source.frame[col].max()):
            reject("grid_bounds_coverage")

    if report is not None:
        if report.source_sha256 != source.sha256:
            reject("report_source_sha256")
        if report.sha256 != baseline.candidate_report_sha256:
            reject("candidate_report_sha256")
        ranked = rank_preset_candidates(report.candidates)
        if not ranked or ranked[0]["params"] != winner_params:
            reject("winner_not_report_top")
