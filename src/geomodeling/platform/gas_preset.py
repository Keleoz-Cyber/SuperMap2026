"""v0.8.0 第三批瓦斯含量预置：源合同加载器（Task 3）。

瓦斯标准化 CSV 内置在仓库 ``example_data/瓦斯含量_合格样品.csv``（字节级
冻结合同见 tests/test_example_data_contract.py：CRLF+UTF-8 BOM、1,977
字节、59 行、SHA-256 f7d6f03d…），运行时仅登记其 SHA-256 指纹，绝不在
受控文件中出现本机绝对路径。已核验源事实（2026-08-09 实测）：表头恰好
``X,Y,Z,CH4_content``、58 数据行、全部数值有限、``(X,Y,Z)`` 无重复、
28 个 XY 采样位置、Z∈[121.0375, 175.656]、CH4_content∈[0.05, 34.3]；
坐标为局部线性米制（``local_linear``，米制，不做 EPSG 配准）；
CH4_content 单位为 ml/g（用户权威确认，不做任何换算）。

加载器 fail-closed：缺失文件、表头/行数不符、非数值/非有限、重复 XYZ
一律抛出 ``PRESET_SOURCE_INVALID``（409）。本模块绝不向公共层返回本机
源路径（错误 details 不含 Path 对象或绝对路径文本）。默认源只从项目内
``example_data/`` 解析，禁止从旧 ``docs/data/gas.md`` 的外部文件或旧
SHA 派生默认数据。

Task 3 只实现源合同加载器与身份常量；seed 生命周期（Task 4）、官方候选
与基线冻结（Task 5）、网格与 NetCDF 资产（Task 6）在后续任务接入，本
模块不预置任何未冻结数值。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from geomodeling.platform.errors import PRESET_SOURCE_INVALID, PlatformError
from geomodeling.platform.settings import example_data_path

PRESET_CASE_ID = "gas"

#: 内置默认源（v0.8.0 第三批：项目内 example_data/ 字节冻结合同；
#: 解析器拒绝目录穿越，缺失即 PRESET_SOURCE_INVALID）
DEFAULT_PRESET_CSV = example_data_path("瓦斯含量_合格样品.csv")

#: 标准化散点表头合同（恰好 4 列，顺序固定）
REQUIRED_COLUMNS = ("X", "Y", "Z", "CH4_content")

EXPECTED_ROW_COUNT = 58

#: CH4_content 单位 ml/g（用户权威确认，绝不静默换算）
GAS_VALUE_UNIT = "ml/g"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class GasPresetSource:
    """已验证的瓦斯预置源：建模框架 + 摘要指纹（无本机路径）。"""

    frame: pd.DataFrame
    sha256: str
    row_count: int
    columns: tuple[str, ...]
    coordinate_kind: str = "local_linear"
    # 局部线性米制坐标（未声明 EPSG，不做跨案例空间叠加）
    coordinate_unit: str = "m"
    # CH4_content 单位 ml/g（用户权威确认，绝不静默换算）
    value_unit: str = GAS_VALUE_UNIT


def load_gas_preset(path: Path) -> GasPresetSource:
    """加载并验证瓦斯含量散点预置 CSV；任何合同违反 fail-closed。"""

    if not path.is_file():
        raise PlatformError(
            PRESET_SOURCE_INVALID,
            "瓦斯预置 CSV 不存在或不可读",
            {"reason": "missing_file"},
            http_status=409,
        )
    try:
        raw = pd.read_csv(path, encoding="utf-8-sig")
    except Exception as exc:  # noqa: BLE001 - 统一翻译为稳定合同错误
        raise PlatformError(
            PRESET_SOURCE_INVALID,
            "瓦斯预置 CSV 解析失败",
            {"reason": type(exc).__name__},
            http_status=409,
        ) from exc
    if tuple(raw.columns) != REQUIRED_COLUMNS:
        raise PlatformError(
            PRESET_SOURCE_INVALID,
            "瓦斯预置 CSV 表头合同不匹配",
            {"expected_columns": list(REQUIRED_COLUMNS)},
            http_status=409,
        )
    if len(raw) != EXPECTED_ROW_COUNT:
        raise PlatformError(
            PRESET_SOURCE_INVALID,
            "瓦斯预置 CSV 行数合同不匹配",
            {"expected_rows": EXPECTED_ROW_COUNT, "actual_rows": len(raw)},
            http_status=409,
        )
    numeric = raw.apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric.to_numpy(dtype="float64")).all():
        raise PlatformError(
            PRESET_SOURCE_INVALID,
            "瓦斯预置 CSV 含非数值或非有限值",
            {"columns": list(REQUIRED_COLUMNS)},
            http_status=409,
        )
    if numeric.iloc[:, :3].duplicated().any():
        raise PlatformError(
            PRESET_SOURCE_INVALID,
            "瓦斯预置 CSV 含重复 XYZ 坐标",
            {"columns": list(REQUIRED_COLUMNS[:3])},
            http_status=409,
        )
    return GasPresetSource(
        frame=numeric.astype("float64"),
        sha256=_sha256(path),
        row_count=len(numeric),
        columns=REQUIRED_COLUMNS,
    )
