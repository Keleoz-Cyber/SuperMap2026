"""Task 13 backend tests: standardized source points for measured-point overlay."""

from __future__ import annotations

from pathlib import Path

from test_experiment_api import CSV_2D, make_client, prepare_dataset

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_dataset_points_serves_standardized_coordinates(tmp_path):
    client, _ = make_client(tmp_path)
    _, dataset_id = prepare_dataset(client)  # CSV_2D: 24 行 x,y,v

    resp = client.get(f"/api/datasets/{dataset_id}/points")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 24
    assert body["served"] == 24
    assert len(body["x"]) == 24
    assert len(body["y"]) == 24
    assert body["z"] is None  # 2D 数据集
    assert len(body["values"]) == 24
    assert body["value_range"][0] <= body["value_range"][1]
    assert body["dimension"] == "2d"

    decimated = client.get(f"/api/datasets/{dataset_id}/points?decimate=2")
    assert decimated.status_code == 200
    assert decimated.json()["served"] == 12
    assert decimated.json()["count"] == 24


def test_dataset_points_unknown_dataset_is_404(tmp_path):
    client, _ = make_client(tmp_path)
    resp = client.get("/api/datasets/00000000-0000-0000-0000-000000000000/points")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "DATASET_NOT_FOUND"


def test_dataset_points_requires_mapping(tmp_path):
    """未映射（无标准化工件）的数据集返回明确诊断而非 500。"""
    import io

    client, _ = make_client(tmp_path)
    case_id = client.post("/api/cases", json={"name": "未映射案例"}).json()["id"]
    upload = client.post(
        f"/api/cases/{case_id}/datasets/uploads",
        files={"file": ("data.csv", io.BytesIO(CSV_2D.encode()), "application/octet-stream")},
    )
    dataset_id = upload.json()["id"]
    resp = client.get(f"/api/datasets/{dataset_id}/points")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "DATASET_NOT_MAPPED"
