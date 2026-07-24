"""Task 15: answer presets and the microseismic second-case boundary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from geomodeling.platform.errors import PlatformError
from geomodeling.platform.presets import list_presets, load_preset

CONFIG_DIR = Path("config")


def test_resistivity_preset_preserves_legacy_facts():
    preset = load_preset("resistivity")
    assert preset["source"] == "builtin_legacy"

    raw = yaml.safe_load((CONFIG_DIR / "default.yaml").read_text(encoding="utf-8"))
    expected = raw["expected"]
    facts = preset["facts"]
    assert facts["standardized_rows"] == expected["standardized_rows"] == 17549
    assert facts["training_rows"] == expected["training_rows"] == 15827
    assert facts["validation_rows"] == expected["validation_rows"] == 1722
    assert facts["formal_result"] == "RHO_KRIG_FINAL_20M_40"
    assert facts["s3m_cache"] == "RHO_KRIG_FINAL_20M_40_VOL_S3M2"
    # S3M 固定清单仍在仓库内（体元渲染契约锚点）
    assert Path("config/s3m_cache_manifest.json").exists()
    # 六级证据链等级完整
    assert preset["evidence_levels"] == [
        "model_succeeded",
        "artifact_exported",
        "iserver_published",
        "service_metadata_verified",
        "browser_loaded",
        "manual_visual_checked",
    ]


def test_microseismic_preset_requires_upload_and_states_boundaries():
    preset = load_preset("microseismic")
    assert preset["source"] == "upload_required"
    assert preset["dimension"] == "3d"
    assert preset["value_unit"] == "km/s"
    assert preset["coordinate_kind"] == "local_linear"
    # 浏览器流程只接受派生标准化表格，不读 DAT
    assert preset["accepted_formats"] == ["csv", "xlsx"]
    assert "dat" not in [fmt.lower() for fmt in preset["accepted_formats"]]

    boundary_text = " ".join(preset["boundaries"])
    assert "WL/2" in boundary_text
    assert "局部" in boundary_text
    assert "1.#QNAN0" in boundary_text
    assert "DAT" in boundary_text
    assert "论文" in boundary_text

    # 推荐搜索网格在后端硬上限内
    search = preset["recommended_search"]
    count = 1
    for value in search["parameters"].values():
        count *= len(value) if isinstance(value, list) else 1
    assert 1 <= count <= 50


def test_presets_never_contain_absolute_paths():
    for name in list_presets():
        raw = (CONFIG_DIR / "presets" / f"{name}.json").read_text(encoding="utf-8")
        assert ":\\" not in raw, f"{name} 含盘符绝对路径"
        assert "\\\\" not in raw, f"{name} 含 UNC 路径"
        json.loads(raw)  # 合法 JSON


def test_loader_rejects_absolute_path(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {
                "preset_id": "bad",
                "title": "坏预设",
                "source": "upload_required",
                "dimension": "3d",
                "semantic_fields": {"x": "x", "y": "y", "z": "z", "value": "v"},
                "value_unit": "m",
                "coordinate_kind": "local_linear",
                "accepted_formats": ["csv"],
                "recommended_search": {"algorithm": "idw", "parameters": {"power": [2]}},
                "demo_copy": "见 D:\\secret\\data.csv",
                "boundaries": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with pytest.raises(PlatformError) as excinfo:
        load_preset(bad)
    assert excinfo.value.code == "PRESET_INVALID"
