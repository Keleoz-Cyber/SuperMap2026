"""v0.8.0 第三批 Task 1：内置 ``example_data/`` 数据源字节合同测试。

三个官方案例的规范化源 CSV 随仓库内置，字节级冻结：SHA-256、字节数、
行数（纯 CRLF，微震/瓦斯含 UTF-8 BOM，电阻率无 BOM）、表头、有限数值与
唯一 XYZ 必须与 2026-08-09 已核验真值精确一致。``.gitattributes`` 对
``example_data/*.csv`` 关闭文本归一化（``-text``），保证任何平台检出后
磁盘字节不变，冻结 SHA 不失真。

默认解析器 ``example_data_path`` 只解析 ``PROJECT_ROOT / "example_data"``
内的纯文件名，拒绝路径穿越与缺失文件；绝不解析出仓库外部（旧
``../超图杯资料`` 等相邻/绝对默认源），解析后的绝对路径也不写入任何
API DTO（浏览器只接收逻辑来源与内容哈希）。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePath

import numpy as np
import pandas as pd
import pytest

from geomodeling.platform.errors import PRESET_SOURCE_INVALID, PlatformError
from geomodeling.platform.settings import PROJECT_ROOT, example_data_path


@dataclass(frozen=True)
class ExampleDataContract:
    filename: str
    sha256: str
    byte_size: int
    line_count: int  # 含表头；纯 CRLF，文件以 CRLF 结尾
    has_bom: bool
    columns: tuple[str, ...]
    data_rows: int


RESISTIVITY = ExampleDataContract(
    filename="地下电阻率节点_标准化.csv",
    sha256="04c5914d992f397f7dcec3b0d1a6069a9ddeb4a214e5c7de121f37c861cec167",
    byte_size=541_941,
    line_count=17_550,
    has_bom=False,
    columns=("X", "Y", "Z", "RHO"),
    data_rows=17_549,
)
MICROSEISMIC = ExampleDataContract(
    filename="微震局部三维点_3Sigma_去重均值_1911.csv",
    sha256="4011de85e1fa7e49999fc5ae66a73e00a59dbec372a417ae0728d0a338c7765e",
    byte_size=110_850,
    line_count=1_912,
    has_bom=True,
    columns=(
        "SAMPLE_IDS",
        "POINT_ID",
        "LINE_ID",
        "X_LOCAL_M",
        "Y_LOCAL_M",
        "DEPTH_M",
        "Z_LOCAL_M",
        "VX_KM_S",
        "N_MERGED",
    ),
    data_rows=1_911,
)
GAS = ExampleDataContract(
    filename="瓦斯含量_合格样品.csv",
    sha256="f7d6f03d280dd0d6db45e5e6a09b47747cc4831669e4163a63b791f913a4f09d",
    byte_size=1_977,
    line_count=59,
    has_bom=True,
    columns=("X", "Y", "Z", "CH4_content"),
    data_rows=58,
)
CONTRACTS = (RESISTIVITY, MICROSEISMIC, GAS)

EXAMPLE_DATA_ROOT = PROJECT_ROOT / "example_data"


def _raw(contract: ExampleDataContract) -> bytes:
    return (EXAMPLE_DATA_ROOT / contract.filename).read_bytes()


def _frame(contract: ExampleDataContract) -> pd.DataFrame:
    return pd.read_csv(EXAMPLE_DATA_ROOT / contract.filename)


def test_example_data_files_exist_at_project_root_relative_paths():
    """三个源文件以项目根相对路径 ``example_data/<filename>`` 存在。"""
    for contract in CONTRACTS:
        path = EXAMPLE_DATA_ROOT / contract.filename
        assert path.is_file(), f"缺少内置源文件：example_data/{contract.filename}"
        # 解析器返回的同一路径，且是已跟踪的仓库内文件
        assert example_data_path(contract.filename) == path


def test_example_data_bytes_match_frozen_sha256_and_crlf_layout():
    """磁盘字节精确匹配冻结指纹；纯 CRLF、以 CRLF 结尾、BOM 形态固定。"""
    for contract in CONTRACTS:
        raw = _raw(contract)
        assert len(raw) == contract.byte_size
        assert hashlib.sha256(raw).hexdigest() == contract.sha256
        # 每个 LF 都属于 CRLF（无 lone LF），行数含表头，文件以 CRLF 结尾
        assert raw.count(b"\n") == raw.count(b"\r\n") == contract.line_count
        assert raw.endswith(b"\r\n")
        assert raw.startswith(b"\xef\xbb\xbf") is contract.has_bom


def test_example_data_headers_match_frozen_columns():
    for contract in CONTRACTS:
        first_line = _raw(contract).split(b"\r\n", 1)[0]
        if contract.has_bom:
            assert first_line.startswith(b"\xef\xbb\xbf")
            first_line = first_line[3:]
        assert first_line.decode("utf-8") == ",".join(contract.columns)


def test_resistivity_csv_matches_frozen_numeric_contract():
    frame = _frame(RESISTIVITY)
    assert tuple(frame.columns) == RESISTIVITY.columns
    assert len(frame) == RESISTIVITY.data_rows == 17_549
    values = frame.to_numpy(dtype="float64")
    assert np.isfinite(values).all()
    assert not frame.duplicated(["X", "Y", "Z"]).any()


def test_microseismic_csv_matches_frozen_numeric_contract():
    frame = _frame(MICROSEISMIC)
    assert tuple(frame.columns) == MICROSEISMIC.columns
    assert len(frame) == MICROSEISMIC.data_rows == 1_911
    numeric = ["X_LOCAL_M", "Y_LOCAL_M", "DEPTH_M", "Z_LOCAL_M", "VX_KM_S", "N_MERGED"]
    assert np.isfinite(frame[numeric].to_numpy(dtype="float64")).all()
    assert not frame.duplicated(["X_LOCAL_M", "Y_LOCAL_M", "Z_LOCAL_M"]).any()
    # 溯源列非空（字符列，不参与数值建模）
    assert frame[["SAMPLE_IDS", "POINT_ID", "LINE_ID"]].notna().all().all()


def test_gas_csv_matches_frozen_numeric_contract():
    frame = _frame(GAS)
    assert tuple(frame.columns) == GAS.columns
    assert len(frame) == GAS.data_rows == 58
    assert np.isfinite(frame.to_numpy(dtype="float64")).all()
    assert not frame.duplicated(["X", "Y", "Z"]).any()
    # 28 个 XY 采样位置；Z/CH4 范围为已核验真值
    assert frame[["X", "Y"]].drop_duplicates().shape[0] == 28
    assert float(frame["Z"].min()) == pytest.approx(121.0375)
    assert float(frame["Z"].max()) == pytest.approx(175.656)
    assert float(frame["CH4_content"].min()) == pytest.approx(0.05)
    assert float(frame["CH4_content"].max()) == pytest.approx(34.3)


def test_example_data_path_resolves_only_inside_bundled_dir():
    """默认解析器只解析仓库内 example_data/，不解析出外部绝对/相邻默认源。"""
    for contract in CONTRACTS:
        resolved = example_data_path(contract.filename)
        assert resolved.is_absolute()
        assert resolved.parent == EXAMPLE_DATA_ROOT
        assert resolved.is_relative_to(PROJECT_ROOT)
        # 旧外部相邻默认源（../超图杯资料 等）不再是解析目标
        assert "超图杯资料" not in str(resolved)
        assert ".." not in resolved.relative_to(PROJECT_ROOT).parts


@pytest.mark.parametrize(
    "filename",
    ["", ".", "..", "../secret.csv", "..\\secret.csv", "sub/dir.csv", "sub\\dir.csv", "/abs.csv", "C:\\x.csv"],
)
def test_example_data_path_rejects_traversal_and_separators(filename: str):
    with pytest.raises(PlatformError) as excinfo:
        example_data_path(filename)
    assert excinfo.value.code == PRESET_SOURCE_INVALID


def test_example_data_path_rejects_missing_file_with_typed_error():
    with pytest.raises(PlatformError) as excinfo:
        example_data_path("不存在的文件.csv")
    assert excinfo.value.code == PRESET_SOURCE_INVALID
    assert excinfo.value.http_status == 409


def test_error_details_never_leak_absolute_paths():
    """类型化错误的 details 不含 Path 对象或本机绝对路径文本。"""

    def _walk(value: object) -> None:
        if isinstance(value, PurePath):
            pytest.fail("details 不得包含 Path 对象")
        if isinstance(value, str):
            assert str(PROJECT_ROOT) not in value
            assert ":\\" not in value
        elif isinstance(value, dict):
            for item in value.values():
                _walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                _walk(item)

    for bad in ("../secret.csv", "不存在的文件.csv"):
        with pytest.raises(PlatformError) as excinfo:
            example_data_path(bad)
        assert excinfo.value.code == PRESET_SOURCE_INVALID
        _walk(excinfo.value.details)


def test_resolver_returns_plain_repo_file_not_external_source(tmp_path: Path):
    """解析结果不依赖环境变量或外部目录：同名外部文件不参与解析。"""
    outside = tmp_path / GAS.filename
    outside.write_bytes(b"X,Y,Z,CH4_content\r\n1,2,3,4\r\n")
    resolved = example_data_path(GAS.filename)
    assert resolved != outside
    assert resolved.read_bytes() != outside.read_bytes()
    assert resolved.is_relative_to(EXAMPLE_DATA_ROOT)
