"""Task 4 tests: quality gates and explicit warning confirmation."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from geomodeling.platform import PlatformRuntime
from geomodeling.platform.errors import platform_error_handler, PlatformError
from geomodeling.platform.schemas import FieldMapping

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def make_client(tmp_path: Path) -> TestClient:
    from geomodeling.api.routes import cases, datasets
    from geomodeling.platform import settings as platform_settings

    runtime = PlatformRuntime(
        settings=platform_settings.PlatformSettings(data_dir=tmp_path / "runtime")
    )
    runtime.initialize()

    app = FastAPI()
    app.add_exception_handler(PlatformError, platform_error_handler)
    app.include_router(cases.router)
    app.include_router(datasets.router)
    app.state.platform_runtime = runtime
    return TestClient(app)


def create_case(client: TestClient) -> str:
    resp = client.post("/api/cases", json={"name": "质量案例"})
    assert resp.status_code == 201
    return resp.json()["id"]


def upload_text(client: TestClient, case_id: str, text: str, filename: str = "q.csv") -> str:
    resp = client.post(
        f"/api/cases/{case_id}/datasets/uploads",
        files={"file": (filename, io.BytesIO(text.encode("utf-8")), "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def map_2d(client: TestClient, dataset_id: str, x="x", y="y", value="v", kind="local_linear"):
    mapping = {
        "dimension": "2d",
        "x": x,
        "y": y,
        "value": value,
        "value_name": "属性",
        "coordinate_kind": kind,
    }
    resp = client.post(f"/api/datasets/{dataset_id}/mapping", json=mapping)
    assert resp.status_code == 200, resp.text
    return resp.json()


def validate(client: TestClient, dataset_id: str):
    return client.post(f"/api/datasets/{dataset_id}/validate")


def confirm(client: TestClient, dataset_id: str, codes: list[str]):
    return client.post(
        f"/api/datasets/{dataset_id}/quality/confirm-warnings",
        json={"issue_codes": codes},
    )


CSV_GOOD = "x,y,v\n" + "\n".join(f"{i % 5 * 10},{i // 5 * 10},{10 + i}" for i in range(15)) + "\n"


# --------------------------------------------------------------------------
# blockers
# --------------------------------------------------------------------------


def test_blocker_all_values_invalid(tmp_path):
    client = make_client(tmp_path)
    case_id = create_case(client)
    text = "x,y,v\n1,1,abc\n2,2,def\n3,3,ghi\n4,4,jkl\n5,5,mno\n6,6,pqr\n7,7,stu\n8,8,vwx\n9,9,yza\n10,10,bcd\n11,11,efg\n"
    dataset_id = upload_text(client, case_id, text)
    map_2d(client, dataset_id)
    resp = validate(client, dataset_id)
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["status"] == "blocked"
    codes = {c["code"] for c in report["issues"] if c["kind"] == "blocker"}
    assert "MISSING_NUMERIC" in codes

    resp = client.get(f"/api/datasets/{dataset_id}")
    assert resp.json()["status"] == "blocked"


def test_blocker_infinite_value(tmp_path):
    client = make_client(tmp_path)
    case_id = create_case(client)
    text = CSV_GOOD + "12,99,inf\n"
    dataset_id = upload_text(client, case_id, text)
    map_2d(client, dataset_id)
    report = validate(client, dataset_id).json()
    assert report["status"] == "blocked"
    codes = {c["code"] for c in report["issues"] if c["kind"] == "blocker"}
    assert "NON_FINITE" in codes


def test_blocker_nodata_minus_9999(tmp_path):
    client = make_client(tmp_path)
    case_id = create_case(client)
    text = CSV_GOOD + "13,99,-9999\n"
    dataset_id = upload_text(client, case_id, text)
    map_2d(client, dataset_id)
    report = validate(client, dataset_id).json()
    assert report["status"] == "blocked"
    codes = {c["code"] for c in report["issues"] if c["kind"] == "blocker"}
    assert "NODATA_VALUE" in codes


def test_blocker_conflicting_coordinates(tmp_path):
    client = make_client(tmp_path)
    case_id = create_case(client)
    text = CSV_GOOD + "0,0,999\n"
    dataset_id = upload_text(client, case_id, text)  # (0,0) 已有 v=10
    map_2d(client, dataset_id)
    report = validate(client, dataset_id).json()
    assert report["status"] == "blocked"
    codes = {c["code"] for c in report["issues"] if c["kind"] == "blocker"}
    assert "CONFLICTING_COORDINATE" in codes
    conflict = next(c for c in report["issues"] if c["code"] == "CONFLICTING_COORDINATE")
    assert conflict["details"]["conflict_count"] >= 1


def test_blocker_insufficient_valid_points(tmp_path):
    client = make_client(tmp_path)
    case_id = create_case(client)
    text = "x,y,v\n1,1,10\n2,2,20\n3,3,30\n4,4,40\n5,5,50\n"
    dataset_id = upload_text(client, case_id, text)
    map_2d(client, dataset_id)
    report = validate(client, dataset_id).json()
    assert report["status"] == "blocked"
    codes = {c["code"] for c in report["issues"] if c["kind"] == "blocker"}
    assert "INSUFFICIENT_VALID_POINTS" in codes


def test_blocker_degenerate_extent(tmp_path):
    client = make_client(tmp_path)
    case_id = create_case(client)
    text = "x,y,v\n" + "\n".join(f"5,{i},{10 + i}" for i in range(12)) + "\n"
    dataset_id = upload_text(client, case_id, text)
    map_2d(client, dataset_id)
    report = validate(client, dataset_id).json()
    assert report["status"] == "blocked"
    codes = {c["code"] for c in report["issues"] if c["kind"] == "blocker"}
    assert "DEGENERATE_EXTENT" in codes


def test_blocker_geographic_without_projection():
    from geomodeling.platform.quality import evaluate_quality

    mapping = FieldMapping(
        dimension="2d", x="x", y="y", value="v",
        value_name="属性", coordinate_kind="geographic",
    )
    with pytest.raises(PlatformError) as exc:
        evaluate_quality(
            frame=None, mapping=mapping, source_sha256="x", standardized_sha256="y"
        )
    assert exc.value.code == "GEOGRAPHIC_NOT_PROJECTED"


# --------------------------------------------------------------------------
# warnings + confirmation
# --------------------------------------------------------------------------


def test_warning_duplicate_rows_and_exact_confirmation(tmp_path):
    client = make_client(tmp_path)
    case_id = create_case(client)
    text = CSV_GOOD + "0,0,10\n"  # 与首行完全重复
    dataset_id = upload_text(client, case_id, text)
    map_2d(client, dataset_id)
    report = validate(client, dataset_id).json()
    assert report["status"] == "warnings"
    codes = {c["code"] for c in report["issues"] if c["kind"] == "warning"}
    assert "DUPLICATE_ROWS" in codes
    assert report["confirmed"] is False

    # 错误代码集合 → 409
    resp = confirm(client, dataset_id, ["DUPLICATE_ROWS", "EXTRA_CODE"])
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "WARNING_CONFIRMATION_MISMATCH"

    # 精确集合 → 确认
    resp = confirm(client, dataset_id, sorted(codes))
    assert resp.status_code == 200
    confirmed = resp.json()
    assert confirmed["confirmed"] is True
    assert set(confirmed["confirmed_issue_codes"]) == codes

    resp = client.get(f"/api/datasets/{dataset_id}/quality")
    assert resp.json()["confirmed"] is True


def test_warning_extreme_values_mad(tmp_path):
    client = make_client(tmp_path)
    case_id = create_case(client)
    rows = [f"{i % 4 * 10},{i // 4 * 10},{10 + (i % 3)}" for i in range(15)]
    rows.append("50,60,5000")
    text = "x,y,v\n" + "\n".join(rows) + "\n"
    dataset_id = upload_text(client, case_id, text)
    map_2d(client, dataset_id)
    report = validate(client, dataset_id).json()
    assert report["status"] == "warnings"
    codes = {c["code"] for c in report["issues"] if c["kind"] == "warning"}
    assert "EXTREME_VALUES" in codes


def test_warning_sparse_distribution(tmp_path):
    client = make_client(tmp_path)
    case_id = create_case(client)
    text = "x,y,v\n" + "\n".join(f"0,{i},{10 + i}" for i in range(6)) + "\n"
    text += "\n".join(f"10,{i},{20 + i}" for i in range(6)) + "\n"
    dataset_id = upload_text(client, case_id, text)
    map_2d(client, dataset_id)
    report = validate(client, dataset_id).json()
    assert report["status"] == "warnings"
    codes = {c["code"] for c in report["issues"] if c["kind"] == "warning"}
    assert "SPARSE_DISTRIBUTION" in codes


def test_warning_suspicious_magnitude(tmp_path):
    client = make_client(tmp_path)
    case_id = create_case(client)
    text = "x,y,v\n" + "\n".join(f"{i * 2e7},{i * 10},{10 + i}" for i in range(12)) + "\n"
    dataset_id = upload_text(client, case_id, text)
    map_2d(client, dataset_id)
    report = validate(client, dataset_id).json()
    assert report["status"] == "warnings"
    codes = {c["code"] for c in report["issues"] if c["kind"] == "warning"}
    assert "SUSPICIOUS_MAGNITUDE" in codes


def test_warning_high_invalid_ratio(tmp_path):
    client = make_client(tmp_path)
    case_id = create_case(client)
    rows = [f"{i % 5 * 10},{i // 5 * 10},{10 + i}" for i in range(11)]
    rows.append("bad,99,99")
    text = "x,y,v\n" + "\n".join(rows) + "\n"
    dataset_id = upload_text(client, case_id, text)
    map_2d(client, dataset_id)
    report = validate(client, dataset_id).json()
    assert report["status"] == "warnings"
    assert report["invalid_row_count"] == 1
    codes = {c["code"] for c in report["issues"] if c["kind"] == "warning"}
    assert "HIGH_INVALID_RATIO" in codes


# --------------------------------------------------------------------------
# report content & lifecycle
# --------------------------------------------------------------------------


def test_passed_report_content(tmp_path):
    client = make_client(tmp_path)
    case_id = create_case(client)
    dataset_id = upload_text(client, case_id, CSV_GOOD)
    map_2d(client, dataset_id)
    report = validate(client, dataset_id).json()
    assert report["status"] == "passed"
    assert report["confirmed"] is True  # 无警告时无需确认
    assert report["valid_row_count"] == 15
    assert report["invalid_row_count"] == 0
    stats = report["statistics"]
    assert stats["ranges"]["x"] == [0.0, 40.0]
    assert stats["ranges"]["y"] == [0.0, 20.0]
    assert stats["unique_coordinate_count"] == 15
    assert stats["duplicate_count"] == 0
    assert stats["conflict_count"] == 0
    assert len(report["source_sha256"]) == 64
    assert len(report["standardized_sha256"]) == 64
    check_map = {c["code"]: c["passed"] for c in report["checks"]}
    assert all(check_map.values())

    resp = client.get(f"/api/datasets/{dataset_id}")
    assert resp.json()["status"] == "validated"


def test_quality_not_evaluated_yet_is_404(tmp_path):
    client = make_client(tmp_path)
    case_id = create_case(client)
    dataset_id = upload_text(client, case_id, CSV_GOOD)
    map_2d(client, dataset_id)
    resp = client.get(f"/api/datasets/{dataset_id}/quality")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "QUALITY_NOT_EVALUATED"


def test_remap_invalidates_quality_and_confirmation(tmp_path):
    client = make_client(tmp_path)
    case_id = create_case(client)
    text = CSV_GOOD + "0,0,10\n"
    dataset_id = upload_text(client, case_id, text)
    map_2d(client, dataset_id)
    report = validate(client, dataset_id).json()
    codes = {c["code"] for c in report["issues"] if c["kind"] == "warning"}
    assert confirm(client, dataset_id, sorted(codes)).status_code == 200

    # 重新映射（换 value 列含义）后质量报告与确认全部失效
    map_2d(client, dataset_id, value="v")
    resp = client.get(f"/api/datasets/{dataset_id}/quality")
    assert resp.status_code == 404

    # 重新 validate 后需要重新确认
    report = validate(client, dataset_id).json()
    assert report["confirmed"] is False


def test_blocked_dataset_can_be_remapped(tmp_path):
    client = make_client(tmp_path)
    case_id = create_case(client)
    text = "x,y,v\n1,1,10\n2,2,20\n3,3,30\n"
    dataset_id = upload_text(client, case_id, text)
    map_2d(client, dataset_id)
    report = validate(client, dataset_id).json()
    assert report["status"] == "blocked"
    resp = map_2d(client, dataset_id)
    assert resp["status"] == "mapped"
