"""v0.8.0 第二批 Task 3：只读分析摘要与导出 API 合同测试。

端点：``GET /api/datasets/{dataset_id}/analysis-summary`` 与
``GET /api/datasets/{dataset_id}/analysis-export?format=json|csv``。
合同锁定（设计 §6/§8）：

- 已验证微震/电阻率预置数据返回正确 ``analysis_profile``、质量/统计/分布/
  空间/三轴剖面模块与 provenance（source_sha256/dataset_version/
  calculation_version）；专属模块本批为 ``disabled`` 骨架（计算属 Task 6）。
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

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from geomodeling.analysis.schemas import CALCULATION_VERSION
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
    # 通用模块本批就位；专属模块为 Task 6 骨架（disabled + 解释消息）
    for module_id in ("quality", "statistics", "distribution", "profile_slices", "model_comparison"):
        assert modules[module_id]["status"] == "ok", module_id
    for module_id in ("axis_trends", "gradient", "spatial_anomaly"):
        assert modules[module_id]["status"] == "disabled", module_id
        assert modules[module_id]["message"], module_id

    distribution = modules["distribution"]["payload"]
    assert len(distribution["bins"]) == 32
    assert sum(bin_["count"] for bin_ in distribution["bins"]) == 1911

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
    assert modules["distribution"]["status"] == "ok"
    assert modules["profile_slices"]["status"] == "ok"
    assert modules["model_comparison"]["status"] == "ok"
    assert modules["depth_slices"]["status"] == "disabled"
    assert modules["spatial_anomaly"]["status"] == "disabled"

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
    spatial = modules["spatial_extent"]
    assert spatial["status"] == "ok"
    payload = spatial["payload"]
    assert payload["grid_size"] == 32
    assert payload["cell_count"] == 32 * 32
    assert len(payload["bins"]) == 32 * 32
    assert modules["model_comparison"]["payload"]["candidates"] == []


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
# 路径泄漏扫描：响应绝不包含 standardized_path 字样或本机绝对路径
# ---------------------------------------------------------------------------


def test_responses_never_leak_paths(micro_client):
    dataset_id = _primary_dataset_id(micro_client, PRESET_CASE_ID)
    runtime_dir = micro_client.runtime_dir
    for url in (
        f"/api/datasets/{dataset_id}/analysis-summary",
        f"/api/datasets/{dataset_id}/analysis-export?format=json",
        f"/api/datasets/{dataset_id}/analysis-export?format=csv",
    ):
        text = micro_client.get(url).text
        assert "standardized_path" not in text, url
        assert ":\\" not in text, url
        assert runtime_dir not in text, url
