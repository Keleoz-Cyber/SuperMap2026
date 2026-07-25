"""Task 7: microseismic multipart import API and safe derivation evidence DTO.

The portable 22-file synthetic bundle mirrors the real file-name manifest
(W1-W9.dat / WD12-Vx..WD20-Vx / WD24-Vx..WD27-Vx) but carries its own tiny
row counts (45 source records, 44 finite, 44 unique modeling nodes). Its
golden SHA-256 pair is pinned by a two-pass calibration inside
``build_synthetic_bundle`` so the import gates genuinely pass end to end.

Red-phase note: this module deliberately never imports
``geomodeling.api.routes.microseismic`` — before Task 7 the routes simply do
not exist and every test must fail with HTTP 404 (route missing), not with a
collection ImportError.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from geomodeling.api.app import create_app
from geomodeling.api.deps import ApiSettings, get_settings
from geomodeling.microseismic.config import load_microseismic_config
from geomodeling.microseismic.service import derive_from_directory
from microseismic_fixtures import write_dat
from test_public_dto import assert_no_path_leak

# ---------------------------------------------------------------------------
# Synthetic 22-file bundle (real file-name manifest, portable tiny counts)
# ---------------------------------------------------------------------------

RULE_VERSION = "microseismic_api_synthetic_v0.5"

BUNDLE_LINES: list[tuple[str, list[tuple[str, str]]]] = [
    ("L1", [(f"W{i}", f"W{i}.dat") for i in range(1, 10)]),
    ("L2", [(f"W{i}", f"WD{i}-Vx.dat") for i in range(12, 21)]),
    ("L3", [(f"W{i}", f"WD{i}-Vx.dat") for i in range(24, 28)]),
]
ALL_NAMES: list[str] = [file_name for _, points in BUNDLE_LINES for _, file_name in points]
NUL_FILES = {"W1.dat", "WD24-Vx.dat"}
QNAN_POINT = "W8"

ROW_A = "        0.050000        0.524804"
ROW_B = "        0.055556        0.438684"
ROW_QNAN = "        0.060000        1.#QNAN0"

# 合同计数：每点 2 行，W8 额外一行 1.#QNAN0 → L1=19/L2=18/L3=8，总计 45，
# 有限 44，无效 1；3σ 无剔除（取值紧贴），同坐标无冲突，建模节点 44。
EXPECTED_LAYER_COUNTS = {
    "source_records": 45,
    "finite_records": 44,
    "invalid_records": 1,
    "rejected_3sigma": 0,
    "accepted_modeling": 44,
    "aggregated_nodes": 44,
}
EXPECTED_LINE_COUNTS = {"L1": 19, "L2": 18, "L3": 8}

INTERVALS_M = {
    "L1": [
        {"from": "W1", "to": "W2", "distance_m": 150},
        {"from": "W2", "to": "W3", "distance_m": 100},
        {"from": "W3", "to": "W4", "distance_m": 100},
        {"from": "W4", "to": "W5", "distance_m": 50},
        {"from": "W5", "to": "W6", "distance_m": 50},
        {"from": "W6", "to": "W7", "distance_m": 150},
        {"from": "W7", "to": "W8", "distance_m": 250},
        {"from": "W8", "to": "W9", "distance_m": 300},
    ],
    "L2": [
        {"from": "W12", "to": "W13", "distance_m": 275},
        {"from": "W13", "to": "W14", "distance_m": 275},
        {"from": "W14", "to": "W15", "distance_m": 250},
        {"from": "W15", "to": "W16", "distance_m": 195},
        {"from": "W16", "to": "W17", "distance_m": 110},
        {"from": "W17", "to": "W18", "distance_m": 600},
        {"from": "W18", "to": "W19", "distance_m": 300},
        {"from": "W19", "to": "W20", "distance_m": 300},
    ],
    "L3": [
        {"from": "W24", "to": "W25", "distance_m": 800},
        {"from": "W25", "to": "W26", "distance_m": 320},
        {"from": "W26", "to": "W27", "distance_m": 335},
    ],
}

LOCAL_COORDINATES = [
    {"point_id": "W1", "x_local_m": 400, "y_local_m": 220},
    {"point_id": "W2", "x_local_m": 250, "y_local_m": 220},
    {"point_id": "W3", "x_local_m": 150, "y_local_m": 220},
    {"point_id": "W4", "x_local_m": 50, "y_local_m": 220},
    {"point_id": "W5", "x_local_m": 0, "y_local_m": 220},
    {"point_id": "W6", "x_local_m": -50, "y_local_m": 220},
    {"point_id": "W7", "x_local_m": -200, "y_local_m": 220},
    {"point_id": "W8", "x_local_m": -450, "y_local_m": 220},
    {"point_id": "W9", "x_local_m": -750, "y_local_m": 220},
    {"point_id": "W12", "x_local_m": 0, "y_local_m": -995},
    {"point_id": "W13", "x_local_m": 0, "y_local_m": -720},
    {"point_id": "W14", "x_local_m": 0, "y_local_m": -445},
    {"point_id": "W15", "x_local_m": 0, "y_local_m": -195},
    {"point_id": "W16", "x_local_m": 0, "y_local_m": 0},
    {"point_id": "W17", "x_local_m": 0, "y_local_m": 110},
    {"point_id": "W18", "x_local_m": 0, "y_local_m": 710},
    {"point_id": "W19", "x_local_m": 0, "y_local_m": 1010},
    {"point_id": "W20", "x_local_m": 0, "y_local_m": 1310},
    {"point_id": "W24", "x_local_m": 960, "y_local_m": 0},
    {"point_id": "W25", "x_local_m": 160, "y_local_m": 0},
    {"point_id": "W26", "x_local_m": -160, "y_local_m": 0},
    {"point_id": "W27", "x_local_m": -495, "y_local_m": 0},
]


def _write_bundle_config(base: Path, data_dir: Path, golden: dict[str, str]) -> Path:
    config = {
        "project": {"name": "GeoModelingPlatform", "version": "0.5-api-fixture"},
        "source": {
            "data_dir": str(data_dir),
            "interval_workbook": "点间距.xlsx",
            "paper_reference": "fixture-paper.pdf",
            "line_map_image": "fixture-lines.jpg",
            "source_unit": "WL/2(km); Vx km/s",
        },
        "lines": [
            {
                "line_id": line_id,
                "point_start": points[0][0],
                "point_end": points[-1][0],
                "points": [{"point_id": point_id, "source_file": file_name} for point_id, file_name in points],
            }
            for line_id, points in BUNDLE_LINES
        ],
        "intervals_m": INTERVALS_M,
        "excluded_points": [
            {
                "point_id": "W28",
                "line_id": "L3",
                "conflict_interval_m": 350,
                "interval_from": "W27",
                "reason": "api fixture conflict-only point",
                "issue_code": "L3_W28_SOURCE_CONFLICT",
            }
        ],
        "local_coordinates": LOCAL_COORDINATES,
        "derivation": {
            "rule_version": RULE_VERSION,
            "adapter_version": "0.5.0",
            "depth_multiplier": 1000.0,
            "z_multiplier": -1.0,
            "vx_unit": "km/s",
            "sigma_threshold": 3.0,
            "sigma_ddof": 1,
            "aggregation_method": "arithmetic_mean_exact_xyz",
            "expected_rejected": 0,
            "expected_accepted": 44,
            "expected_conflict_groups": 0,
            "expected_conflict_rows": 0,
            "expected_modeling_nodes": 44,
            "golden": golden,
        },
        "expected": {
            "dat_file_count": 22,
            "nul_terminator_count": 2,
            "line_point_counts": {"L1": 9, "L2": 9, "L3": 4},
            "source_record_counts": {"L1": 19, "L2": 18, "L3": 8},
            "source_record_total": 45,
            "valid_numeric_counts": {"L1": 18, "L2": 18, "L3": 8},
            "valid_numeric_total": 44,
            "invalid_numeric_total": 1,
            "special_nan_token": "1.#QNAN0",
            "special_nan_point": "W8",
            "paper_counts": {"L1": 19, "L2": 18, "L3": 8, "total": 45},
        },
        "cleaning_conflicts": {
            "outlier_count_claim": 80,
            "rate_claim_percent": 3.59,
            "computed_rate_percent": 3.99,
            "method_a": "linear interpolation",
            "method_b": "nearest 5 point IDW",
        },
        "outputs": {"default_dir": str(base / "out")},
    }
    config_path = base / "microseismic_api_fixture.yaml"
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    return config_path


def build_synthetic_bundle(tmp_path: Path) -> tuple[Path, Path]:
    """Write the 22-file bundle and calibrate its golden hashes (two passes)."""

    data_dir = tmp_path / "bundle"
    data_dir.mkdir(parents=True)
    for _, points in BUNDLE_LINES:
        for point_id, file_name in points:
            rows = [ROW_A, ROW_B]
            if point_id == QNAN_POINT:
                rows = [ROW_A, ROW_QNAN, ROW_B]
            write_dat(data_dir / file_name, rows, trailing_nul=file_name in NUL_FILES)

    placeholder = {"accepted_sha256": "0" * 64, "rejected_sha256": "0" * 64}
    config_path = _write_bundle_config(tmp_path, data_dir, placeholder)
    first, _ = derive_from_directory(load_microseismic_config(config_path), data_dir, tmp_path / "calibration-a")
    actual = {check.name: check.actual for check in first.golden.checks}
    assert first.audit.validation.passed, "合成包的审计合同必须在第一遍就通过"
    golden = {"accepted_sha256": actual["accepted_sha256"], "rejected_sha256": actual["rejected_sha256"]}

    config_path = _write_bundle_config(tmp_path, data_dir, golden)
    final, _ = derive_from_directory(load_microseismic_config(config_path), data_dir, tmp_path / "calibration-b")
    assert final.validation.passed, "标定后的黄金门禁必须整体通过"
    return config_path, data_dir


def make_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config_path: Path):
    """Full app with hermetic data dir and the synthetic microseismic config."""

    monkeypatch.setenv("GEOMODELING_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GEOMODELING_MICROSEISMIC_CONFIG", str(config_path))
    settings = ApiSettings(
        config_path=Path("config/default.yaml"),
        metrics_json=None,
        evidence_dir=tmp_path / "evidence",
        frontend_dist=None,
        voxel_cache_dir=None,
    )
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    return app


def multipart(data_dir: Path, entries: list[tuple[str, str | None]]) -> list[tuple[str, tuple[str, bytes, str]]]:
    """Build the ``files=[...]`` payload; ``client_name=None`` uses the DAT name."""

    parts = []
    for file_name, client_name in entries:
        parts.append(("files", (client_name or file_name, (data_dir / file_name).read_bytes(), "application/octet-stream")))
    return parts


def all_parts(data_dir: Path) -> list[tuple[str, tuple[str, bytes, str]]]:
    return multipart(data_dir, [(name, None) for name in ALL_NAMES])


def create_case(client: TestClient, name: str = "微震 API 案例") -> str:
    resp = client.post("/api/cases", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def import_bundle(client: TestClient, case_id: str, data_dir: Path) -> dict:
    resp = client.post(f"/api/cases/{case_id}/microseismic-imports", files=all_parts(data_dir))
    assert resp.status_code == 201, resp.text
    return resp.json()


def assert_envelope(payload: dict) -> dict:
    assert set(payload) == {"error"}
    assert set(payload["error"]) == {"code", "message", "details"}
    return payload["error"]


# ---------------------------------------------------------------------------
# Step 1: API contract
# ---------------------------------------------------------------------------


def test_import_bundle_returns_mapped_dataset_with_derivation_summary(tmp_path, monkeypatch):
    config_path, data_dir = build_synthetic_bundle(tmp_path)
    app = make_app(tmp_path, monkeypatch, config_path)
    with TestClient(app) as client:
        case_id = create_case(client)
        resp = client.post(f"/api/cases/{case_id}/microseismic-imports", files=all_parts(data_dir))
        assert resp.status_code == 201, resp.text
        body = resp.json()

        assert_no_path_leak(body, "$.import")
        assert body["case_id"] == case_id
        assert body["version"] == 1
        assert body["status"] == "mapped"
        assert isinstance(body["id"], str) and body["id"]

        profile = body["profile"]
        assert profile["source_kind"] == "microseismic_dat_bundle"
        assert profile["rule_version"] == RULE_VERSION
        assert profile["adapter_version"] == "0.5.0"
        assert profile["aggregation_method"] == "arithmetic_mean_exact_xyz"
        assert profile["mapping"]["value"] == "VX_KM_S"
        assert profile["mapping"]["dimension"] == "3d"
        assert profile["layer_counts"] == EXPECTED_LAYER_COUNTS
        assert profile["golden"]["passed"] is True
        assert all(check["passed"] for check in profile["golden"]["checks"])
        assert profile["aggregation"]["conflict_group_count"] == 0
        assert profile["aggregation"]["conflict_row_count"] == 0
        assert profile["aggregation"]["collapsed_row_count"] == 0
        assert [entry["file_name"] for entry in profile["source_files"]] == ALL_NAMES
        assert all(len(entry["sha256"]) == 64 for entry in profile["source_files"])

        # 数据集挂在案例下且可见（身份一致、无路径键）
        listing = client.get(f"/api/cases/{case_id}/datasets")
        assert listing.status_code == 200
        assert [item["id"] for item in listing.json()["datasets"]] == [body["id"]]
        assert_no_path_leak(listing.json(), "$.datasets")

        # 上传暂存与派生暂存均不得残留
        staging_root = tmp_path / "data" / "staging" / "microseismic"
        assert not staging_root.exists() or list(staging_root.iterdir()) == []


def test_get_derivation_returns_case_ownership_golden_checks_and_aggregation(tmp_path, monkeypatch):
    config_path, data_dir = build_synthetic_bundle(tmp_path)
    app = make_app(tmp_path, monkeypatch, config_path)
    with TestClient(app) as client:
        case_id = create_case(client)
        dataset_id = import_bundle(client, case_id, data_dir)["id"]

        resp = client.get(f"/api/datasets/{dataset_id}/derivation")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert_no_path_leak(body, "$.derivation")
        assert body["dataset_id"] == dataset_id
        assert body["case_id"] == case_id
        assert body["source_kind"] == "microseismic_dat_bundle"
        assert body["status"] == "mapped"
        assert body["rule_version"] == RULE_VERSION
        assert body["adapter_version"] == "0.5.0"
        assert body["aggregation_method"] == "arithmetic_mean_exact_xyz"

        assert body["layer_counts"] == EXPECTED_LAYER_COUNTS
        assert body["line_counts"] == EXPECTED_LINE_COUNTS

        golden = body["golden"]
        assert golden["passed"] is True
        check_names = {check["name"] for check in golden["checks"]}
        assert {
            "accepted_count",
            "rejected_count",
            "accepted_sha256",
            "rejected_sha256",
            "conflict_group_count",
            "conflict_row_count",
            "modeling_node_count",
        } <= check_names
        assert all(check["passed"] for check in golden["checks"])
        accepted = next(check for check in golden["checks"] if check["name"] == "accepted_count")
        assert accepted["expected"] == 44
        assert accepted["actual"] == 44

        aggregation = body["aggregation"]
        assert aggregation["conflict_group_count"] == 0
        assert aggregation["conflict_row_count"] == 0
        assert aggregation["collapsed_row_count"] == 0
        assert aggregation["max_value_range"] == 0.0

        coordinates = body["coordinates"]
        assert coordinates["vx_unit"] == "km/s"
        assert coordinates["coord_type"]
        assert coordinates["depth_rule"]
        assert coordinates["z_rule"]

        three_sigma = body["three_sigma"]
        assert three_sigma["threshold"] == 3.0
        assert three_sigma["ddof"] == 1

        assert body["validation_passed"] is True
        assert body["downstream_gates"] == {
            "geometry_blocked": False,
            "cleaning_blocked": False,
            "interpolation_blocked": False,
        }

        # 来源清单摘要：22 个文件的身份（文件名/哈希/测点/测线/行数），无路径
        source_files = body["source_files"]
        assert [entry["file_name"] for entry in source_files] == ALL_NAMES
        w8 = next(entry for entry in source_files if entry["file_name"] == "W8.dat")
        assert w8["point_id"] == "W8"
        assert w8["line_id"] == "L1"
        assert w8["source_record_count"] == 3

        # 可下载工件身份是逻辑名，不是路径
        artifacts = body["artifacts"]
        assert artifacts["accepted_modeling"]["file"] == "accepted_modeling_44.csv"
        assert artifacts["accepted_modeling"]["rows"] == 44
        assert artifacts["aggregated_nodes"]["file"] == "aggregated_nodes_44.csv"
        for artifact in artifacts.values():
            assert "/" not in artifact["file"] and "\\" not in artifact["file"]
            assert len(artifact["sha256"]) == 64


def test_failed_derivation_returns_envelope_with_public_diagnostics(tmp_path, monkeypatch):
    config_path, data_dir = build_synthetic_bundle(tmp_path)
    # 破坏 W9.dat：多一行 → 分线/总计数与合同不符 → 派生门禁阻断
    write_dat(data_dir / "W9.dat", [ROW_A, ROW_B, "        0.060000        0.500000"])
    app = make_app(tmp_path, monkeypatch, config_path)
    with TestClient(app) as client:
        case_id = create_case(client)
        resp = client.post(f"/api/cases/{case_id}/microseismic-imports", files=all_parts(data_dir))
        assert resp.status_code == 422, resp.text
        error = assert_envelope(resp.json())
        assert error["code"] == "MICROSEISMIC_DERIVATION_FAILED"
        failed = error["details"]["failed_checks"]
        assert failed, "必须给出失败检查清单"
        assert all(set(check) == {"name", "evidence"} for check in failed)
        assert any("source_record_counts_per_line" == check["name"] for check in failed)
        # 诊断只含检查名与 expected/actual，不含本机路径
        assert_no_path_leak(resp.json(), "$.failed_derivation")
        assert str(tmp_path) not in json.dumps(resp.json(), ensure_ascii=False)

        # 阻断的导入不得残留数据集
        listing = client.get(f"/api/cases/{case_id}/datasets")
        assert listing.status_code == 200
        assert listing.json()["datasets"] == []


# ---------------------------------------------------------------------------
# Step 2: hostile inputs
# ---------------------------------------------------------------------------


def test_duplicate_basename_with_different_client_paths_rejected(tmp_path, monkeypatch):
    config_path, data_dir = build_synthetic_bundle(tmp_path)
    app = make_app(tmp_path, monkeypatch, config_path)
    entries = [(name, None) for name in ALL_NAMES if name != "W1.dat"]
    entries.append(("W1.dat", "data/W1.dat"))
    entries.append(("W1.dat", "other\\W1.dat"))
    with TestClient(app) as client:
        case_id = create_case(client)
        resp = client.post(f"/api/cases/{case_id}/microseismic-imports", files=multipart(data_dir, entries))
        assert resp.status_code == 422, resp.text
        error = assert_envelope(resp.json())
        assert error["code"] == "MICROSEISMIC_BUNDLE_INVALID"
        assert "W1.dat" in json.dumps(error["details"], ensure_ascii=False)
        assert_no_path_leak(resp.json(), "$.duplicate")
        # 暂存目录必须清理
        staging_root = tmp_path / "data" / "staging" / "microseismic"
        assert not staging_root.exists() or list(staging_root.iterdir()) == []


def test_missing_dat_rejected_with_file_level_detail(tmp_path, monkeypatch):
    config_path, data_dir = build_synthetic_bundle(tmp_path)
    app = make_app(tmp_path, monkeypatch, config_path)
    entries = [(name, None) for name in ALL_NAMES if name != "W9.dat"]
    with TestClient(app) as client:
        case_id = create_case(client)
        resp = client.post(f"/api/cases/{case_id}/microseismic-imports", files=multipart(data_dir, entries))
        assert resp.status_code == 422, resp.text
        error = assert_envelope(resp.json())
        assert error["code"] == "MICROSEISMIC_BUNDLE_INVALID"
        assert error["details"]["missing"] == ["W9.dat"]
        assert error["details"]["expected_count"] == 22
        assert error["details"]["actual_count"] == 21


def test_unknown_dat_rejected_with_file_level_detail(tmp_path, monkeypatch):
    config_path, data_dir = build_synthetic_bundle(tmp_path)
    write_dat(data_dir / "WX.dat", [ROW_A])
    app = make_app(tmp_path, monkeypatch, config_path)
    entries = [(name, None) for name in ALL_NAMES] + [("WX.dat", None)]
    with TestClient(app) as client:
        case_id = create_case(client)
        resp = client.post(f"/api/cases/{case_id}/microseismic-imports", files=multipart(data_dir, entries))
        assert resp.status_code == 422, resp.text
        error = assert_envelope(resp.json())
        assert error["code"] == "MICROSEISMIC_BUNDLE_INVALID"
        assert error["details"]["unknown"] == ["WX.dat"]


def test_traversal_filename_rejected(tmp_path, monkeypatch):
    config_path, data_dir = build_synthetic_bundle(tmp_path)
    app = make_app(tmp_path, monkeypatch, config_path)
    entries = [(name, "../W1.dat" if name == "W1.dat" else None) for name in ALL_NAMES]
    with TestClient(app) as client:
        case_id = create_case(client)
        resp = client.post(f"/api/cases/{case_id}/microseismic-imports", files=multipart(data_dir, entries))
        assert resp.status_code == 422, resp.text
        error = assert_envelope(resp.json())
        assert error["code"] == "MICROSEISMIC_BUNDLE_INVALID"
        # 遍历被拒绝，且响应不回显任何本机绝对路径
        assert_no_path_leak(resp.json(), "$.traversal")
        staging_root = tmp_path / "data" / "staging" / "microseismic"
        assert not staging_root.exists() or list(staging_root.iterdir()) == []


def test_per_file_size_limit_enforced(tmp_path, monkeypatch):
    config_path, data_dir = build_synthetic_bundle(tmp_path)
    data_dir.joinpath("W5.dat").write_bytes(b"A" * (1024 * 1024 + 1))
    app = make_app(tmp_path, monkeypatch, config_path)
    with TestClient(app) as client:
        case_id = create_case(client)
        resp = client.post(f"/api/cases/{case_id}/microseismic-imports", files=all_parts(data_dir))
        assert resp.status_code == 413, resp.text
        error = assert_envelope(resp.json())
        assert error["code"] == "MICROSEISMIC_UPLOAD_TOO_LARGE"
        assert error["details"]["file_name"] == "W5.dat"
        assert error["details"]["max_file_bytes"] == 1024 * 1024
        assert_no_path_leak(resp.json(), "$.per_file_limit")


def test_total_size_limit_enforced(tmp_path, monkeypatch):
    config_path, data_dir = build_synthetic_bundle(tmp_path)
    # 11 个文件各 1 MiB（单文件未超限）→ 总计 > 10 MiB
    for name in ALL_NAMES[:11]:
        data_dir.joinpath(name).write_bytes(b"B" * (1024 * 1024))
    app = make_app(tmp_path, monkeypatch, config_path)
    with TestClient(app) as client:
        case_id = create_case(client)
        resp = client.post(f"/api/cases/{case_id}/microseismic-imports", files=all_parts(data_dir))
        assert resp.status_code == 413, resp.text
        error = assert_envelope(resp.json())
        assert error["code"] == "MICROSEISMIC_UPLOAD_TOO_LARGE"
        assert error["details"]["max_total_bytes"] == 10 * 1024 * 1024
        assert "file_name" not in error["details"]


def test_import_into_unknown_case_is_envelope_404(tmp_path, monkeypatch):
    config_path, data_dir = build_synthetic_bundle(tmp_path)
    app = make_app(tmp_path, monkeypatch, config_path)
    with TestClient(app) as client:
        resp = client.post(
            "/api/cases/00000000-0000-0000-0000-000000000000/microseismic-imports",
            files=all_parts(data_dir),
        )
        assert resp.status_code == 404, resp.text
        error = assert_envelope(resp.json())
        assert error["code"] == "CASE_NOT_FOUND"


def test_derivation_for_dataset_of_other_case_kind_is_409(tmp_path, monkeypatch):
    """数据集属于某个案例但不是微震导入（普通 CSV 上传）→ 409，不是 200。"""

    from test_experiment_api import CSV_2D

    config_path, _ = build_synthetic_bundle(tmp_path)
    app = make_app(tmp_path, monkeypatch, config_path)
    with TestClient(app) as client:
        case_id = create_case(client, "普通上传案例")
        upload = client.post(
            f"/api/cases/{case_id}/datasets/uploads",
            files={"file": ("data.csv", io.BytesIO(CSV_2D.encode()), "application/octet-stream")},
        )
        assert upload.status_code == 201, upload.text
        dataset_id = upload.json()["id"]

        resp = client.get(f"/api/datasets/{dataset_id}/derivation")
        assert resp.status_code == 409, resp.text
        error = assert_envelope(resp.json())
        assert error["code"] == "DATASET_NOT_MICROSEISMIC"
        assert_no_path_leak(resp.json(), "$.not_microseismic")


def test_derivation_for_unknown_dataset_is_envelope_404(tmp_path, monkeypatch):
    config_path, _ = build_synthetic_bundle(tmp_path)
    app = make_app(tmp_path, monkeypatch, config_path)
    with TestClient(app) as client:
        resp = client.get("/api/datasets/00000000-0000-0000-0000-000000000000/derivation")
        assert resp.status_code == 404, resp.text
        error = assert_envelope(resp.json())
        assert error["code"] == "DATASET_NOT_FOUND"


def test_nested_absolute_paths_scrubbed_from_derivation_response(tmp_path, monkeypatch):
    config_path, data_dir = build_synthetic_bundle(tmp_path)
    app = make_app(tmp_path, monkeypatch, config_path)
    with TestClient(app) as client:
        case_id = create_case(client)
        dataset_id = import_bundle(client, case_id, data_dir)["id"]

        # 在内部报告里植入嵌套的绝对路径值与路径键，模拟未来键扩张
        report_path = (
            tmp_path
            / "data"
            / "datasets"
            / case_id
            / dataset_id
            / "derived"
            / "derivation_report.json"
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["coordinates"]["evidence_note"] = "D:\\secret\\bundle\\W1.dat"
        report["source_path"] = str(tmp_path / "data" / "datasets")
        report["golden"]["checks"][0]["debug"] = {"grid_path": "/var/lib/internal/grid.npz"}
        report["artifacts"]["accepted_modeling"]["local_copy"] = "C:/cache/accepted.csv"
        report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

        resp = client.get(f"/api/datasets/{dataset_id}/derivation")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert_no_path_leak(body, "$.scrubbed_derivation")
        dumped = json.dumps(body, ensure_ascii=False)
        assert "D:\\secret" not in dumped
        assert "/var/lib/internal" not in dumped
        assert "C:/cache" not in dumped
        assert str(tmp_path) not in dumped
        # 白名单字段仍然完整
        assert body["layer_counts"] == EXPECTED_LAYER_COUNTS
        assert body["golden"]["passed"] is True
