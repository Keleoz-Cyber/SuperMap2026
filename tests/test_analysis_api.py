"""v0.8.0 第二批 Task 3：只读分析摘要与导出 API 合同测试。

端点：``GET /api/datasets/{dataset_id}/analysis-summary`` 与
``GET /api/datasets/{dataset_id}/analysis-export?format=json|csv``。
合同锁定（设计 §6/§8）：

- 已验证微震/电阻率预置数据返回正确 ``analysis_profile``、质量/统计/分布/
  空间/三轴剖面模块与 provenance（source_sha256/dataset_version/
  calculation_version）；Task 6 起专属模块为真实有限计算（微震
  axis_trends/gradient/spatial_anomaly，电阻率 log 分布/depth_slices/
  spatial_anomaly），载荷带计算方法/来源字段/阈值来源。
- 未知 dataset → 404 ``DATASET_NOT_FOUND``；回收案例 → 410 ``CASE_TRASHED``；
  未验证 dataset → 409 ``DATASET_NOT_VALIDATED``；空公共有效集 → 409
  ``ANALYSIS_EMPTY_COMMON_VALID``（绝不返回 null 堆叠伪成功面板）。
- model_comparison 只读既有 succeeded 候选（result_id/算法/参数摘要/公共
  指标/物化状态/是否正式选择），绝不重算指标。
- 导出：json → application/json + Content-Disposition 安全文件名（含
  dataset/profile 标识）；csv → text/csv，头部 provenance 注释行 +
  稳定表头 ``section,axis,bin_index,metric,lower,upper,value`` + 轴身份列。
- 任何响应绝不包含 ``standardized_path`` 字样或本机绝对路径。

夹具：微震预置 seed / 电阻率预置 seed（粗网格夹具基线）/ 空运行库，
模式参照 ``test_case_workspace_api`` 与 ``test_resistivity_preset_seed``。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from geomodeling.analysis.schemas import CALCULATION_VERSION
from geomodeling.api.routes import analysis as analysis_routes
from geomodeling.platform import tables
from geomodeling.platform.microseismic_preset import (
    PRESET_CASE_ID,
    TRACKED_CSV_SHA256,
    seed_microseismic_preset,
)
from geomodeling.platform.resistivity_preset import (
    PRESET_CASE_ID as RESISTIVITY_PRESET_CASE_ID,
    load_resistivity_preset,
    seed_resistivity_preset,
)
from test_resistivity_preset import write_resistivity_fixture
from test_resistivity_preset_seed import _fixture_baseline

CSV_HEADER = "section,axis,bin_index,metric,lower,upper,value"


def _make_client(tmp_path: Path, *, seed: str | None):
    from fastapi.testclient import TestClient

    from geomodeling.api.app import create_app
    from geomodeling.api.deps import (
        ApiSettings,
        get_app_config,
        get_iserver_client,
        get_settings,
    )
    from geomodeling.platform import PlatformRuntime
    from test_api import FakeIServer, make_config

    fixture_csv = Path("tests/fixtures/rho_tiny_validation.csv").resolve()
    config = make_config(standardized=fixture_csv)
    settings = ApiSettings(
        config_path=Path("config/default.yaml"),
        metrics_json=(tmp_path / "m.json"),
        evidence_dir=tmp_path / "evidence",
        frontend_dist=None,
        voxel_cache_dir=tmp_path / "cache",
    )
    (tmp_path / "m.json").write_text('{"summaries": {}}', encoding="utf-8")

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_app_config] = lambda: config
    app.dependency_overrides[get_iserver_client] = lambda: FakeIServer({})

    runtime = PlatformRuntime(tmp_path / "data")
    runtime.initialize()
    if seed == "microseismic":
        seed_microseismic_preset(runtime)
    elif seed == "resistivity":
        source_path = write_resistivity_fixture(tmp_path / "rho-source.csv", rows=17_549)
        source = load_resistivity_preset(source_path)
        seed_resistivity_preset(
            runtime, source_path=source_path, baseline=_fixture_baseline(source)
        )
    app.state.platform_runtime = runtime
    client = TestClient(app)
    client.runtime_dir = str(tmp_path)  # 供路径泄漏扫描断言
    return client


@pytest.fixture(scope="module")
def micro_client(tmp_path_factory):
    return _make_client(tmp_path_factory.mktemp("analysis-micro"), seed="microseismic")


@pytest.fixture(scope="module")
def rho_client(tmp_path_factory):
    return _make_client(tmp_path_factory.mktemp("analysis-rho"), seed="resistivity")


@pytest.fixture()
def fresh_client(tmp_path):
    return _make_client(tmp_path, seed=None)


def _primary_dataset_id(client, case_id: str) -> str:
    response = client.get(f"/api/cases/{case_id}/workspace")
    assert response.status_code == 200, response.text
    return response.json()["primary_dataset"]["id"]


def _official_result_id(client, case_id: str) -> str:
    response = client.get(f"/api/cases/{case_id}/workspace")
    assert response.status_code == 200, response.text
    return response.json()["official_result"]["result_id"]


def _modules(body: dict) -> dict:
    return {module["module_id"]: module for module in body["modules"]}


def _insert_case_dataset(
    client, case_id: str, dataset_id: str, *, status: str, profile: dict | None = None
) -> None:
    runtime = client.app.state.platform_runtime
    with runtime.session() as session:
        session.add(
            tables.Case(id=case_id, name="分析测试案例", case_type="generic", config_json="{}")
        )
        session.add(
            tables.DatasetVersion(
                id=dataset_id,
                case_id=case_id,
                version=1,
                status=status,
                source_path="pending://upload",
                profile_json=tables.dumps_canonical(profile or {}),
            )
        )
        session.commit()


# ---------------------------------------------------------------------------
# analysis-summary：预置 profile / 质量 / 统计 / 模块 / provenance
# ---------------------------------------------------------------------------


def test_microseismic_summary_returns_profile_quality_statistics_modules_provenance(
    micro_client,
):
    dataset_id = _primary_dataset_id(micro_client, PRESET_CASE_ID)
    response = micro_client.get(f"/api/datasets/{dataset_id}/analysis-summary")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["dataset_id"] == dataset_id
    assert body["case_id"] == PRESET_CASE_ID
    assert body["analysis_profile"] == "microseismic_velocity"
    assert body["profile_version"] == 1
    assert body["variable"] == {"name": "Vx", "unit": "km/s"}

    quality = body["quality"]
    assert quality["row_count"] == 1911
    assert quality["valid_count"] == 1911
    assert quality["invalid_count"] == 0
    assert quality["duplicate_coordinate_count"] == 0
    assert set(quality["bounds"]) == {"x", "y", "z"}

    statistics = body["statistics"]
    assert statistics["count"] == 1911
    assert statistics["min"] <= statistics["median"] <= statistics["max"]
    assert statistics["quantiles"]["p50"] == statistics["median"]
    assert statistics["std"] is not None

    modules = _modules(body)
    assert set(modules) == {
        "quality",
        "statistics",
        "distribution",
        "axis_trends",
        "gradient",
        "spatial_anomaly",
        "profile_slices",
        "model_comparison",
    }
    # 不生成时间演化/震源能量等数据中不存在的指标（设计 §5.1）
    assert not {"time_evolution", "temporal_trend", "source_energy", "magnitude"} & set(
        modules
    )
    # 通用模块与 Task 6 专属模块全部就位（status == "ok"）
    for module_id in (
        "quality",
        "statistics",
        "distribution",
        "profile_slices",
        "model_comparison",
        "axis_trends",
        "gradient",
        "spatial_anomaly",
    ):
        assert modules[module_id]["status"] == "ok", module_id

    distribution = modules["distribution"]["payload"]
    assert len(distribution["bins"]) == 32
    assert sum(bin_["count"] for bin_ in distribution["bins"]) == 1911

    # axis_trends：X/Y/Z 逐轴分箱趋势，附计算方法/来源字段/轴身份/样本数
    axis_trends = modules["axis_trends"]["payload"]
    assert axis_trends["method"]
    assert axis_trends["source_fields"]["value"] == "VX_KM_S"
    assert axis_trends["source_fields"]["z"] == "Z_LOCAL_M"
    assert {axis["axis"] for axis in axis_trends["axes"]} == {"x", "y", "z"}
    for axis_summary in axis_trends["axes"]:
        assert axis_summary["sample_count"] == 1911
        assert len(axis_summary["bins"]) == 32
        assert sum(bin_["count"] for bin_ in axis_summary["bins"]) == 1911

    # gradient：相邻网格差分幅值有限统计，方法与排除计数保留
    gradient = modules["gradient"]["payload"]
    assert gradient["method"]
    assert gradient["source_fields"]["value"] == "VX_KM_S"
    assert gradient["count"] > 0
    assert gradient["mean"] is not None
    assert gradient["p95"] is not None
    assert gradient["pair_count"] > gradient["count"]
    assert gradient["excluded_pair_count"] >= 0

    # spatial_anomaly：速度高/低值区域，含体积占比与阈值来源
    anomaly = modules["spatial_anomaly"]["payload"]
    assert anomaly["method"]
    assert anomaly["thresholds"]["source"]
    assert "p75" in anomaly["thresholds"]["method"]
    assert "p25" in anomaly["thresholds"]["method"]
    assert len(anomaly["bins"]) == 32 * 32
    assert {bin_["region"] for bin_ in anomaly["bins"]} <= {
        "high",
        "low",
        "normal",
        "empty",
    }
    assert 0.0 <= anomaly["high_volume_ratio"] <= 1.0
    assert 0.0 <= anomaly["low_volume_ratio"] <= 1.0

    profile_slices = modules["profile_slices"]["payload"]
    assert {axis["axis"] for axis in profile_slices["axes"]} == {"x", "y", "z"}
    for axis_summary in profile_slices["axes"]:
        assert len(axis_summary["bins"]) == 32

    provenance = body["provenance"]
    assert provenance["source_sha256"] == TRACKED_CSV_SHA256
    assert provenance["dataset_version"] == 1
    assert provenance["calculation_version"] == CALCULATION_VERSION
    assert provenance["generated_at"]


def test_resistivity_summary_returns_resistivity_profile(rho_client):
    dataset_id = _primary_dataset_id(rho_client, RESISTIVITY_PRESET_CASE_ID)
    response = rho_client.get(f"/api/datasets/{dataset_id}/analysis-summary")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["analysis_profile"] == "resistivity"
    assert body["variable"]["name"] == "RHO"
    assert body["quality"]["row_count"] == 17_549
    assert body["statistics"]["count"] == 17_549

    modules = _modules(body)
    for module_id in (
        "distribution",
        "profile_slices",
        "model_comparison",
        "depth_slices",
        "spatial_anomaly",
    ):
        assert modules[module_id]["status"] == "ok", module_id

    # distribution 升级：log10 分箱（仅严格正值）与原始值分箱并存，排除计数保留
    distribution = modules["distribution"]["payload"]
    assert distribution["method"]
    assert distribution["source_fields"]["value"] == "RHO"
    assert len(distribution["bins"]) == 32  # 原始值分箱保留
    log10 = distribution["log10"]
    assert log10["method"]
    assert log10["bins"] is not None and len(log10["bins"]) == 32
    assert log10["excluded_non_positive_count"] == 0  # 夹具 RHO 全为严格正值
    assert sum(bin_["count"] for bin_ in log10["bins"]) == 17_549

    # depth_slices：逐 Z 层超阈占比，分位阈值来源明示
    depth = modules["depth_slices"]["payload"]
    assert depth["method"]
    assert depth["source_fields"]["z"] == "Z"
    assert depth["thresholds"]["source"]
    assert "p75" in depth["thresholds"]["method"]
    assert len(depth["slices"]) == 16
    assert sum(slice_["count"] for slice_ in depth["slices"]) == 17_549

    # spatial_anomaly：高/低阻区域聚合；阈值以非空单元均值自身分位数产生
    # （致密采样下样本级阈值会被单元均值平滑掉），与 depth_slices 的样本级
    # 阈值是两个不同口径，各自来源字段如实标注
    anomaly = modules["spatial_anomaly"]["payload"]
    assert anomaly["method"]
    assert anomaly["thresholds"]["source"] == "cell_mean_quantiles_p25_p75"
    assert "单元均值" in anomaly["thresholds"]["method"]
    assert depth["thresholds"]["source"] == "valid_value_quantiles_p25_p75"
    assert anomaly["high_cell_count"] + anomaly["low_cell_count"] > 0
    assert {bin_["region"] for bin_ in anomaly["bins"]} <= {
        "high",
        "low",
        "normal",
        "empty",
    }

    provenance = body["provenance"]
    assert len(provenance["source_sha256"]) == 64
    assert provenance["dataset_version"] == 1
    assert provenance["calculation_version"] == CALCULATION_VERSION


def test_summary_spatial_extent_module_for_generic_profile(fresh_client):
    """通用降级 profile：spatial_extent 模块就位（专属 profile 无此模块）。"""

    runtime = fresh_client.app.state.platform_runtime
    case_id, dataset_id = "gen-case", "gen-ds"
    target = runtime.settings.standardized_dataset(case_id, dataset_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "source_row": [0, 1, 2, 3],
            "x": [0.0, 1.0, 2.0, 3.0],
            "y": [0.0, 1.0, 0.0, 1.0],
            "z": [0.0, 0.0, 1.0, 1.0],
            "value": [1.0, 2.0, 3.0, 4.0],
            "is_numeric_valid": [True, True, True, True],
        }
    )
    frame.to_parquet(target, index=False)
    profile = {
        "dimension": "3d",
        "mapping": {
            "dimension": "3d",
            "x": "X",
            "y": "Y",
            "z": "Z",
            "value": "VAL",
            "value_name": "VAL",
        },
        "source_sha256": "a" * 64,
    }
    _insert_case_dataset(fresh_client, case_id, dataset_id, status="validated", profile=profile)
    with runtime.session() as session:
        row = session.get(tables.DatasetVersion, dataset_id)
        row.standardized_path = str(target)
        session.commit()

    response = fresh_client.get(f"/api/datasets/{dataset_id}/analysis-summary")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["analysis_profile"] == "generic_3d"
    assert body["variable"]["unit"] is None
    modules = _modules(body)
    # 通用降级不暴露任何专属模块（微震/电阻率/瓦斯专属一律不出现）
    assert not {
        "axis_trends",
        "gradient",
        "depth_slices",
        "spatial_anomaly",
        "threshold_zones",
    } & set(modules)
    spatial = modules["spatial_extent"]
    assert spatial["status"] == "ok"
    payload = spatial["payload"]
    assert payload["grid_size"] == 32
    assert payload["cell_count"] == 32 * 32
    assert len(payload["bins"]) == 32 * 32
    assert modules["model_comparison"]["payload"]["candidates"] == []


def test_resistivity_payload_has_no_geological_semantic_conclusions(rho_client):
    """单位未确认（RHO）：payload/copy 禁止水、矿、瓦斯通道等地质语义结论。"""

    dataset_id = _primary_dataset_id(rho_client, RESISTIVITY_PRESET_CASE_ID)
    response = rho_client.get(f"/api/datasets/{dataset_id}/analysis-summary")
    assert response.status_code == 200, response.text
    text = response.text
    for term in ("含水", "水体", "矿体", "矿产", "瓦斯"):
        assert term not in text, term


# ---------------------------------------------------------------------------
# model_comparison：只读既有 succeeded 候选
# ---------------------------------------------------------------------------


def test_model_comparison_lists_existing_candidates_read_only(micro_client):
    dataset_id = _primary_dataset_id(micro_client, PRESET_CASE_ID)
    official_id = _official_result_id(micro_client, PRESET_CASE_ID)

    response = micro_client.get(f"/api/datasets/{dataset_id}/analysis-summary")
    assert response.status_code == 200, response.text
    module = _modules(response.json())["model_comparison"]
    candidates = module["payload"]["candidates"]
    assert len(candidates) == 1, "seed 官方链只有一条 succeeded 候选"
    official = candidates[0]
    assert official["result_id"] == official_id
    assert official["algorithm"] == "ordinary_kriging"
    assert official["parameters"], "候选参数摘要必须随记录出站"
    metrics = official["metrics"]
    for key in ("rmse", "mae", "r2", "bias"):
        assert metrics[key] is not None and np.isfinite(metrics[key]), key
    assert official["materialized"] is True
    assert official["formal_selection"] is True
    assert official["result_url"] == f"/results/{official_id}"

    # 只读语义：重复调用不得新增候选/任务记录，候选清单逐位一致
    runtime = micro_client.app.state.platform_runtime
    with runtime.session() as session:
        candidate_count = session.query(tables.CandidateResult).count()
        run_count = session.query(tables.Run).count()
    second = micro_client.get(f"/api/datasets/{dataset_id}/analysis-summary")
    assert second.status_code == 200, second.text
    assert _modules(second.json())["model_comparison"] == module
    with runtime.session() as session:
        assert session.query(tables.CandidateResult).count() == candidate_count
        assert session.query(tables.Run).count() == run_count


# ---------------------------------------------------------------------------
# 错误合同：404 / 410 / 409 / 空公共有效集
# ---------------------------------------------------------------------------


def test_unknown_dataset_returns_404(micro_client):
    response = micro_client.get("/api/datasets/no-such-dataset/analysis-summary")
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "DATASET_NOT_FOUND"
    export = micro_client.get("/api/datasets/no-such-dataset/analysis-export")
    assert export.status_code == 404, export.text
    assert export.json()["error"]["code"] == "DATASET_NOT_FOUND"


def test_trashed_case_returns_410(fresh_client):
    _insert_case_dataset(fresh_client, "trash-case", "trash-ds", status="uploaded")
    delete = fresh_client.delete("/api/cases/trash-case")
    assert delete.status_code == 200, delete.text

    summary = fresh_client.get("/api/datasets/trash-ds/analysis-summary")
    assert summary.status_code == 410, summary.text
    assert summary.json()["error"]["code"] == "CASE_TRASHED"
    export = fresh_client.get("/api/datasets/trash-ds/analysis-export")
    assert export.status_code == 410, export.text
    assert export.json()["error"]["code"] == "CASE_TRASHED"


def test_unvalidated_dataset_returns_409(fresh_client):
    _insert_case_dataset(fresh_client, "up-case", "up-ds", status="uploaded")
    summary = fresh_client.get("/api/datasets/up-ds/analysis-summary")
    assert summary.status_code == 409, summary.text
    body = summary.json()
    assert body["error"]["code"] == "DATASET_NOT_VALIDATED"
    assert body["error"]["details"]["status"] == "uploaded"
    export = fresh_client.get("/api/datasets/up-ds/analysis-export")
    assert export.status_code == 409, export.text
    assert export.json()["error"]["code"] == "DATASET_NOT_VALIDATED"


def test_empty_common_valid_returns_409_never_null_panels(fresh_client):
    runtime = fresh_client.app.state.platform_runtime
    case_id, dataset_id = "empty-case", "empty-ds"
    target = runtime.settings.standardized_dataset(case_id, dataset_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "source_row": [0, 1, 2],
            "x": [0.0, 1.0, 2.0],
            "y": [0.0, 1.0, 2.0],
            "z": [0.0, 1.0, 2.0],
            "value": [float("nan")] * 3,
            "is_numeric_valid": [True, True, True],
        }
    )
    frame.to_parquet(target, index=False)
    profile = {
        "dimension": "3d",
        "mapping": {
            "dimension": "3d",
            "x": "X",
            "y": "Y",
            "z": "Z",
            "value": "VAL",
            "value_name": "VAL",
        },
        "source_sha256": "b" * 64,
    }
    _insert_case_dataset(fresh_client, case_id, dataset_id, status="validated", profile=profile)
    with runtime.session() as session:
        row = session.get(tables.DatasetVersion, dataset_id)
        row.standardized_path = str(target)
        session.commit()

    response = fresh_client.get(f"/api/datasets/{dataset_id}/analysis-summary")
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "ANALYSIS_EMPTY_COMMON_VALID"


# ---------------------------------------------------------------------------
# 导出：json / csv / 非法 format
# ---------------------------------------------------------------------------


def test_export_json_content_type_safe_filename_and_provenance(micro_client):
    dataset_id = _primary_dataset_id(micro_client, PRESET_CASE_ID)
    response = micro_client.get(
        f"/api/datasets/{dataset_id}/analysis-export", params={"format": "json"}
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    assert f'filename="analysis-{dataset_id}-microseismic_velocity.json"' in disposition
    assert "\\" not in disposition and "/" not in disposition.split("filename=")[1]

    body = response.json()
    assert body["dataset_id"] == dataset_id
    assert body["analysis_profile"] == "microseismic_velocity"
    assert body["provenance"]["source_sha256"] == TRACKED_CSV_SHA256
    assert body["provenance"]["calculation_version"] == CALCULATION_VERSION
    assert body["statistics"]["count"] == 1911


def test_export_csv_stable_header_axis_identity_and_provenance_comments(micro_client):
    dataset_id = _primary_dataset_id(micro_client, PRESET_CASE_ID)
    response = micro_client.get(
        f"/api/datasets/{dataset_id}/analysis-export", params={"format": "csv"}
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    disposition = response.headers["content-disposition"]
    assert f'filename="analysis-{dataset_id}-microseismic_velocity.csv"' in disposition

    lines = response.text.splitlines()
    # provenance 头部注释行（本批锁定的唯一形态：注释行而非数据行）
    assert lines[0] == f"# dataset_id={dataset_id}"
    assert lines[1] == f"# case_id={PRESET_CASE_ID}"
    assert lines[2] == "# analysis_profile=microseismic_velocity"
    assert lines[3] == f"# source_sha256={TRACKED_CSV_SHA256}"
    assert lines[4] == "# dataset_version=1"
    assert lines[5] == f"# calculation_version={CALCULATION_VERSION}"
    assert lines[6].startswith("# generated_at=")
    assert lines[7] == CSV_HEADER

    rows = lines[8:]
    statistics_rows = [row for row in rows if row.startswith("statistics,")]
    assert any(row == "statistics,,,count,,,1911" for row in statistics_rows)
    for metric in ("min", "max", "mean", "median", "std", "p05", "p25", "p50", "p75", "p95"):
        assert any(row.startswith(f"statistics,,,{metric},,,") for row in statistics_rows), metric

    distribution_rows = [row for row in rows if row.startswith("distribution,")]
    assert len(distribution_rows) == 32
    assert all(row.split(",")[3] == "count" for row in distribution_rows)

    profile_rows = [row for row in rows if row.startswith("profile,")]
    assert {row.split(",")[1] for row in profile_rows} == {"x", "y", "z"}
    assert {row.split(",")[3] for row in profile_rows} == {"count", "mean", "median"}
    for axis in ("x", "y", "z"):
        assert sum(1 for row in profile_rows if row.startswith(f"profile,{axis},")) == 32 * 3


def test_export_invalid_format_returns_typed_422(micro_client):
    dataset_id = _primary_dataset_id(micro_client, PRESET_CASE_ID)
    response = micro_client.get(
        f"/api/datasets/{dataset_id}/analysis-export", params={"format": "yaml"}
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "ANALYSIS_EXPORT_FORMAT_INVALID"


def test_export_csv_resistivity_profile(rho_client):
    dataset_id = _primary_dataset_id(rho_client, RESISTIVITY_PRESET_CASE_ID)
    response = rho_client.get(
        f"/api/datasets/{dataset_id}/analysis-export", params={"format": "csv"}
    )
    assert response.status_code == 200, response.text
    lines = response.text.splitlines()
    assert lines[0] == f"# dataset_id={dataset_id}"
    assert lines[2] == "# analysis_profile=resistivity"
    assert lines[7] == CSV_HEADER
    assert any(row == "statistics,,,count,,,17549" for row in lines)


# ---------------------------------------------------------------------------
# Task 7 导出合同强化：完整 provenance / ok 模块摘要 / 410 不触盘
# ---------------------------------------------------------------------------


def test_export_json_full_provenance_and_ok_module_summaries(micro_client):
    """JSON 导出：数据身份 + profile + 源哈希 + 计算版本 + 生成时间 + 全部 ok 模块摘要。"""

    dataset_id = _primary_dataset_id(micro_client, PRESET_CASE_ID)
    response = micro_client.get(
        f"/api/datasets/{dataset_id}/analysis-export", params={"format": "json"}
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["dataset_id"] == dataset_id
    assert body["case_id"] == PRESET_CASE_ID
    assert body["analysis_profile"] == "microseismic_velocity"
    provenance = body["provenance"]
    assert provenance["source_sha256"] == TRACKED_CSV_SHA256
    assert provenance["dataset_version"] == 1
    assert provenance["calculation_version"] == CALCULATION_VERSION
    generated_at = provenance["generated_at"]
    assert generated_at and datetime.fromisoformat(generated_at), generated_at

    # 全部 ok 模块摘要随导出出站，且与 analysis-summary 同一组装逐位一致
    summary = micro_client.get(f"/api/datasets/{dataset_id}/analysis-summary").json()
    export_modules = {module["module_id"]: module for module in body["modules"]}
    summary_modules = {module["module_id"]: module for module in summary["modules"]}
    assert set(export_modules) == set(summary_modules)
    ok_modules = [module for module in body["modules"] if module["status"] == "ok"]
    assert ok_modules, "微震预置导出必须包含 ok 模块"
    for module in ok_modules:
        assert module["payload"], module["module_id"]
    for module_id, module in summary_modules.items():
        assert export_modules[module_id] == module, module_id


def test_export_csv_provenance_comment_block_complete_and_verbatim(rho_client):
    """CSV 导出：provenance 注释行齐全（7 行固定键序）+ 表头逐字稳定 + 轴身份列。"""

    dataset_id = _primary_dataset_id(rho_client, RESISTIVITY_PRESET_CASE_ID)
    response = rho_client.get(
        f"/api/datasets/{dataset_id}/analysis-export", params={"format": "csv"}
    )
    assert response.status_code == 200, response.text
    lines = response.text.splitlines()

    comments = [line for line in lines if line.startswith("#")]
    assert len(comments) == 7, "provenance 注释行必须齐全且仅 7 行"
    keys = [line[1:].split("=", 1)[0].strip() for line in comments]
    assert keys == [
        "dataset_id",
        "case_id",
        "analysis_profile",
        "source_sha256",
        "dataset_version",
        "calculation_version",
        "generated_at",
    ]
    values = [line.split("=", 1)[1].strip() for line in comments]
    assert all(values), "provenance 注释行值不得为空"
    assert comments[0] == f"# dataset_id={dataset_id}"
    assert comments[2] == "# analysis_profile=resistivity"

    # 注释块之后立即是逐字稳定表头
    assert lines[7] == "section,axis,bin_index,metric,lower,upper,value"

    # 轴身份列：profile 行 axis ∈ {x,y,z}，bin_index 为整数序
    profile_rows = [line.split(",") for line in lines[8:] if line.startswith("profile,")]
    assert profile_rows, "电阻率导出必须包含剖面行"
    assert {row[1] for row in profile_rows} == {"x", "y", "z"}
    for row in profile_rows:
        assert row[2].isdigit(), row
        assert row[3] in {"count", "mean", "median"}, row


def test_trashed_export_returns_410_without_reading_files(fresh_client, monkeypatch):
    """回收案例导出：410 CASE_TRASHED，且绝不进入文件加载/读取阶段。"""

    _insert_case_dataset(fresh_client, "gone-case", "gone-ds", status="uploaded")
    delete = fresh_client.delete("/api/cases/gone-case")
    assert delete.status_code == 200, delete.text

    def _forbidden(*args, **kwargs):  # pragma: no cover - 触盘即失败
        raise AssertionError("回收案例导出不得加载/读取任何数据文件")

    monkeypatch.setattr(analysis_routes, "_load_standardized_frame", _forbidden)
    monkeypatch.setattr(pd, "read_parquet", _forbidden)
    for fmt in ("json", "csv"):
        response = fresh_client.get(
            "/api/datasets/gone-ds/analysis-export", params={"format": fmt}
        )
        assert response.status_code == 410, response.text
        assert response.json()["error"]["code"] == "CASE_TRASHED"


# ---------------------------------------------------------------------------
# 路径泄漏扫描：响应绝不包含 standardized_path 字样或本机绝对路径
# ---------------------------------------------------------------------------


def test_responses_never_leak_paths(micro_client):
    dataset_id = _primary_dataset_id(micro_client, PRESET_CASE_ID)
    runtime_dir = micro_client.runtime_dir
    # 绝对路径形态：Windows 盘符（反/正斜杠）、UNC、file://、POSIX 用户目录
    absolute_path_shapes = (":\\", ":/", "\\\\", "file://", "/home/", "/Users/")
    for url in (
        f"/api/datasets/{dataset_id}/analysis-summary",
        f"/api/datasets/{dataset_id}/analysis-export?format=json",
        f"/api/datasets/{dataset_id}/analysis-export?format=csv",
    ):
        text = micro_client.get(url).text
        assert "standardized_path" not in text, url
        assert runtime_dir not in text, url
        for shape in absolute_path_shapes:
            assert shape not in text, f"{url} 泄漏绝对路径形态 {shape!r}"
