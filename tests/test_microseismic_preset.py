"""v0.7.0 Batch 1：微震 CSV 预置源合同测试（Task 1）。

受控 CSV 是用户指定标准化文件的原字节拷贝（9 列表头，含 SAMPLE_IDS 等
溯源列）；加载器钉死完整表头、1911 行、有限数值与唯一 XYZ，并向公共
层只暴露 4 个建模列与摘要指纹，绝不返回本机源路径。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from geomodeling.platform.errors import PRESET_SOURCE_INVALID, PlatformError
from geomodeling.platform.microseismic_preset import (
    ORIGINAL_SOURCE_NAME,
    ORIGINAL_SOURCE_SHA256,
    PRESET_CASE_ID,
    PRESET_VERSION,
    REQUIRED_COLUMNS,
    SOURCE_COLUMNS,
    TRACKED_CSV_BYTES,
    TRACKED_CSV_SHA256,
    load_microseismic_preset,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
TRACKED_CSV = REPO_ROOT / "data" / "presets" / "microseismic" / "microseismic-vx-1911.csv"


@pytest.fixture()
def preset_csv() -> Path:
    return TRACKED_CSV


def test_tracked_csv_is_byte_identified_and_never_outside_repo(preset_csv: Path):
    assert preset_csv.is_file()
    # .gitattributes `*.csv text eol=lf`：任何平台检出均为 LF 字节
    digest = hashlib.sha256(preset_csv.read_bytes()).hexdigest()
    assert digest == TRACKED_CSV_SHA256
    assert preset_csv.stat().st_size == TRACKED_CSV_BYTES
    assert preset_csv.resolve().is_relative_to(REPO_ROOT)
    # 溯源记录：用户指定原始文件（CRLF 形态）身份随模块保存
    assert ORIGINAL_SOURCE_SHA256 == "4011de85e1fa7e49999fc5ae66a73e00a59dbec372a417ae0728d0a338c7765e"
    assert ORIGINAL_SOURCE_NAME.endswith("_1911.csv")


def test_load_preset_requires_1911_unique_finite_vx_rows(preset_csv: Path):
    source = load_microseismic_preset(preset_csv)
    assert source.row_count == 1911
    assert source.columns == ("X_LOCAL_M", "Y_LOCAL_M", "Z_LOCAL_M", "VX_KM_S")
    assert source.source_columns == SOURCE_COLUMNS
    assert source.value_unit == "km/s"
    assert source.coordinate_kind == "local_linear"
    assert source.sha256 == TRACKED_CSV_SHA256
    assert list(source.frame.columns) == list(REQUIRED_COLUMNS)
    # Vx 保持 km/s，不静默换算 m/s
    assert float(source.frame["VX_KM_S"].max()) < 10.0


def test_preset_identity_is_stable_and_public():
    assert PRESET_CASE_ID == "builtin-microseismic-vx-1911"
    assert PRESET_VERSION == "microseismic-vx-1911/v1"


def _write(tmp_path: Path, frame: pd.DataFrame, name: str = "candidate.csv") -> Path:
    target = tmp_path / name
    frame.to_csv(target, index=False, encoding="utf-8-sig")
    return target


def _valid_frame() -> pd.DataFrame:
    base = pd.read_csv(TRACKED_CSV, encoding="utf-8-sig")
    return base


def test_load_preset_rejects_wrong_header(tmp_path: Path):
    frame = _valid_frame().drop(columns=["N_MERGED"])
    with pytest.raises(PlatformError) as excinfo:
        load_microseismic_preset(_write(tmp_path, frame))
    assert excinfo.value.code == PRESET_SOURCE_INVALID


def test_load_preset_rejects_wrong_row_count(tmp_path: Path):
    frame = _valid_frame().iloc[:-1]
    with pytest.raises(PlatformError) as excinfo:
        load_microseismic_preset(_write(tmp_path, frame))
    assert excinfo.value.code == PRESET_SOURCE_INVALID


def test_load_preset_rejects_nonfinite_values(tmp_path: Path):
    frame = _valid_frame()
    frame.loc[0, "VX_KM_S"] = float("nan")
    with pytest.raises(PlatformError) as excinfo:
        load_microseismic_preset(_write(tmp_path, frame))
    assert excinfo.value.code == PRESET_SOURCE_INVALID


def test_load_preset_rejects_duplicate_xyz(tmp_path: Path):
    frame = _valid_frame()
    frame.loc[1, ["X_LOCAL_M", "Y_LOCAL_M", "Z_LOCAL_M"]] = frame.loc[
        0, ["X_LOCAL_M", "Y_LOCAL_M", "Z_LOCAL_M"]
    ]
    with pytest.raises(PlatformError) as excinfo:
        load_microseismic_preset(_write(tmp_path, frame))
    assert excinfo.value.code == PRESET_SOURCE_INVALID


def test_load_preset_missing_file_raises_typed_error(tmp_path: Path):
    with pytest.raises(PlatformError) as excinfo:
        load_microseismic_preset(tmp_path / "missing.csv")
    assert excinfo.value.code == PRESET_SOURCE_INVALID
