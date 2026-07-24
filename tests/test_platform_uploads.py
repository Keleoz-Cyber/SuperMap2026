"""Task 3 tests: secure CSV/XLSX upload, inspection, and field mapping."""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from geomodeling.platform import PlatformRuntime
from geomodeling.platform.errors import platform_error_handler, PlatformError

FIXTURE_DIR = Path(__file__).parent / "fixtures"

UPLOAD = "sample.csv"


def make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch | None = None) -> TestClient:
    """Test app with only the Task 3 routers and a tmp runtime (app.py 未动）。"""

    from geomodeling.api.routes import cases, datasets
    from geomodeling.platform import settings as platform_settings

    settings = platform_settings.PlatformSettings(
        data_dir=tmp_path / "runtime",
        max_upload_bytes=platform_settings.DEFAULT_MAX_UPLOAD_BYTES,
        max_upload_rows=platform_settings.DEFAULT_MAX_UPLOAD_ROWS,
    )
    runtime = PlatformRuntime(settings=settings)
    runtime.initialize()

    app = FastAPI()
    app.add_exception_handler(PlatformError, platform_error_handler)
    app.include_router(cases.router)
    app.include_router(datasets.router)

    @app.middleware("http")
    async def _inject_runtime(request, call_next):
        request.app.state.platform_runtime = runtime
        return await call_next(request)

    app.state.platform_runtime = runtime
    return TestClient(app)


def create_case(client: TestClient, name: str = "测试案例") -> str:
    resp = client.post("/api/cases", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def upload(client: TestClient, case_id: str, path: Path, filename: str = "sample.csv"):
    with path.open("rb") as fh:
        return client.post(
            f"/api/cases/{case_id}/datasets/uploads",
            files={"file": (filename, fh, "application/octet-stream")},
        )


def upload_bytes(client: TestClient, case_id: str, payload: bytes, filename: str):
    return client.post(
        f"/api/cases/{case_id}/datasets/uploads",
        files={"file": (filename, io.BytesIO(payload), "application/octet-stream")},
    )


def make_xlsx(sheets: dict[str, list[list]]) -> bytes:
    from openpyxl import Workbook

    book = Workbook()
    first = True
    for name, rows in sheets.items():
        sheet = book.active if first else book.create_sheet()
        sheet.title = name
        for row in rows:
            sheet.append(row)
        first = False
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


XLSX_ROWS = [
    ["id", "x", "y", "rho"],
    ["A", 1.0, 2.0, 10.0],
    ["B", 3.0, 4.0, 20.0],
    ["C", 5.0, 6.0, 30.0],
]


# --------------------------------------------------------------------------
# happy paths
# --------------------------------------------------------------------------


def test_csv_2d_full_sequence(tmp_path):
    client = make_client(tmp_path)
    case_id = create_case(client)

    resp = upload(client, case_id, FIXTURE_DIR / "platform_2d.csv")
    assert resp.status_code == 201, resp.text
    dataset = resp.json()
    dataset_id = dataset["id"]
    assert dataset["status"] == "uploaded"
    assert dataset["profile"]["original_filename"] == "sample.csv"
    assert dataset["profile"]["suffix"] == "csv"
    assert len(dataset["profile"]["source_sha256"]) == 64

    resp = client.get(f"/api/datasets/{dataset_id}/inspection")
    assert resp.status_code == 200, resp.text
    inspection = resp.json()
    assert inspection["row_count"] == 12
    assert {c["name"] for c in inspection["columns"]} == {"station", "easting", "northing", "rho"}
    types = {c["name"]: c["inferred_type"] for c in inspection["columns"]}
    assert types["station"] == "text"
    assert types["easting"] == "numeric"
    assert len(inspection["preview_rows"]) <= 20
    assert inspection["limits"]["max_upload_rows"] == 500_000
    assert inspection["limits"]["max_upload_bytes"] == 50 * 1024 * 1024
    assert inspection["candidate_mapping"]["x"] == "easting"
    assert inspection["candidate_mapping"]["y"] == "northing"
    assert inspection["candidate_mapping"]["value"] == "rho"

    mapping = {
        "dimension": "2d",
        "x": "easting",
        "y": "northing",
        "value": "rho",
        "value_name": "视电阻率",
        "value_unit": "待确认",
        "coordinate_kind": "local_linear",
    }
    resp = client.post(f"/api/datasets/{dataset_id}/mapping", json=mapping)
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["status"] == "mapped"

    profile = result["profile"]
    assert profile["row_count"] == 12
    assert profile["valid_row_count"] == 12
    assert profile["invalid_row_count"] == 0
    assert profile["dimension"] == "2d"
    assert profile["mapping"]["x"] == "easting"

    parquet_path = Path(result["profile"]["standardized_path"])
    frame = pd.read_parquet(parquet_path)
    assert list(frame.columns) == ["source_row", "x", "y", "z", "value", "is_numeric_valid"]
    assert len(frame) == 12
    assert frame["z"].isna().all()
    assert frame["is_numeric_valid"].all()
    assert frame["source_row"].tolist() == list(range(1, 13))


def test_csv_3d_full_sequence(tmp_path):
    client = make_client(tmp_path)
    case_id = create_case(client)
    resp = upload(client, case_id, FIXTURE_DIR / "platform_3d.csv")
    assert resp.status_code == 201, resp.text
    dataset_id = resp.json()["id"]

    mapping = {
        "dimension": "3d",
        "x": "x",
        "y": "y",
        "z": "depth",
        "value": "vx",
        "value_name": "速度",
        "value_unit": "km/s",
        "coordinate_kind": "local_linear",
    }
    resp = client.post(f"/api/datasets/{dataset_id}/mapping", json=mapping)
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["status"] == "mapped"

    frame = pd.read_parquet(Path(result["profile"]["standardized_path"]))
    assert len(frame) == 24
    assert frame["z"].notna().all()
    assert frame["z"].min() == -40.0
    assert frame["is_numeric_valid"].all()


def test_xlsx_single_sheet_full_sequence(tmp_path):
    client = make_client(tmp_path)
    case_id = create_case(client)
    payload = make_xlsx({"数据": XLSX_ROWS})
    resp = upload_bytes(client, case_id, payload, "表.xlsx")
    assert resp.status_code == 201, resp.text
    dataset_id = resp.json()["id"]

    resp = client.get(f"/api/datasets/{dataset_id}/inspection")
    assert resp.status_code == 200, resp.text
    inspection = resp.json()
    assert inspection["row_count"] == 3
    assert {c["name"] for c in inspection["columns"]} == {"id", "x", "y", "rho"}

    mapping = {
        "dimension": "2d",
        "x": "x",
        "y": "y",
        "value": "rho",
        "value_name": "电阻率",
        "coordinate_kind": "local_linear",
    }
    resp = client.post(f"/api/datasets/{dataset_id}/mapping", json=mapping)
    assert resp.status_code == 200, resp.text
    frame = pd.read_parquet(Path(resp.json()["profile"]["standardized_path"]))
    assert len(frame) == 3
    assert frame["value"].tolist() == [10.0, 20.0, 30.0]


def test_invalid_rows_are_preserved_with_flags(tmp_path):
    client = make_client(tmp_path)
    case_id = create_case(client)
    resp = upload(client, case_id, FIXTURE_DIR / "platform_invalid.csv")
    assert resp.status_code == 201, resp.text
    dataset_id = resp.json()["id"]

    mapping = {
        "dimension": "3d",
        "x": "x",
        "y": "y",
        "z": "z",
        "value": "grade",
        "value_name": "品位",
        "coordinate_kind": "local_linear",
    }
    resp = client.post(f"/api/datasets/{dataset_id}/mapping", json=mapping)
    assert resp.status_code == 200, resp.text
    profile = resp.json()["profile"]
    assert profile["row_count"] == 8
    assert profile["valid_row_count"] == 4
    assert profile["invalid_row_count"] == 4

    frame = pd.read_parquet(Path(profile["standardized_path"]))
    # 无效行不被丢弃，逐行标记
    assert len(frame) == 8
    invalid_rows = frame.loc[~frame["is_numeric_valid"], "source_row"].tolist()
    assert invalid_rows == [2, 3, 5, 7]


# --------------------------------------------------------------------------
# rejections
# --------------------------------------------------------------------------


def test_unsupported_extension_rejected(tmp_path):
    client = make_client(tmp_path)
    case_id = create_case(client)
    resp = upload(client, case_id, FIXTURE_DIR / "platform_2d.csv", filename="data.txt")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "UPLOAD_UNSUPPORTED_FORMAT"


def test_zip_and_macro_workbook_rejected(tmp_path):
    client = make_client(tmp_path)
    case_id = create_case(client)
    resp = upload(client, case_id, FIXTURE_DIR / "platform_2d.csv", filename="data.zip")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "UPLOAD_UNSUPPORTED_FORMAT"
    resp = upload(client, case_id, FIXTURE_DIR / "platform_2d.csv", filename="data.xlsm")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "UPLOAD_UNSUPPORTED_FORMAT"


def test_oversize_upload_rejected(tmp_path, monkeypatch):
    from geomodeling.platform import settings as platform_settings

    monkeypatch.setattr(platform_settings, "DEFAULT_MAX_UPLOAD_BYTES", 64)
    client = make_client(tmp_path)
    case_id = create_case(client)
    resp = upload(client, case_id, FIXTURE_DIR / "platform_2d.csv")
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "UPLOAD_TOO_LARGE"


def test_too_many_rows_rejected_at_inspection(tmp_path, monkeypatch):
    from geomodeling.platform import settings as platform_settings

    monkeypatch.setattr(platform_settings, "DEFAULT_MAX_UPLOAD_ROWS", 5)
    client = make_client(tmp_path)
    case_id = create_case(client)
    resp = upload(client, case_id, FIXTURE_DIR / "platform_2d.csv")
    assert resp.status_code == 201, resp.text
    dataset_id = resp.json()["id"]
    resp = client.get(f"/api/datasets/{dataset_id}/inspection")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "DATASET_TOO_MANY_ROWS"


def test_multisheet_without_selection_rejected(tmp_path):
    client = make_client(tmp_path)
    case_id = create_case(client)
    payload = make_xlsx({"第一表": XLSX_ROWS, "第二表": XLSX_ROWS})
    resp = upload_bytes(client, case_id, payload, "多表.xlsx")
    assert resp.status_code == 201, resp.text
    dataset_id = resp.json()["id"]

    resp = client.get(f"/api/datasets/{dataset_id}/inspection")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "SHEET_SELECTION_REQUIRED"

    resp = client.get(f"/api/datasets/{dataset_id}/inspection?sheet=第二表")
    assert resp.status_code == 200, resp.text
    assert resp.json()["sheet"] == "第二表"


def test_path_like_filename_rejected(tmp_path):
    client = make_client(tmp_path)
    case_id = create_case(client)
    for bad in ("../evil.csv", "a/b.csv", "..\\evil.csv", "a\\b.csv"):
        resp = upload(client, case_id, FIXTURE_DIR / "platform_2d.csv", filename=bad)
        assert resp.status_code == 400, bad
        assert resp.json()["error"]["code"] == "UPLOAD_FILENAME_UNSAFE"


def test_duplicate_field_selection_rejected(tmp_path):
    client = make_client(tmp_path)
    case_id = create_case(client)
    resp = upload(client, case_id, FIXTURE_DIR / "platform_2d.csv")
    dataset_id = resp.json()["id"]
    mapping = {
        "dimension": "2d",
        "x": "easting",
        "y": "easting",
        "value": "rho",
        "value_name": "电阻率",
        "coordinate_kind": "local_linear",
    }
    resp = client.post(f"/api/datasets/{dataset_id}/mapping", json=mapping)
    assert resp.status_code == 422


def test_geographic_without_projection_rejected(tmp_path):
    client = make_client(tmp_path)
    case_id = create_case(client)
    resp = upload(client, case_id, FIXTURE_DIR / "platform_2d.csv")
    dataset_id = resp.json()["id"]
    mapping = {
        "dimension": "2d",
        "x": "easting",
        "y": "northing",
        "value": "rho",
        "value_name": "电阻率",
        "coordinate_kind": "geographic",
    }
    resp = client.post(f"/api/datasets/{dataset_id}/mapping", json=mapping)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "GEOGRAPHIC_NOT_PROJECTED"


def test_mapping_missing_column_rejected(tmp_path):
    client = make_client(tmp_path)
    case_id = create_case(client)
    resp = upload(client, case_id, FIXTURE_DIR / "platform_2d.csv")
    dataset_id = resp.json()["id"]
    mapping = {
        "dimension": "2d",
        "x": "不存在列",
        "y": "northing",
        "value": "rho",
        "value_name": "电阻率",
        "coordinate_kind": "local_linear",
    }
    resp = client.post(f"/api/datasets/{dataset_id}/mapping", json=mapping)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "MAPPING_COLUMN_NOT_FOUND"


def test_upload_to_missing_case_is_404(tmp_path):
    client = make_client(tmp_path)
    resp = client.post(
        "/api/cases/不存在的案例/datasets/uploads",
        files={"file": ("sample.csv", io.BytesIO(b"a,b\n1,2\n"), "application/octet-stream")},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "CASE_NOT_FOUND"


def test_inspection_and_mapping_require_existing_dataset(tmp_path):
    client = make_client(tmp_path)
    resp = client.get("/api/datasets/不存在/inspection")
    assert resp.status_code == 404
    resp = client.post("/api/datasets/不存在/mapping", json={})
    assert resp.status_code in (404, 422)
