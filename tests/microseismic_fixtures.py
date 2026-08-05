from pathlib import Path

import yaml

HEADER = "         WL/2(km)          Vx"


def write_dat(path: Path, rows: list[str], trailing_nul: bool = True) -> Path:
    content = "\r\n".join([HEADER, *rows]) + "\r\n"
    data = content.encode("ascii")
    if trailing_nul:
        data += b"\x00"
    path.write_bytes(data)
    return path


def write_fixture_tree(base: Path) -> Path:
    data_dir = base / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    write_dat(data_dir / "W1.dat", ["        0.050000        0.524804", "        0.055556        0.438684", "        0.060000        0.500000"])
    write_dat(data_dir / "W2.dat", ["        0.050000        1.#QNAN0", "        0.055556        0.400000"])
    write_dat(data_dir / "WA.dat", ["        0.100000        1.000000", "        0.200000        2.000000"], trailing_nul=False)
    return data_dir


def write_fixture_config(base: Path, data_dir: Path, **overrides) -> Path:
    expected = {
        "dat_file_count": 3,
        "nul_terminator_count": 2,
        "line_point_counts": {"L1": 2, "L2": 1},
        "source_record_counts": {"L1": 5, "L2": 2},
        "source_record_total": 7,
        "valid_numeric_counts": {"L1": 4, "L2": 2},
        "valid_numeric_total": 6,
        "invalid_numeric_total": 1,
        "special_nan_token": "1.#QNAN0",
        "special_nan_point": "W2",
        "paper_counts": {"L1": 5, "L2": 1, "total": 6},
    }
    expected.update(overrides.pop("expected", {}))
    config = {
        "project": {"name": "GeoModelingPlatform", "version": "0.2a"},
        "source": {
            "data_dir": str(data_dir),
            "interval_workbook": "点间距.xlsx",
            "paper_reference": "fixture-paper.pdf",
            "line_map_image": "fixture-lines.jpg",
            "source_unit": "WL/2(km); Vx km/s",
        },
        "lines": [
            {
                "line_id": "L1",
                "point_start": "W1",
                "point_end": "W2",
                "points": [
                    {"point_id": "W1", "source_file": "W1.dat"},
                    {"point_id": "W2", "source_file": "W2.dat"},
                ],
            },
            {
                "line_id": "L2",
                "point_start": "WA",
                "point_end": "WA",
                "points": [{"point_id": "WA", "source_file": "WA.dat"}],
            },
        ],
        "intervals_m": {"L1": [{"from": "W1", "to": "W2", "distance_m": 100}], "L2": []},
        "excluded_points": [
            {
                "point_id": "W99",
                "line_id": "L1",
                "conflict_interval_m": 350,
                "interval_from": "W2",
                "reason": "fixture conflict-only point",
                "issue_code": "L3_W28_SOURCE_CONFLICT",
            }
        ],
        "local_coordinates": [
            {"point_id": "W1", "x_local_m": 0, "y_local_m": 220},
            {"point_id": "W2", "x_local_m": 100, "y_local_m": 220},
            {"point_id": "WA", "x_local_m": 0, "y_local_m": 0},
        ],
        "derivation": {
            "rule_version": "microseismic_local_3d_v0.2b_confirmed_2026-07-20",
            "adapter_version": "0.5.0",
            "depth_multiplier": 1000.0,
            "z_multiplier": -1.0,
            "vx_unit": "km/s",
            "sigma_threshold": 3.0,
            "sigma_ddof": 1,
            "aggregation_method": "arithmetic_mean_exact_xyz",
            # Fixture-specific contract: the fixture's 6 finite rows yield no
            # 3-sigma rejections and no exact-xyz conflicts. Never copy the
            # real 2006/1925/80/1911 counts into this portable fixture.
            "expected_rejected": 0,
            "expected_accepted": 6,
            "expected_conflict_groups": 0,
            "expected_conflict_rows": 0,
            "expected_modeling_nodes": 6,
            # Fixture-only golden pins, re-pinned in Task 4: sha256 of the
            # canonical UTF-8-BOM/CRLF CSV bytes of the fixture's accepted
            # set (6 rows) and of its empty rejected set (header only).
            "golden": {
                "accepted_sha256": "063a98c5277a2c3ce557e166e30c6652765a207b68059a9eb3cdac14503e0316",
                "rejected_sha256": "2ebb1f496b428d75d713e7e8bfe3dff78749be0155aa8395fa577fb2339e8738",
            },
        },
        "expected": expected,
        "cleaning_conflicts": {
            "outlier_count_claim": 80,
            "rate_claim_percent": 3.59,
            "computed_rate_percent": 3.99,
            "method_a": "linear interpolation",
            "method_b": "nearest 5 point IDW",
        },
        "outputs": {"default_dir": str(base / "out")},
    }
    config_path = base / "microseismic_fixture.yaml"
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    return config_path



# ---------------------------------------------------------------------------
# v0.5 合成 22 文件包（自 test_microseismic_api 迁入；DAT HTTP 流程退出后，
# 导出/工件等服务级测试共用）
# ---------------------------------------------------------------------------

import yaml  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from geomodeling.api.app import create_app  # noqa: E402
from geomodeling.api.deps import ApiSettings, get_settings  # noqa: E402
from geomodeling.microseismic.config import load_microseismic_config  # noqa: E402
from geomodeling.microseismic.service import derive_from_directory  # noqa: E402

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
                "points": [
                    {"point_id": point_id, "source_file": file_name}
                    for point_id, file_name in points
                ],
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
    first, _ = derive_from_directory(
        load_microseismic_config(config_path), data_dir, tmp_path / "calibration-a"
    )
    actual = {check.name: check.actual for check in first.golden.checks}
    assert first.audit.validation.passed, "合成包的审计合同必须在第一遍就通过"
    golden = {
        "accepted_sha256": actual["accepted_sha256"],
        "rejected_sha256": actual["rejected_sha256"],
    }

    config_path = _write_bundle_config(tmp_path, data_dir, golden)
    final, _ = derive_from_directory(
        load_microseismic_config(config_path), data_dir, tmp_path / "calibration-b"
    )
    assert final.validation.passed, "标定后的黄金门禁必须整体通过"
    return config_path, data_dir


def make_app(tmp_path: Path, monkeypatch, config_path: Path):
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


def create_case(client: TestClient, name: str = "微震 API 案例") -> str:
    resp = client.post("/api/cases", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def assert_envelope(payload: dict) -> dict:
    assert set(payload) == {"error"}
    assert set(payload["error"]) == {"code", "message", "details"}
    return payload["error"]
