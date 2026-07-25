"""Merge-blocker 2: upload finalize failure must not leave pending://upload rows."""

from __future__ import annotations

import io

import pytest

from test_experiment_api import CSV_2D, make_client


def test_finalize_failure_rolls_back_dataset_row(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path)

    # 模拟落盘失败（磁盘满/权限）：finalize_upload 抛 OSError
    import geomodeling.api.routes.cases as cases_module

    def failing_finalize(receipt, final_path):
        raise OSError("disk full (simulated)")

    monkeypatch.setattr(cases_module, "finalize_upload", failing_finalize)

    case_id = client.post("/api/cases", json={"name": "补偿事务案例"}).json()["id"]
    with pytest.raises(OSError, match="disk full"):
        client.post(
            f"/api/cases/{case_id}/datasets/uploads",
            files={"file": ("data.csv", io.BytesIO(CSV_2D.encode()), "application/octet-stream")},
        )

    # 补偿事务：数据集行必须被删除，不得残留 pending://upload
    listing = client.get(f"/api/cases/{case_id}/datasets")
    assert listing.status_code == 200
    assert listing.json()["datasets"] == []

    # 上传暂存文件也被清理（runtime 目录下无孤儿 upload）
    from geomodeling.platform import PlatformRuntime

    runtime: PlatformRuntime = client.app.state.platform_runtime  # type: ignore[attr-defined]
    leftovers = list((runtime.settings.data_dir / "uploads").rglob("*")) if (runtime.settings.data_dir / "uploads").exists() else []
    assert [p for p in leftovers if p.is_file()] == []
