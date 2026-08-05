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
