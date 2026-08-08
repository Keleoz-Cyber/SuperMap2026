"""v0.8.0 电阻率散点预置：源合同（Task 1）+ 只读 seed 链（Task 2）。

电阻率标准化 CSV 是项目外部的私有文件（逻辑身份
``地下电阻率节点_标准化.csv``），绝不提交 Git、绝不在受控文件中出现
本机绝对路径；运行时仅登记其 SHA-256 指纹。已核验源事实：表头恰好
``X,Y,Z,RHO``、17,549 行、全部数值有限、``(X,Y,Z)`` 无重复、局部工程
坐标（未声明 EPSG）；RHO 单位待来源确认（不静默声明单位、不做换算）。

加载器 fail-closed：缺失文件、表头/行数不符、非数值/非有限、重复 XYZ
一律抛出 ``PRESET_SOURCE_INVALID``（409）。本模块绝不向公共层返回本机
源路径（错误 details 不含 Path 对象或绝对路径文本）。

Task 2：``seed_resistivity_preset`` 经正常生命周期把外部源 seed 为只读
``builtin_preset`` 案例链（Case→DatasetVersion→Experiment→Run→
CandidateResult→materialize→FormalSelection），结构与纪律同微震预置
（确定性 uuid5 主键、线程锁 + 唯一约束幂等、失败补偿删行删目录）。
官方基线 JSON 由 Task 5 冻结真实数值；本模块只定义合同并 fail-closed
验证，缺失/不符一律 ``PRESET_BASELINE_INVALID``，绝不覆盖既有成果。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from geomodeling.platform.errors import PRESET_SOURCE_INVALID, PlatformError

PRESET_CASE_ID = "resistivity"

#: 标准化散点表头合同（恰好 4 列，顺序固定）
REQUIRED_COLUMNS = ("X", "Y", "Z", "RHO")

EXPECTED_ROW_COUNT = 17_549


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class ResistivityPresetSource:
    """已验证的电阻率预置源：建模框架 + 摘要指纹（无本机路径）。"""

    frame: pd.DataFrame
    sha256: str
    row_count: int
    columns: tuple[str, ...]
    coordinate_kind: str = "local_linear"
    # RHO 单位待来源确认：保持 None，不静默声明单位
    value_unit: str | None = None


def load_resistivity_preset(path: Path) -> ResistivityPresetSource:
    """加载并验证电阻率散点预置 CSV；任何合同违反 fail-closed。"""

    if not path.is_file():
        raise PlatformError(
            PRESET_SOURCE_INVALID,
            "电阻率预置 CSV 不存在或不可读",
            {"reason": "missing_file"},
            http_status=409,
        )
    try:
        raw = pd.read_csv(path, encoding="utf-8-sig")
    except Exception as exc:  # noqa: BLE001 - 统一翻译为稳定合同错误
        raise PlatformError(
            PRESET_SOURCE_INVALID,
            "电阻率预置 CSV 解析失败",
            {"reason": type(exc).__name__},
            http_status=409,
        ) from exc
    if tuple(raw.columns) != REQUIRED_COLUMNS:
        raise PlatformError(
            PRESET_SOURCE_INVALID,
            "电阻率预置 CSV 表头合同不匹配",
            {"expected_columns": list(REQUIRED_COLUMNS)},
            http_status=409,
        )
    if len(raw) != EXPECTED_ROW_COUNT:
        raise PlatformError(
            PRESET_SOURCE_INVALID,
            "电阻率预置 CSV 行数合同不匹配",
            {"expected_rows": EXPECTED_ROW_COUNT, "actual_rows": len(raw)},
            http_status=409,
        )
    numeric = raw.apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric.to_numpy(dtype="float64")).all():
        raise PlatformError(
            PRESET_SOURCE_INVALID,
            "电阻率预置 CSV 含非数值或非有限值",
            {"columns": list(REQUIRED_COLUMNS)},
            http_status=409,
        )
    if numeric.iloc[:, :3].duplicated().any():
        raise PlatformError(
            PRESET_SOURCE_INVALID,
            "电阻率预置 CSV 含重复 XYZ 坐标",
            {"columns": list(REQUIRED_COLUMNS[:3])},
            http_status=409,
        )
    return ResistivityPresetSource(
        frame=numeric.astype("float64"),
        sha256=_sha256(path),
        row_count=len(numeric),
        columns=REQUIRED_COLUMNS,
    )


# ---------------------------------------------------------------------------
# Task 2：官方基线合同（真实数值由 Task 5 评审冻结，本模块只验证不生成）
# ---------------------------------------------------------------------------

import json  # noqa: E402
from typing import Any  # noqa: E402

from geomodeling.platform.errors import PRESET_BASELINE_INVALID  # noqa: E402

PRESET_VERSION = "resistivity-rho-17549/v1"

#: 官方 winner 参数的允许矩阵（与微震同一固定纪律；Task 5 候选分析不得越界）
VARIOGRAM_MODELS = ("spherical", "exponential", "gaussian")
NEIGHBOR_COUNTS = (12, 24, 36)
Z_SCALES = (0.5, 1.0, 2.0)

#: 固定空间 5 折交叉验证合同（种子钉死，基线/报告均记录）
VALIDATION_CONTRACT = {"method": "spatial_kfold", "folds": 5, "seed": 20260723}

GRID_MAX_CELLS = 1_000_000

BASELINE_SCHEMA = "v0.8.0-resistivity-official-baseline/v1"
DEFAULT_BASELINE_PATH = Path("config/presets/resistivity-official-baseline.json")

SELECTION_RULE = ("rmse_asc", "mae_asc", "r2_desc", "canonical_params_asc")


def preset_candidate_matrix() -> list[dict[str, Any]]:
    """固定 27 成员普通克里金允许矩阵（确定性顺序；不得扩展为插件式搜索空间）。"""

    return [
        {"variogram_model": model, "neighbor_count": neighbors, "z_scale": z_scale}
        for model in VARIOGRAM_MODELS
        for neighbors in NEIGHBOR_COUNTS
        for z_scale in Z_SCALES
    ]


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


def verify_official_baseline(source: ResistivityPresetSource, baseline: OfficialBaseline) -> None:
    """验证基线与受控源的身份链；任何不匹配 fail-closed。"""

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


# ---------------------------------------------------------------------------
# Task 2：官方成果 seed（常规 Case→Dataset→Experiment→Run→Candidate→Selection 链）
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

_PRESET_NAMESPACE = uuid.UUID("8d2f6b4a-1c7e-4a5d-b3f9-6e0d2a8c5f17")
# 进程内线程锁：并发 seed 串行化；跨进程由确定性主键唯一约束兜底。
_SEED_LOCK = threading.Lock()

SEED_SELECTED_BY = "preset-seed"
SEED_NOTE = (
    "官方普通克里金基线（v0.8.0 电阻率散点预置）：候选矩阵空间验证与选择理由见 "
    "config/presets/resistivity-official-baseline.json；用户实验不得改写本选择。"
)

#: RHO 单位待来源确认：诚实表述，绝不写 Ω·m 等未确认单位
VALUE_UNIT_NOTE = "RHO 单位待来源确认"
#: 工作台 provenance 键（seed 写入 Case config_json，legacy_adapter 读取）
DATA_FORM = "三维 X/Y/Z/RHO（局部工程坐标）"
PRESET_BADGE = "散点预置 · 官方普通克里金成果"


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


def seed_resistivity_preset(
    runtime,
    source_path: Path,
    *,
    baseline_path: Path | None = None,
    baseline: OfficialBaseline | None = None,
) -> PresetSeedRecord:
    """幂等 seed：同指纹完整链直接复用；否则经正常生命周期全链创建。

    ``source_path`` 是外部私有源 CSV（必填，无仓库默认）。基线可注入：
    ``baseline`` 对象优先，其次 ``baseline_path``，均未给出时读
    ``DEFAULT_BASELINE_PATH``（Task 5 前不存在，缺失即 fail-closed）。
    无论注入方式，``verify_official_baseline`` 都强制执行。
    """

    with _SEED_LOCK:
        source = load_resistivity_preset(source_path)
        if baseline is None:
            baseline = load_official_baseline(baseline_path or DEFAULT_BASELINE_PATH)
        verify_official_baseline(source, baseline)
        existing = find_matching_preset_seed(runtime, source.sha256, baseline.sha256)
        if existing is not None:
            return existing
        return _create_preset_chain(runtime, source, baseline, source_path)


def _stage_source_csv(
    runtime, dataset_id: str, source: ResistivityPresetSource, source_path: Path
) -> Path:
    """外部源 CSV 原子复制进运行时（临时文件 + 回读校验 + os.replace）。"""

    target = runtime.settings.upload_source(PRESET_CASE_ID, dataset_id, "csv")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="preset-source-", suffix=".csv", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(source_path.read_bytes())
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


def _create_preset_chain(
    runtime,
    source: ResistivityPresetSource,
    baseline: OfficialBaseline,
    source_path: Path,
):
    ids = _preset_ids()
    dataset_id = ids["dataset"]
    experiment_id = ids["experiment"]
    run_id = ids["run"]
    created_candidate_id: str | None = None

    try:
        staged_path = _stage_source_csv(runtime, dataset_id, source, source_path)
        mapping = FieldMapping(
            dimension="3d",
            x="X",
            y="Y",
            z="Z",
            value="RHO",
            value_name="RHO",
            value_unit=VALUE_UNIT_NOTE,
            coordinate_kind="local_linear",
        )
        summary = standardize(
            runtime.settings, PRESET_CASE_ID, dataset_id, staged_path, "csv", mapping
        )

        config = {
            "workspace_kind": "builtin_preset",
            "preset_version": PRESET_VERSION,
            "read_only": True,
            "source_sha256": source.sha256,
            "baseline_sha256": baseline.sha256,
            "candidate_report_sha256": baseline.candidate_report_sha256,
            # 工作台 provenance（legacy_adapter 读取；微震卡走既有常量兜底）
            "data_form": DATA_FORM,
            "value_unit": VALUE_UNIT_NOTE,
            "coordinate_kind": "local_linear",
            "badge": PRESET_BADGE,
        }
        profile = {
            "source_kind": "builtin_preset",
            "dimension": "3d",
            "mapping": {
                "dimension": "3d",
                "x": "X",
                "y": "Y",
                "z": "Z",
                "value": "RHO",
                "value_name": "RHO",
                "value_unit": VALUE_UNIT_NOTE,
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
                        name="地下电阻率",
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
                        source_path=str(staged_path),
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
