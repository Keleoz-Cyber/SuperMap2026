"""v0.7.0 Batch 1：微震速度 CSV 预置源合同。

受控 CSV 内置在仓库 ``example_data/微震局部三维点_3Sigma_去重均值_1911.csv``
（v0.8.0 第三批起默认源统一解析到项目内 ``example_data/``；字节级冻结合同见
tests/test_example_data_contract.py）。该文件即用户指定标准化文件本身
（纯 CRLF + UTF-8 BOM 形态，``example_data/*.csv`` 关闭 EOL 归一化）：
9 列表头含 SAMPLE_IDS/POINT_ID/LINE_ID/N_MERGED 溯源列与 DEPTH_M 参照列；
建模只使用 4 个建模列 ``X_LOCAL_M/Y_LOCAL_M/Z_LOCAL_M/VX_KM_S``
（Vx 单位恒为 km/s，绝不静默换算）。v0.7.0 时代的 LF 归一化入库副本
（``data/presets/microseismic/microseismic-vx-1911.csv``）已随默认源切换
删除——同一逻辑数据，字节身份统一回原始 CRLF+BOM 形态。

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
from geomodeling.platform.settings import example_data_path

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

#: 内置默认源（v0.8.0 第三批：项目内 example_data/ 字节冻结合同；
#: 解析器拒绝目录穿越，缺失即 PRESET_SOURCE_INVALID）
DEFAULT_PRESET_CSV = example_data_path("微震局部三维点_3Sigma_去重均值_1911.csv")

#: 内置受控字节身份：原始标准化文件本身（纯 CRLF + UTF-8 BOM 形态，
#: ``example_data/*.csv -text`` 关闭 EOL 归一化，任何平台检出字节一致）。
#: 身份迁移注记：v0.7.0 时代入库副本为 .gitattributes 归一化后的 LF 形态
#: （sha256 ea3917c2…、108,938 字节），逐行数据与本文件相同；v0.8.0 第三批
#: 删除该副本，字节身份统一回原始 CRLF+BOM 形态（同一逻辑数据）。
TRACKED_CSV_SHA256 = "4011de85e1fa7e49999fc5ae66a73e00a59dbec372a417ae0728d0a338c7765e"
TRACKED_CSV_BYTES = 110_850

#: 溯源审计常量：用户指定原始标准化文件的身份。v0.8.0 第三批起该文件本身
#: 即内置默认源，故 ORIGINAL_SOURCE_* 与 TRACKED_CSV_* 同值（保留本组常量
#: 仅为审计可读性与既有断言语义；新代码请直接使用 TRACKED_CSV_*）。
ORIGINAL_SOURCE_NAME = "微震局部三维点_3Sigma_去重均值_1911.csv"
ORIGINAL_SOURCE_SHA256 = TRACKED_CSV_SHA256
ORIGINAL_SOURCE_BYTES = TRACKED_CSV_BYTES


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



# ---------------------------------------------------------------------------
# Task 3：官方成果 seed（常规 Case→Dataset→Experiment→Run→Candidate→Selection 链）
# ---------------------------------------------------------------------------

import os  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import uuid  # noqa: E402

from sqlalchemy.exc import IntegrityError  # noqa: E402

from geomodeling.modeling.runner import execute_run  # noqa: E402
from geomodeling.platform import tables  # noqa: E402
from geomodeling.platform.ingest import standardize  # noqa: E402
from geomodeling.platform.repositories import (  # noqa: E402
    FormalSelectionRepository,
    featured_result_for_case,
)
from geomodeling.platform.results import materialize  # noqa: E402
from geomodeling.platform.schemas import (  # noqa: E402
    FeaturedResultLink,
    FieldMapping,
    FormalSelectionRequest,
)

_PRESET_NAMESPACE = uuid.UUID("c5f7a2e1-4b8d-4e6a-9f0c-1d2b3a4c5e6f")
# 进程内线程锁：并发 seed 串行化；跨进程由确定性主键唯一约束兜底。
_SEED_LOCK = threading.Lock()

SEED_SELECTED_BY = "preset-seed"
SEED_NOTE = (
    "官方普通克里金基线（v0.7.0 微震 CSV 预置）：候选矩阵空间验证与选择理由见 "
    "config/presets/microseismic-official-baseline.json；用户实验不得改写本选择。"
)


@dataclass(frozen=True)
class PresetSeedRecord:
    """seed 结果身份（只含逻辑 ID/链接/指纹，绝无本机路径）。"""

    case_id: str
    workspace_kind: str
    dataset_version_id: str
    experiment_id: str
    run_id: str
    official_result: FeaturedResultLink
    source_sha256: str
    baseline_sha256: str


def _preset_ids() -> dict[str, str]:
    return {
        "dataset": str(uuid.uuid5(_PRESET_NAMESPACE, f"{PRESET_VERSION}/dataset")),
        "experiment": str(uuid.uuid5(_PRESET_NAMESPACE, f"{PRESET_VERSION}/experiment")),
        "run": str(uuid.uuid5(_PRESET_NAMESPACE, f"{PRESET_VERSION}/run")),
    }


def load_and_verify_official_baseline(source: PresetSource) -> OfficialBaseline:
    baseline = load_official_baseline(DEFAULT_BASELINE_PATH)
    verify_official_baseline(source, baseline)
    return baseline


def _record_from_rows(runtime, source_sha256: str, baseline_sha256: str) -> PresetSeedRecord:
    ids = _preset_ids()
    with runtime.session() as session:
        featured = featured_result_for_case(session, PRESET_CASE_ID)
    if featured is None:
        raise PlatformError(
            PRESET_BASELINE_INVALID,
            "预置案例正式成果链不完整",
            {"reason": "partial_chain"},
            http_status=409,
        )
    return PresetSeedRecord(
        case_id=PRESET_CASE_ID,
        workspace_kind="builtin_preset",
        dataset_version_id=ids["dataset"],
        experiment_id=ids["experiment"],
        run_id=ids["run"],
        official_result=featured,
        source_sha256=source_sha256,
        baseline_sha256=baseline_sha256,
    )


def find_matching_preset_seed(
    runtime, source_sha256: str, baseline_sha256: str
) -> PresetSeedRecord | None:
    """已有同身份同指纹的完整 seed → 直接返回；指纹不同/链不完整 → fail-closed。"""

    with runtime.session() as session:
        case = session.get(tables.Case, PRESET_CASE_ID)
        if case is None:
            return None
        config = tables.loads_canonical(case.config_json or "{}")
    if config.get("workspace_kind") != "builtin_preset":
        raise PlatformError(
            PRESET_BASELINE_INVALID,
            "预置案例身份冲突：已存在同 ID 非预置案例",
            {"reason": "workspace_kind"},
            http_status=409,
        )
    if config.get("preset_version") != PRESET_VERSION:
        raise PlatformError(
            PRESET_BASELINE_INVALID,
            "预置版本不一致，绝不覆盖既有成果",
            {"reason": "preset_version"},
            http_status=409,
        )
    if (
        config.get("source_sha256") != source_sha256
        or config.get("baseline_sha256") != baseline_sha256
    ):
        raise PlatformError(
            PRESET_BASELINE_INVALID,
            "预置源/基线指纹不一致，绝不覆盖既有成果",
            {"reason": "fingerprint"},
            http_status=409,
        )
    return _record_from_rows(runtime, source_sha256, baseline_sha256)


def seed_microseismic_preset(runtime) -> PresetSeedRecord:
    """幂等 seed：同指纹完整链直接复用；否则经正常生命周期全链创建。"""

    with _SEED_LOCK:
        source = load_microseismic_preset(DEFAULT_PRESET_CSV)
        baseline = load_and_verify_official_baseline(source)
        existing = find_matching_preset_seed(runtime, source.sha256, baseline.sha256)
        if existing is not None:
            return existing
        return _create_preset_chain(runtime, source, baseline)


def _stage_source_csv(runtime, dataset_id: str, source: PresetSource) -> Path:
    """受控 CSV 原子复制进运行时（临时文件 + 回读校验 + os.replace）。"""

    target = runtime.settings.upload_source(PRESET_CASE_ID, dataset_id, "csv")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="preset-source-", suffix=".csv", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(DEFAULT_PRESET_CSV.read_bytes())
        if hashlib.sha256(Path(tmp_name).read_bytes()).hexdigest() != source.sha256:
            raise PlatformError(
                PRESET_SOURCE_INVALID,
                "预置源复制校验失败",
                {"reason": "copy_sha_mismatch"},
                http_status=409,
            )
        os.replace(tmp_name, target)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return target


def _create_preset_chain(runtime, source: PresetSource, baseline: OfficialBaseline):
    ids = _preset_ids()
    dataset_id = ids["dataset"]
    experiment_id = ids["experiment"]
    run_id = ids["run"]
    created_candidate_id: str | None = None

    try:
        source_path = _stage_source_csv(runtime, dataset_id, source)
        mapping = FieldMapping(
            dimension="3d",
            x="X_LOCAL_M",
            y="Y_LOCAL_M",
            z="Z_LOCAL_M",
            value="VX_KM_S",
            value_name="Vx",
            value_unit="km/s",
            coordinate_kind="local_linear",
        )
        summary = standardize(
            runtime.settings, PRESET_CASE_ID, dataset_id, source_path, "csv", mapping
        )

        config = {
            "workspace_kind": "builtin_preset",
            "preset_version": PRESET_VERSION,
            "read_only": True,
            "source_sha256": source.sha256,
            "baseline_sha256": baseline.sha256,
            "candidate_report_sha256": baseline.candidate_report_sha256,
        }
        profile = {
            "source_kind": "builtin_preset",
            "dimension": "3d",
            "mapping": {
                "dimension": "3d",
                "x": "X_LOCAL_M",
                "y": "Y_LOCAL_M",
                "z": "Z_LOCAL_M",
                "value": "VX_KM_S",
                "value_name": "Vx",
                "value_unit": "km/s",
                "coordinate_kind": "local_linear",
            },
            "row_count": summary["row_count"],
            "valid_row_count": summary["valid_row_count"],
            "invalid_row_count": summary["invalid_row_count"],
            "source_sha256": source.sha256,
            "standardized_sha256": summary["standardized_sha256"],
            "standardized_path": summary["standardized_path"],
            "quality": {"status": "passed", "confirmed": True},
        }
        experiment_params = {
            "algorithm": "ordinary_kriging",
            "dataset_version_id": dataset_id,
            "search_mode": "manual",
            "parameters": baseline.winner["parameters"],
            "validation": baseline.validation,
            "grid": baseline.grid,
        }
        try:
            with runtime.session() as session:
                session.add(
                    tables.Case(
                        id=PRESET_CASE_ID,
                        name="微震速度",
                        case_type="generic",
                        config_json=tables.dumps_canonical(config),
                    )
                )
                session.add(
                    tables.DatasetVersion(
                        id=dataset_id,
                        case_id=PRESET_CASE_ID,
                        version=1,
                        status="validated",
                        source_path=str(source_path),
                        standardized_path=summary["standardized_path"],
                        profile_json=tables.dumps_canonical(profile),
                    )
                )
                session.add(
                    tables.Experiment(
                        id=experiment_id,
                        case_id=PRESET_CASE_ID,
                        name="官方普通克里金基线",
                        params_json=tables.dumps_canonical(experiment_params),
                    )
                )
                session.add(tables.Run(id=run_id, experiment_id=experiment_id, status="queued"))
                session.commit()
        except IntegrityError:
            # 并发/重复 seed 已由其他进程创建同身份链：回读复用或 fail-closed
            existing = find_matching_preset_seed(runtime, source.sha256, baseline.sha256)
            if existing is not None:
                return existing
            raise

        outcome = execute_run(runtime, run_id, threading.Event())
        if outcome.status != "succeeded":
            raise PlatformError(
                PRESET_BASELINE_INVALID,
                "官方候选执行未成功",
                {"reason": "run_not_succeeded", "status": outcome.status},
                http_status=409,
            )
        with runtime.session() as session:
            candidates = (
                session.query(tables.CandidateResult)
                .filter(tables.CandidateResult.run_id == run_id)
                .all()
            )
        succeeded = [c for c in candidates if c.status == "succeeded"]
        if len(succeeded) != 1:
            raise PlatformError(
                PRESET_BASELINE_INVALID,
                "官方候选数量合同不一致",
                {"reason": "candidate_count", "count": len(succeeded)},
                http_status=409,
            )
        created_candidate_id = succeeded[0].id

        materialize(runtime, created_candidate_id)

        with runtime.session() as session:
            FormalSelectionRepository(session).select(
                PRESET_CASE_ID,
                FormalSelectionRequest(
                    candidate_result_id=created_candidate_id,
                    note=SEED_NOTE,
                    selected_by=SEED_SELECTED_BY,
                ),
            )
        return _record_from_rows(runtime, source.sha256, baseline.sha256)
    except BaseException:
        _compensate_seed(runtime, ids, created_candidate_id)
        raise


def _compensate_seed(runtime, ids: dict[str, str], candidate_id: str | None) -> None:
    """seed 失败补偿：删行 + 删工件目录；清理异常只记录，绝不覆盖原异常。"""

    import logging

    logger = logging.getLogger("geomodeling.platform")
    try:
        with runtime.session() as session:
            session.query(tables.FormalSelection).filter(
                tables.FormalSelection.case_id == PRESET_CASE_ID
            ).delete(synchronize_session=False)
            session.query(tables.CandidateResult).filter(
                tables.CandidateResult.run_id == ids["run"]
            ).delete(synchronize_session=False)
            for model, row_id in (
                (tables.Run, ids["run"]),
                (tables.Experiment, ids["experiment"]),
                (tables.DatasetVersion, ids["dataset"]),
                (tables.Case, PRESET_CASE_ID),
            ):
                row = session.get(model, row_id)
                if row is not None:
                    session.delete(row)
            session.commit()
    except Exception:  # noqa: BLE001 - 清理失败只记录
        logger.exception("预置 seed 补偿：数据库行清理失败")
    for path in (
        runtime.settings.datasets_dir / PRESET_CASE_ID,
        runtime.settings.uploads_dir / PRESET_CASE_ID,
        runtime.settings.experiments_dir / ids["experiment"],
        (runtime.settings.results_dir / candidate_id) if candidate_id else None,
    ):
        if path is None:
            continue
        try:
            shutil.rmtree(path, ignore_errors=True)
        except Exception:  # noqa: BLE001 - 清理失败只记录
            logger.exception("预置 seed 补偿：工件目录清理失败 %s", path)
