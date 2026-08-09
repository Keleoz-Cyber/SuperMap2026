"""v0.8.0 Task 1：电阻率散点预置源合同测试。

电阻率标准化 CSV 内置在仓库 ``example_data/地下电阻率节点_标准化.csv``
（v0.8.0 第三批起默认源；字节级冻结合同见 tests/test_example_data_contract.py），
运行时只登记其 SHA-256 指纹，绝不在受控文件中出现本机绝对路径。便携测试
使用确定性合成夹具（``write_resistivity_fixture``：表头恰为 ``X,Y,Z,RHO``、
唯一 ``(X,Y,Z)``、全部有限、无随机源）；真实 17,549 行源核验标记
``local_data``，仅从 ``GEOMODELING_RHO_SOURCE`` 环境变量取路径，未设置
即跳过。
"""

from __future__ import annotations

import hashlib
import inspect
import os
from pathlib import Path, PurePath

import numpy as np
import pandas as pd
import pytest

from geomodeling.platform.errors import PRESET_SOURCE_INVALID, PlatformError
from geomodeling.platform.resistivity_preset import (
    DEFAULT_PRESET_CSV,
    EXPECTED_ROW_COUNT,
    PRESET_CASE_ID,
    REQUIRED_COLUMNS,
    ResistivityPresetSource,
    load_resistivity_preset,
    seed_resistivity_preset,
)
from geomodeling.platform.settings import example_data_path

RHO_SOURCE_ENV = "GEOMODELING_RHO_SOURCE"


def _fixture_frame(rows: int = EXPECTED_ROW_COUNT) -> pd.DataFrame:
    """确定性合成散点：唯一 ``(X,Y,Z)``、全部有限，无随机源。"""
    index = np.arange(rows, dtype=np.int64)
    column = index // 60  # 每个 (X,Y) 空间柱至多 60 个节点
    level = index % 60
    return pd.DataFrame(
        {
            "X": column * 10.0,  # 每柱 X 唯一 ⇒ (X,Y) 唯一
            "Y": (column % 13) * 2.5,
            "Z": -(level * 17.5),  # 柱内逐层唯一
            "RHO": 1.032113 + index * 0.008,
        }
    )


def write_resistivity_fixture(path: Path, rows: int = EXPECTED_ROW_COUNT) -> Path:
    """写出确定性合成源 CSV（表头恰为 ``X,Y,Z,RHO``）。"""
    _fixture_frame(rows).to_csv(path, index=False, encoding="utf-8")
    return path


def _write_frame(tmp_path: Path, frame: pd.DataFrame, name: str = "candidate.csv") -> Path:
    target = tmp_path / name
    frame.to_csv(target, index=False, encoding="utf-8")
    return target


def test_resistivity_source_contract_has_17549_finite_unique_rows(tmp_path: Path):
    path = write_resistivity_fixture(tmp_path / "rho.csv", rows=17_549)
    source = load_resistivity_preset(path)
    assert source.row_count == 17_549
    assert source.columns == ("X", "Y", "Z", "RHO")
    assert source.frame[["X", "Y", "Z", "RHO"]].isna().sum().sum() == 0
    assert source.frame.duplicated(["X", "Y", "Z"]).sum() == 0


def test_resistivity_source_identity_and_fingerprint(tmp_path: Path):
    path = write_resistivity_fixture(tmp_path / "rho.csv")
    source = load_resistivity_preset(path)
    assert isinstance(source, ResistivityPresetSource)
    assert PRESET_CASE_ID == "resistivity"
    assert REQUIRED_COLUMNS == ("X", "Y", "Z", "RHO")
    assert EXPECTED_ROW_COUNT == 17_549
    # 局部工程坐标，未声明 EPSG
    assert source.coordinate_kind == "local_linear"
    # RHO 单位已确认为 Ω·m（v0.8.0 第三批用户权威确认）
    assert source.value_unit == "Ω·m"
    # 只暴露摘要指纹，绝不暴露本机源路径
    assert source.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert list(source.frame.columns) == list(REQUIRED_COLUMNS)
    assert all(source.frame[column].dtype == np.float64 for column in REQUIRED_COLUMNS)


def test_load_rejects_missing_file(tmp_path: Path):
    with pytest.raises(PlatformError) as excinfo:
        load_resistivity_preset(tmp_path / "missing.csv")
    assert excinfo.value.code == PRESET_SOURCE_INVALID
    assert excinfo.value.http_status == 409


def test_default_preset_csv_resolves_to_bundled_example_data():
    """v0.8.0 第三批：默认源只解析到项目内 example_data/ 字节冻结内置源。"""

    assert DEFAULT_PRESET_CSV == example_data_path("地下电阻率节点_标准化.csv")
    assert DEFAULT_PRESET_CSV.parent.name == "example_data"
    # 内置源身份与基线冻结合同一致（04c5914d…，见基线 JSON source_sha256）
    source = load_resistivity_preset(DEFAULT_PRESET_CSV)
    assert source.row_count == 17_549
    assert source.sha256 == "04c5914d992f397f7dcec3b0d1a6069a9ddeb4a214e5c7de121f37c861cec167"
    # seed 不再要求外部源路径：source_path 缺省即内置默认源
    signature = inspect.signature(seed_resistivity_preset)
    assert signature.parameters["source_path"].default is None


def test_load_rejects_wrong_header(tmp_path: Path):
    frame = _fixture_frame().rename(columns={"RHO": "RES"})
    with pytest.raises(PlatformError) as excinfo:
        load_resistivity_preset(_write_frame(tmp_path, frame))
    assert excinfo.value.code == PRESET_SOURCE_INVALID
    assert excinfo.value.http_status == 409


def test_load_rejects_extra_column_header(tmp_path: Path):
    frame = _fixture_frame().assign(SOURCE_ID=1)
    with pytest.raises(PlatformError) as excinfo:
        load_resistivity_preset(_write_frame(tmp_path, frame))
    assert excinfo.value.code == PRESET_SOURCE_INVALID


def test_load_rejects_wrong_row_count(tmp_path: Path):
    path = write_resistivity_fixture(tmp_path / "short.csv", rows=100)
    with pytest.raises(PlatformError) as excinfo:
        load_resistivity_preset(path)
    assert excinfo.value.code == PRESET_SOURCE_INVALID
    assert excinfo.value.details["expected_rows"] == 17_549
    assert excinfo.value.details["actual_rows"] == 100


def test_load_rejects_nonfinite_values(tmp_path: Path):
    frame = _fixture_frame()
    frame.loc[0, "RHO"] = float("nan")
    with pytest.raises(PlatformError) as excinfo:
        load_resistivity_preset(_write_frame(tmp_path, frame))
    assert excinfo.value.code == PRESET_SOURCE_INVALID


def test_load_rejects_nonnumeric_values(tmp_path: Path):
    frame = _fixture_frame()
    frame["X"] = frame["X"].astype(object)
    frame.loc[1, "X"] = "not-a-number"
    with pytest.raises(PlatformError) as excinfo:
        load_resistivity_preset(_write_frame(tmp_path, frame))
    assert excinfo.value.code == PRESET_SOURCE_INVALID


def test_load_rejects_duplicate_xyz(tmp_path: Path):
    frame = _fixture_frame()
    frame.loc[1, ["X", "Y", "Z"]] = frame.loc[0, ["X", "Y", "Z"]]
    with pytest.raises(PlatformError) as excinfo:
        load_resistivity_preset(_write_frame(tmp_path, frame))
    assert excinfo.value.code == PRESET_SOURCE_INVALID


def test_error_details_never_leak_source_path(tmp_path: Path):
    """合同错误的 details 不含 Path 对象或本机绝对路径文本。"""
    attempts = [
        tmp_path / "missing.csv",
        write_resistivity_fixture(tmp_path / "short.csv", rows=100),
        _write_frame(tmp_path, _fixture_frame().rename(columns={"RHO": "RES"}), "header.csv"),
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
            load_resistivity_preset(candidate)
        assert excinfo.value.code == PRESET_SOURCE_INVALID
        _walk(excinfo.value.details)


@pytest.mark.local_data
def test_real_resistivity_source_matches_verified_contract():
    """真实外部源核验（真值来自 2026-08-08 实测；源文件不入库）。"""
    raw_path = os.environ.get(RHO_SOURCE_ENV)
    if not raw_path:
        pytest.skip(f"{RHO_SOURCE_ENV} 未设置：外部私有源不入库，便携环境跳过")
    source = load_resistivity_preset(Path(raw_path))
    frame = source.frame
    assert source.row_count == 17_549
    assert source.columns == ("X", "Y", "Z", "RHO")
    assert np.isfinite(frame.to_numpy(dtype="float64")).all()
    assert not frame.duplicated(["X", "Y", "Z"]).any()
    rho = frame["RHO"]
    assert float(rho.min()) == pytest.approx(1.032113)
    assert float(rho.max()) == pytest.approx(149.984)
    # 293 个 (X,Y) 空间柱，每柱 42–60 个节点
    columns = frame.groupby(["X", "Y"], sort=False).size()
    assert len(columns) == 293
    assert int(columns.min()) >= 42
    assert int(columns.max()) <= 60
