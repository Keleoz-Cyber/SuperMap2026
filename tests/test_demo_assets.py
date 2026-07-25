"""Task 3: the single authoritative public demo dataset contract."""

from __future__ import annotations

import pytest

from geomodeling.demo_assets import DEMO_DATASET_SHA256, get_demo_dataset
from geomodeling.platform.errors import PlatformError

EXPECTED_DEMO_SHA256 = "deb9c25f713ae79d7b1c6300cc8066a6ae927879767c67ab03ef4ad76e8a2bb3"


def test_demo_dataset_contract():
    asset = get_demo_dataset()
    assert asset.path.as_posix().endswith("demo/platform_demo_3d.csv")
    assert asset.sha256 == EXPECTED_DEMO_SHA256 == DEMO_DATASET_SHA256
    assert asset.row_count == 144
    assert asset.columns == ("x", "y", "z", "rho")


def test_demo_dataset_missing_file_fails_closed(tmp_path):
    with pytest.raises(PlatformError) as excinfo:
        get_demo_dataset(tmp_path / "missing.csv")
    assert excinfo.value.code == "DEMO_DATASET_UNAVAILABLE"


def test_demo_dataset_modified_hash_fails_closed(tmp_path):
    tampered = tmp_path / "platform_demo_3d.csv"
    tampered.write_text("x,y,z,rho\n1,2,3,4\n", encoding="utf-8")
    with pytest.raises(PlatformError) as excinfo:
        get_demo_dataset(tampered)
    assert excinfo.value.code == "DEMO_DATASET_UNAVAILABLE"
    # 公开诊断不含本机绝对路径
    assert str(tmp_path) not in str(excinfo.value.details)
