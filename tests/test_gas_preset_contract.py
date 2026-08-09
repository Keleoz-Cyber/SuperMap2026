"""v0.8.0 第三批 Task 3：瓦斯含量预置源合同测试。

瓦斯标准化 CSV 内置在仓库 ``example_data/瓦斯含量_合格样品.csv``（字节级
冻结合同见 tests/test_example_data_contract.py：CRLF+BOM、1,977 字节、
59 行、SHA-256 f7d6f03d…）。加载器 ``load_gas_preset`` fail-closed：
缺失文件、表头/行数不符、非数值/非有限、重复 XYZ 一律抛出
``PRESET_SOURCE_INVALID``（409），错误 details 绝不含本机路径。

已核验源事实（2026-08-09 实测，与 example_data 字节合同一致）：表头恰为
``X,Y,Z,CH4_content``、58 数据行、全部数值有限、``(X,Y,Z)`` 无重复、
28 个 XY 采样位置、Z∈[121.0375, 175.656]、CH4_content∈[0.05, 34.3]；
坐标为局部线性米制（local_linear，不做 EPSG 配准），CH4_content 单位
ml/g（用户权威确认，不做任何换算）。默认源只从项目内 ``example_data/``
解析，禁止从旧 ``docs/data/gas.md`` 的外部文件或旧 SHA 派生。
"""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePath

import numpy as np
import pandas as pd
import pytest

from geomodeling.platform.errors import PRESET_SOURCE_INVALID, PlatformError
from geomodeling.platform.gas_preset import (
    DEFAULT_PRESET_CSV,
    EXPECTED_ROW_COUNT,
    GAS_VALUE_UNIT,
    PRESET_CASE_ID,
    REQUIRED_COLUMNS,
    GasPresetSource,
    load_gas_preset,
)
from geomodeling.platform.settings import example_data_path

#: 冻结的瓦斯源字节指纹（tests/test_example_data_contract.py 同一事实源）
GAS_SOURCE_SHA256 = "f7d6f03d280dd0d6db45e5e6a09b47747cc4831669e4163a63b791f913a4f09d"


def _fixture_frame(rows: int = EXPECTED_ROW_COUNT) -> pd.DataFrame:
    """确定性合成散点：唯一 ``(X,Y,Z)``、全部有限，无随机源。"""
    index = np.arange(rows, dtype=np.int64)
    column = index // 4  # 每个 (X,Y) 采样位置至多 4 个深度节点
    level = index % 4
    return pd.DataFrame(
        {
            "X": 200.0 + column * 5.0,  # 每列 X 唯一 ⇒ (X,Y) 唯一
            "Y": 300.0 + (column % 7) * 2.5,
            "Z": 121.0 + level * 17.5,  # 列内逐层唯一
            "CH4_content": 0.05 + index * 0.5,
        }
    )


def write_gas_fixture(path: Path, rows: int = EXPECTED_ROW_COUNT) -> Path:
    """写出确定性合成源 CSV（表头恰为 ``X,Y,Z,CH4_content``）。"""
    _fixture_frame(rows).to_csv(path, index=False, encoding="utf-8")
    return path


def _write_frame(tmp_path: Path, frame: pd.DataFrame, name: str = "candidate.csv") -> Path:
    target = tmp_path / name
    frame.to_csv(target, index=False, encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# 内置默认源：冻结字节合同与已核验真值
# ---------------------------------------------------------------------------


def test_default_preset_csv_resolves_to_bundled_example_data():
    """默认源只解析到项目内 example_data/ 字节冻结内置源（无外部默认源）。"""

    assert DEFAULT_PRESET_CSV == example_data_path("瓦斯含量_合格样品.csv")
    assert DEFAULT_PRESET_CSV.parent.name == "example_data"
    assert "超图杯资料" not in str(DEFAULT_PRESET_CSV)


def test_bundled_gas_source_matches_frozen_contract():
    source = load_gas_preset(DEFAULT_PRESET_CSV)
    assert isinstance(source, GasPresetSource)
    assert source.row_count == 58
    assert source.columns == ("X", "Y", "Z", "CH4_content")
    assert source.sha256 == GAS_SOURCE_SHA256
    assert source.sha256 == hashlib.sha256(DEFAULT_PRESET_CSV.read_bytes()).hexdigest()
    frame = source.frame
    assert np.isfinite(frame.to_numpy(dtype="float64")).all()
    assert not frame.duplicated(["X", "Y", "Z"]).any()
    # 28 个 XY 采样位置；Z/CH4 范围为 2026-08-09 已核验真值
    assert frame[["X", "Y"]].drop_duplicates().shape[0] == 28
    assert float(frame["Z"].min()) == pytest.approx(121.0375)
    assert float(frame["Z"].max()) == pytest.approx(175.656)
    assert float(frame["CH4_content"].min()) == pytest.approx(0.05)
    assert float(frame["CH4_content"].max()) == pytest.approx(34.3)


def test_bundled_gas_source_has_utf8_bom_and_crlf_layout():
    """真实内置源为 CRLF + UTF-8 BOM 形态（加载器按 utf-8-sig 读入）。"""

    raw = DEFAULT_PRESET_CSV.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert raw.count(b"\n") == raw.count(b"\r\n") == 59  # 表头 + 58 数据行
    # 带 BOM 的同内容字节加载后表头仍恰为合同列（BOM 不混入首列名）
    source = load_gas_preset(DEFAULT_PRESET_CSV)
    assert source.columns == REQUIRED_COLUMNS
    assert "X" in source.frame.columns


def test_gas_source_identity_and_units():
    source = load_gas_preset(DEFAULT_PRESET_CSV)
    assert PRESET_CASE_ID == "gas"
    assert REQUIRED_COLUMNS == ("X", "Y", "Z", "CH4_content")
    assert EXPECTED_ROW_COUNT == 58
    assert GAS_VALUE_UNIT == "ml/g"
    # 局部线性米制坐标，未声明 EPSG
    assert source.coordinate_kind == "local_linear"
    assert source.coordinate_unit == "m"
    # CH4_content 单位 ml/g（用户权威确认，绝不静默换算）
    assert source.value_unit == "ml/g"
    assert list(source.frame.columns) == list(REQUIRED_COLUMNS)
    assert all(source.frame[column].dtype == np.float64 for column in REQUIRED_COLUMNS)


# ---------------------------------------------------------------------------
# fail-closed 拒绝分支（合成夹具）
# ---------------------------------------------------------------------------


def test_load_rejects_missing_file(tmp_path: Path):
    with pytest.raises(PlatformError) as excinfo:
        load_gas_preset(tmp_path / "missing.csv")
    assert excinfo.value.code == PRESET_SOURCE_INVALID
    assert excinfo.value.http_status == 409


def test_load_rejects_wrong_header(tmp_path: Path):
    frame = _fixture_frame().rename(columns={"CH4_content": "CH4"})
    with pytest.raises(PlatformError) as excinfo:
        load_gas_preset(_write_frame(tmp_path, frame))
    assert excinfo.value.code == PRESET_SOURCE_INVALID
    assert excinfo.value.http_status == 409


def test_load_rejects_extra_column_header(tmp_path: Path):
    frame = _fixture_frame().assign(SAMPLE_ID=1)
    with pytest.raises(PlatformError) as excinfo:
        load_gas_preset(_write_frame(tmp_path, frame))
    assert excinfo.value.code == PRESET_SOURCE_INVALID


def test_load_rejects_wrong_row_count(tmp_path: Path):
    path = write_gas_fixture(tmp_path / "short.csv", rows=57)
    with pytest.raises(PlatformError) as excinfo:
        load_gas_preset(path)
    assert excinfo.value.code == PRESET_SOURCE_INVALID
    assert excinfo.value.details["expected_rows"] == 58
    assert excinfo.value.details["actual_rows"] == 57


def test_load_rejects_nonfinite_values(tmp_path: Path):
    frame = _fixture_frame()
    frame.loc[0, "CH4_content"] = float("nan")
    with pytest.raises(PlatformError) as excinfo:
        load_gas_preset(_write_frame(tmp_path, frame))
    assert excinfo.value.code == PRESET_SOURCE_INVALID


def test_load_rejects_nonnumeric_values(tmp_path: Path):
    frame = _fixture_frame()
    frame["X"] = frame["X"].astype(object)
    frame.loc[1, "X"] = "not-a-number"
    with pytest.raises(PlatformError) as excinfo:
        load_gas_preset(_write_frame(tmp_path, frame))
    assert excinfo.value.code == PRESET_SOURCE_INVALID


def test_load_rejects_duplicate_xyz(tmp_path: Path):
    frame = _fixture_frame()
    frame.loc[1, ["X", "Y", "Z"]] = frame.loc[0, ["X", "Y", "Z"]]
    with pytest.raises(PlatformError) as excinfo:
        load_gas_preset(_write_frame(tmp_path, frame))
    assert excinfo.value.code == PRESET_SOURCE_INVALID


def test_load_accepts_bom_prefixed_fixture(tmp_path: Path):
    """带 UTF-8 BOM 的同合同夹具正常加载（BOM 不混入首列名）。"""

    target = tmp_path / "bom.csv"
    _fixture_frame().to_csv(target, index=False, encoding="utf-8-sig")
    assert target.read_bytes().startswith(b"\xef\xbb\xbf")
    source = load_gas_preset(target)
    assert source.columns == REQUIRED_COLUMNS
    assert source.row_count == 58


def test_error_details_never_leak_source_path(tmp_path: Path):
    """合同错误的 details 不含 Path 对象或本机绝对路径文本。"""
    attempts = [
        tmp_path / "missing.csv",
        write_gas_fixture(tmp_path / "short.csv", rows=57),
        _write_frame(tmp_path, _fixture_frame().rename(columns={"CH4_content": "CH4"}), "header.csv"),
    ]

    def _walk(value: object) -> None:
        if isinstance(value, PurePath):
            pytest.fail("details 不得包含 Path 对象")
        if isinstance(value, str):
            assert str(tmp_path) not in value
            assert ":\\" not in value
        elif isinstance(value, dict):
            for item in value.values():
                _walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                _walk(item)

    for candidate in attempts:
        with pytest.raises(PlatformError) as excinfo:
            load_gas_preset(candidate)
        assert excinfo.value.code == PRESET_SOURCE_INVALID
        _walk(excinfo.value.details)
