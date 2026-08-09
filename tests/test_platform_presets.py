"""Task 15: answer presets and the microseismic second-case boundary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from geomodeling.platform.errors import PlatformError
from geomodeling.platform.presets import list_presets, load_preset

CONFIG_DIR = Path("config")


def test_resistivity_preset_declares_builtin_preset_scattered_identity():
    """v0.8.0 Task 1：电阻率公开身份从 builtin_legacy 迁移为 builtin_preset。"""
    preset = load_preset("resistivity")
    assert preset["source"] == "builtin_preset"
    assert preset["dimension"] == "3d"
    assert preset["semantic_fields"] == {"x": "X", "y": "Y", "z": "Z", "value": "RHO"}
    assert preset["coordinate_kind"] == "local_linear"
    # RHO 单位已确认为 Ω·m（v0.8.0 第三批用户权威确认）
    assert preset["value_unit"] == "Ω·m"

    raw = yaml.safe_load((CONFIG_DIR / "default.yaml").read_text(encoding="utf-8"))
    expected = raw["expected"]
    facts = preset["facts"]
    # 行数事实延续既有标准化合同（设计 §2）
    assert facts["standardized_rows"] == expected["standardized_rows"] == 17549
    assert facts["training_rows"] == expected["training_rows"] == 15827
    assert facts["validation_rows"] == expected["validation_rows"] == 1722

    # 旧 S3M/legacy 成果不再作为当前产品身份出现（旧链退役见后续任务）
    raw_text = (CONFIG_DIR / "presets" / "resistivity.json").read_text(encoding="utf-8")
    assert "builtin_legacy" not in raw_text
    assert "S3M" not in raw_text
    assert "s3m" not in raw_text
    assert "RHO_KRIG_FINAL" not in raw_text
    assert "formal_result" not in raw_text
    assert "evidence_levels" not in raw_text
    # 绝不含本机绝对路径
    assert ":\\" not in raw_text
    assert "\\\\" not in raw_text

    boundary_text = " ".join(preset["boundaries"])
    # 局部工程坐标警告：未声明 EPSG、不跨案例叠加
    assert "局部工程坐标" in boundary_text
    assert "EPSG" in boundary_text
    assert "跨案例" in boundary_text
    # RHO 单位 Ω·m + example_data/ 内置源字节冻结合同边界
    assert "Ω·m" in boundary_text
    assert "单位待来源确认" not in boundary_text
    assert "example_data/" in boundary_text
    assert "内置" in boundary_text
    assert "字节" in boundary_text


def test_resistivity_preset_default_grid_is_20m_xyz_within_cell_cap():
    """v0.8.0 Task 5：官方 20 m 三轴网格，边界为已核验真实源范围。"""

    preset = load_preset("resistivity")
    grid = preset["default_grid"]
    assert grid["bounds"] == [[-160, -40], [220, 660], [-833.0047143, -19.5999]]
    assert grid["resolution"] == [20, 20, 20]
    # 与后端 _axis_nodes 同一口径：round(span/step)+1 个节点/轴
    cells = 1
    for (lo, hi), step in zip(grid["bounds"], grid["resolution"]):
        cells *= round((hi - lo) / step) + 1
    assert cells == grid["estimated_cells"] == 7 * 23 * 42 == 6762
    assert cells < grid["max_cells"] == 1_000_000


def test_resistivity_preset_search_grids_cover_three_algorithms_under_cap():
    """v0.8.0 Task 5：IDW/普通克里金/DSI-like 三算法搜索合同，组合数 ≤50。"""

    preset = load_preset("resistivity")
    grids = preset["search_grids"]
    assert set(grids) == {"idw", "ordinary_kriging", "dsi_like"}
    counts = {}
    for algorithm, parameters in grids.items():
        count = 1
        for value in parameters.values():
            count *= len(value)
        counts[algorithm] = count
        assert 1 <= count <= 50
    assert counts == {"idw": 9, "ordinary_kriging": 4, "dsi_like": 18}
    # DSI-like 搜索键严格落在 DSIParameters 允许域内
    dsi = grids["dsi_like"]
    assert set(dsi["neighbor_connectivity"]) <= {6, 18, 26}
    assert all(0 < strength <= 1 for strength in dsi["smoothing_strength"])
    assert set(dsi["max_iterations"]) <= {25, 50}
    assert "hard_constraints" not in dsi, "硬约束恒开，不进入搜索空间"
    # 默认推荐与 search_grids 保持单一事实源（官方基线重建 Kriging 合同）
    assert preset["recommended_search"]["algorithm"] == "ordinary_kriging"
    assert preset["recommended_search"]["search_mode"] == "grid"
    assert preset["recommended_search"]["parameters"] == grids["ordinary_kriging"]


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
