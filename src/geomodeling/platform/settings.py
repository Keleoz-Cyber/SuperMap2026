"""v0.4 platform runtime paths.

The runtime root resolves from ``GEOMODELING_DATA_DIR`` and defaults to
``var/geomodeling`` (gitignored). Every durable artifact of the generic
modeling platform — the SQLite database, uploaded sources, standardized
datasets, experiment workspaces, result grids, and export packages — lives
under this root.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from geomodeling.platform.errors import PRESET_SOURCE_INVALID, PlatformError
from geomodeling.platform.render_contracts import DisplayAnchor

ENV_DATA_DIR = "GEOMODELING_DATA_DIR"
DEFAULT_DATA_DIR = "var/geomodeling"

DB_FILENAME = "platform.sqlite3"

# v0.8.0 第三批：三个官方案例的规范化源 CSV 随仓库内置，统一从
# ``PROJECT_ROOT / "example_data"`` 解析（字节级冻结，见
# tests/test_example_data_contract.py）。
PROJECT_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_DATA_DIRNAME = "example_data"


def example_data_path(filename: str) -> Path:
    """解析内置示例数据文件：``PROJECT_ROOT / "example_data" / filename``。

    只接受纯文件名——拒绝空串、``.``/``..`` 与任何路径分隔符（``/``、``\\``），
    防止目录穿越；文件不存在时抛出 ``PRESET_SOURCE_INVALID`` 类型化错误，
    公开 details 不含本机绝对路径。

    返回的绝对路径仅供后端 seed/合同校验内部使用，绝不写入任何 API DTO：
    浏览器只接收逻辑来源（预置 ID / 相对路径）与内容 SHA-256。
    """

    if (
        not filename
        or filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
    ):
        raise PlatformError(
            PRESET_SOURCE_INVALID,
            f"内置示例数据文件名非法：{filename!r}",
            details={"reason": "filename_must_be_plain", "directory": EXAMPLE_DATA_DIRNAME},
            http_status=409,
        )
    candidate = PROJECT_ROOT / EXAMPLE_DATA_DIRNAME / filename
    if not candidate.is_file():
        raise PlatformError(
            PRESET_SOURCE_INVALID,
            f"内置示例数据不存在：{EXAMPLE_DATA_DIRNAME}/{filename}",
            details={"directory": EXAMPLE_DATA_DIRNAME, "filename": filename},
            http_status=409,
        )
    return candidate

# 上传硬上限：50 MiB、500,000 数据行。构造 PlatformSettings 时可覆盖，
# inspection 响应会把实际生效值回传给前端展示。
DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_UPLOAD_ROWS = 500_000


@dataclass(frozen=True)
class PlatformSettings:
    data_dir: Path
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    max_upload_rows: int = DEFAULT_MAX_UPLOAD_ROWS

    @classmethod
    def resolve(cls) -> "PlatformSettings":
        return cls(data_dir=Path(os.environ.get(ENV_DATA_DIR, DEFAULT_DATA_DIR)))

    @property
    def db_path(self) -> Path:
        return self.data_dir / DB_FILENAME

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def datasets_dir(self) -> Path:
        return self.data_dir / "datasets"

    @property
    def experiments_dir(self) -> Path:
        return self.data_dir / "experiments"

    @property
    def results_dir(self) -> Path:
        return self.data_dir / "results"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def render_sources_dir(self) -> Path:
        return self.data_dir / "render-sources"

    @property
    def render_assets_dir(self) -> Path:
        return self.data_dir / "render-assets"

    @property
    def comparisons_dir(self) -> Path:
        """Deep candidate comparison registry root (v0.7.0 batch 3)."""
        return self.data_dir / "comparisons"

    @property
    def purge_quarantine_dir(self) -> Path:
        """Quarantine root for case purge file moves (v0.7.0 batch 3 §5.4)."""
        return self.data_dir / "purge-quarantine"

    @property
    def display_anchor(self) -> DisplayAnchor:
        return DisplayAnchor(longitude=120.0, latitude=30.0, height=0.0)

    def upload_source(self, case_id: str, dataset_id: str, suffix: str) -> Path:
        """Original uploaded file, e.g. ``uploads/{case}/{dataset}/source.csv``."""

        return self.uploads_dir / case_id / dataset_id / f"source.{suffix}"

    def standardized_dataset(self, case_id: str, dataset_id: str) -> Path:
        return self.datasets_dir / case_id / dataset_id / "standardized.parquet"

    def microseismic_dataset_dir(self, case_id: str, dataset_id: str) -> Path:
        """Immutable microseismic dataset version directory (source/ + derived/)."""

        return self.datasets_dir / case_id / dataset_id

    def microseismic_staging_dir(self) -> Path:
        """Per-import staging root; each import derives under a unique child."""

        return self.data_dir / "staging" / "microseismic"

    def modeling_provenance(self, case_id: str, dataset_id: str) -> Path:
        return self.microseismic_dataset_dir(case_id, dataset_id) / "derived" / "modeling_provenance.parquet"

    def experiment_dir(self, experiment_id: str) -> Path:
        return self.experiments_dir / experiment_id

    def result_grid(self, result_id: str) -> Path:
        return self.results_dir / result_id / "grid.npz"

    def ml_fields(self, result_id: str) -> Path:
        return self.results_dir / result_id / "ml_fields.npz"

    def ml_fields_manifest(self, result_id: str) -> Path:
        return self.results_dir / result_id / "ml_fields.json"

    def professional_result_dir(self, result_id: str) -> Path:
        """Per-candidate professional artifact directory (fold/OOF evidence)."""

        return self.results_dir / result_id / "professional"

    def professional_result_manifest(self, result_id: str) -> Path:
        """专业物化清单：物化完成与幂等重读的身份标记（设计 §5.3）。"""

        return self.professional_result_dir(result_id) / "manifest.json"

    def professional_diagnosis_dir(
        self, case_id: str, dataset_id: str, diagnosis_id: str
    ) -> Path:
        """Per-diagnosis professional artifact directory (variogram evidence)."""

        return (
            self.datasets_dir / case_id / dataset_id / "professional"
            / "diagnostics" / diagnosis_id
        )

    def anomaly_extraction_dir(self, result_id: str, extraction_id: str) -> Path:
        """Per-extraction anomaly artifact directory under a materialized result."""

        return self.results_dir / result_id / "anomalies" / extraction_id

    def export_package(self, export_id: str) -> Path:
        return self.exports_dir / export_id / "result-package.zip"

    def runtime_directories(self) -> tuple[Path, ...]:
        return (
            self.data_dir,
            self.uploads_dir,
            self.datasets_dir,
            self.experiments_dir,
            self.results_dir,
            self.exports_dir,
            self.render_sources_dir,
            self.render_assets_dir,
            self.comparisons_dir,
            self.purge_quarantine_dir,
        )
