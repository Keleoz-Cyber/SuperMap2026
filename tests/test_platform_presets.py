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


def test_microseismic_preset_uses_domain_adapter_and_matches_aggregated_columns():
    preset = load_preset("microseismic")
    assert preset["source"] == "domain_adapter"
    assert preset["adapter_id"] == "microseismic_dat_v05"
    assert preset["dimension"] == "3d"
    assert preset["value_unit"] == "km/s"
    assert preset["coordinate_kind"] == "local_linear"
    # 浏览器流程由领域适配器导入正式 DAT 集合（Task 11），不再接受派生表格上传
    assert preset["accepted_formats"] == ["dat"]
    # 自动字段映射与聚合建模节点列一致（platform_adapter.MAPPING）
    assert preset["semantic_fields"] == {
        "x": "X_LOCAL_M",
        "y": "Y_LOCAL_M",
        "z": "Z_LOCAL_M",
        "value": "VX_KM_S",
    }

    boundary_text = " ".join(preset["boundaries"])
    assert "WL/2" in boundary_text
    assert "km/s" in boundary_text
    # 局部坐标警告：局部工程坐标、非 EPSG、不跨案例叠加
    assert "局部工程坐标" in boundary_text
    assert "EPSG" in boundary_text
    assert "跨案例" in boundary_text
    assert "1.#QNAN0" in boundary_text
    assert "DAT" in boundary_text
    assert "论文" in boundary_text
    # z_scale 是实验参数而非已确认各向异性
    assert "z_scale" in boundary_text


def test_microseismic_preset_default_grid_is_50m_xyz_within_cell_cap():
    preset = load_preset("microseismic")
    grid = preset["default_grid"]
    # 黄金候选实际物理范围
    assert grid["bounds"] == [[-750, 960], [-995, 1310], [-4086.538, -37.5]]
    assert grid["resolution"] == [50, 50, 50]
    # 与后端 _axis_nodes 同一口径：round(span/step)+1 个节点/轴
    cells = 1
    for (lo, hi), step in zip(grid["bounds"], grid["resolution"]):
        cells *= round((hi - lo) / step) + 1
    assert cells == grid["estimated_cells"]
    assert cells < grid["max_cells"] == 1_000_000


def test_microseismic_preset_search_grids_are_under_combination_cap():
    preset = load_preset("microseismic")
    grids = preset["search_grids"]
    idw = grids["idw"]
    kriging = grids["ordinary_kriging"]

    idw_count = len(idw["power"]) * len(idw["neighbor_count"]) * len(idw["z_scale"])
    kriging_count = (
        len(kriging["variogram_model"]) * len(kriging["neighbor_count"]) * len(kriging["z_scale"])
    )
    assert idw_count == 36
    assert kriging_count == 27
    assert idw_count < 50
    assert kriging_count < 50
    # 默认推荐与 search_grids 保持单一事实源
    assert preset["recommended_search"]["algorithm"] == "idw"
    assert preset["recommended_search"]["search_mode"] == "grid"
    assert preset["recommended_search"]["parameters"] == idw


def test_loader_rejects_unknown_domain_adapter(tmp_path):
    base = {
        "preset_id": "bad_adapter",
        "title": "坏适配器",
        "source": "domain_adapter",
        "dimension": "3d",
        "semantic_fields": {"x": "x", "y": "y", "z": "z", "value": "v"},
        "value_unit": "m",
        "coordinate_kind": "local_linear",
        "recommended_search": {"algorithm": "idw", "parameters": {"power": [2]}},
        "demo_copy": "占位",
        "boundaries": [],
    }
    missing = tmp_path / "missing.json"
    missing.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(PlatformError) as excinfo:
        load_preset(missing)
    assert excinfo.value.code == "PRESET_INVALID"

    wrong = tmp_path / "wrong.json"
    wrong.write_text(
        json.dumps({**base, "adapter_id": "some_other_adapter"}, ensure_ascii=False),
        encoding="utf-8",
    )
    with pytest.raises(PlatformError) as excinfo:
        load_preset(wrong)
    assert excinfo.value.code == "PRESET_INVALID"


def test_loader_rejects_oversized_search_grids(tmp_path):
    bad = tmp_path / "oversized.json"
    bad.write_text(
        json.dumps(
            {
                "preset_id": "oversized",
                "title": "超上限",
                "source": "domain_adapter",
                "adapter_id": "microseismic_dat_v05",
                "dimension": "3d",
                "semantic_fields": {"x": "x", "y": "y", "z": "z", "value": "v"},
                "value_unit": "m",
                "coordinate_kind": "local_linear",
                "recommended_search": {"algorithm": "idw", "parameters": {"power": [2]}},
                "search_grids": {
                    # 6 × 9 = 54，超出 50 硬上限
                    "idw": {
                        "power": [1, 2, 3, 4, 5, 6],
                        "neighbor_count": [4, 8, 12, 16, 24, 32, 48, 64, 96],
                    },
                },
                "demo_copy": "占位",
                "boundaries": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with pytest.raises(PlatformError) as excinfo:
        load_preset(bad)
    assert excinfo.value.code == "PRESET_INVALID"


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
