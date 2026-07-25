"""Merge-blocker 1: public responses must never leak internal filesystem paths.

Every dataset/export/publication response uses whitelist DTOs; nested
free-form payloads (profile/evidence/manifest) are scrubbed recursively.
The assertion helper fails on denylisted keys *and* on any absolute-path
string value at any depth.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from test_experiment_api import CSV_2D, MAPPING_2D
from test_platform_results import make_client

PATH_KEYS = {"source_path", "standardized_path", "grid_path", "package_path", "predictions_path"}


def assert_no_path_leak(value: Any, trail: str = "$") -> None:
    """递归断言：无路径键名、无绝对路径形态字符串值。"""

    if isinstance(value, dict):
        for key, item in value.items():
            assert key not in PATH_KEYS, f"{trail}.{key} 泄露内部路径键"
            assert_no_path_leak(item, f"{trail}.{key}")
    elif isinstance(value, (list, tuple)):
        for idx, item in enumerate(value):
            assert_no_path_leak(item, f"{trail}[{idx}]")
    elif isinstance(value, str):
        head = value[:2]
        assert not (len(value) >= 2 and value[1] == ":" and value[0].isalpha()), f"{trail} 泄露盘符路径：{value!r}"
        is_download_url = value.startswith("/api/")
        assert is_download_url or not value.startswith(("\\\\", "/")), f"{trail} 泄露绝对路径：{value!r}"
        assert head != "~" or not value.startswith("~/"), f"{trail} 泄露用户目录：{value!r}"


def prepare_validated_dataset(client) -> tuple[str, str]:
    case_id = client.post("/api/cases", json={"name": "DTO 案例"}).json()["id"]
    upload = client.post(
        f"/api/cases/{case_id}/datasets/uploads",
        files={"file": ("data.csv", io.BytesIO(CSV_2D.encode()), "application/octet-stream")},
    )
    assert upload.status_code == 201, upload.text
    dataset_id = upload.json()["id"]
    assert_no_path_leak(upload.json(), "$.upload")
    assert client.post(f"/api/datasets/{dataset_id}/mapping", json=MAPPING_2D).status_code == 200
    assert client.post(f"/api/datasets/{dataset_id}/validate").status_code == 200
    return case_id, dataset_id


def test_dataset_endpoints_use_whitelist_dto(tmp_path):
    client, _ = make_client(tmp_path)
    case_id, dataset_id = prepare_validated_dataset(client)

    mapping = client.post(f"/api/datasets/{dataset_id}/mapping", json=MAPPING_2D)
    assert mapping.status_code == 200
    assert_no_path_leak(mapping.json(), "$.mapping")

    get_resp = client.get(f"/api/datasets/{dataset_id}")
    assert get_resp.status_code == 200
    assert_no_path_leak(get_resp.json(), "$.get_dataset")

    inspection = client.get(f"/api/datasets/{dataset_id}/inspection")
    assert inspection.status_code == 200
    assert_no_path_leak(inspection.json(), "$.inspection")

    listing = client.get(f"/api/cases/{case_id}/datasets")
    assert listing.status_code == 200
    assert_no_path_leak(listing.json(), "$.case_datasets")

    points = client.get(f"/api/datasets/{dataset_id}/points")
    assert points.status_code == 200
    assert_no_path_leak(points.json(), "$.points")


def test_export_and_publication_responses_have_no_internal_paths(tmp_path):
    import time

    client, _ = make_client(tmp_path)
    case_id, dataset_id = prepare_validated_dataset(client)
    experiment = client.post("/api/experiments", json={
        "case_id": case_id,
        "name": "DTO 实验",
        "algorithm": "idw",
        "dataset_version_id": dataset_id,
        "search_mode": "manual",
        "parameters": {"power": 2.0, "neighbor_count": 4},
        "validation": {"method": "spatial_kfold", "folds": 3, "seed": 1, "holdout_fraction": 0.2},
    })
    experiment_id = experiment.json()["id"]
    run_id = client.post(f"/api/experiments/{experiment_id}/runs").json()["id"]
    deadline = time.time() + 30
    while time.time() < deadline:
        body = client.get(f"/api/runs/{run_id}").json()
        if body["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.1)
    assert body["status"] == "succeeded"
    candidate = client.get(f"/api/experiments/{experiment_id}/candidates").json()["candidates"][0]

    materialized = client.get(f"/api/results/{candidate['id']}")
    assert materialized.status_code == 200, materialized.text
    assert_no_path_leak(materialized.json(), "$.result_metadata")

    export = client.post(f"/api/results/{candidate['id']}/exports")
    assert export.status_code == 201, export.text
    assert_no_path_leak(export.json(), "$.export")

    publication = client.post(f"/api/results/{candidate['id']}/publications")
    assert publication.status_code == 201, publication.text
    body = publication.json()
    assert_no_path_leak(body, "$.publication")
    # 发布证据只能给资源 ID 或下载 URL，不给服务器文件路径
    assert body["evidence"]["download_url"] == f"/api/exports/{body['export_id']}/download"
    assert "package" not in body["evidence"]
