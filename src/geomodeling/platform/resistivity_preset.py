"""v0.8.0 Task 1：电阻率散点预置源合同。

电阻率标准化 CSV 是项目外部的私有文件（逻辑身份
``地下电阻率节点_标准化.csv``），绝不提交 Git、绝不在受控文件中出现
本机绝对路径；运行时仅登记其 SHA-256 指纹。已核验源事实：表头恰好
``X,Y,Z,RHO``、17,549 行、全部数值有限、``(X,Y,Z)`` 无重复、局部工程
坐标（未声明 EPSG）；RHO 单位待来源确认（不静默声明单位、不做换算）。

加载器 fail-closed：缺失文件、表头/行数不符、非数值/非有限、重复 XYZ
一律抛出 ``PRESET_SOURCE_INVALID``（409）。本模块绝不向公共层返回本机
源路径（错误 details 不含 Path 对象或绝对路径文本）。
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
