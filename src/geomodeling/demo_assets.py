"""唯一权威演示数据解析器（demo/platform_demo_3d.csv）。

fail-closed：文件缺失、哈希不符、列或行数不符都抛
``PlatformError(DEMO_DATASET_UNAVAILABLE)``；公开诊断不含本机绝对路径。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from geomodeling.platform.errors import PlatformError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEMO_DATASET_PATH = PROJECT_ROOT / "demo" / "platform_demo_3d.csv"
DEMO_DATASET_SHA256 = "deb9c25f713ae79d7b1c6300cc8066a6ae927879767c67ab03ef4ad76e8a2bb3"
DEMO_DATASET_UNAVAILABLE = "DEMO_DATASET_UNAVAILABLE"

_EXPECTED_COLUMNS = ("x", "y", "z", "rho")
_EXPECTED_ROW_COUNT = 144


@dataclass(frozen=True)
class DemoDatasetAsset:
    path: Path
    sha256: str
    row_count: int
    columns: tuple[str, ...]


def _fail(message: str, detail: dict[str, object]) -> None:
    raise PlatformError(DEMO_DATASET_UNAVAILABLE, message, detail, http_status=503)


def get_demo_dataset(path: Path | None = None) -> DemoDatasetAsset:
    """返回经校验的演示数据资产；任何不符都 fail closed。"""

    asset_path = path if path is not None else DEMO_DATASET_PATH
    if not asset_path.exists():
        _fail("演示数据文件缺失", {"asset": asset_path.name, "reason": "missing"})

    digest = hashlib.sha256(asset_path.read_bytes()).hexdigest()
    if digest != DEMO_DATASET_SHA256:
        _fail(
            "演示数据哈希不符（文件可能被修改，请恢复仓库版本）",
            {"asset": asset_path.name, "reason": "hash_mismatch"},
        )

    with asset_path.open("r", encoding="utf-8") as handle:
        lines = [line.strip() for line in handle if line.strip()]
    columns = tuple(lines[0].split(",")) if lines else ()
    if columns != _EXPECTED_COLUMNS:
        _fail("演示数据列契约不符", {"asset": asset_path.name, "reason": "columns"})
    row_count = len(lines) - 1
    if row_count != _EXPECTED_ROW_COUNT:
        _fail("演示数据行数不符", {"asset": asset_path.name, "reason": "row_count"})

    return DemoDatasetAsset(
        path=asset_path,
        sha256=digest,
        row_count=row_count,
        columns=columns,
    )
