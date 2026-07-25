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

ENV_DATA_DIR = "GEOMODELING_DATA_DIR"
DEFAULT_DATA_DIR = "var/geomodeling"

DB_FILENAME = "platform.sqlite3"

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

    def upload_source(self, case_id: str, dataset_id: str, suffix: str) -> Path:
        """Original uploaded file, e.g. ``uploads/{case}/{dataset}/source.csv``."""

        return self.uploads_dir / case_id / dataset_id / f"source.{suffix}"

    def standardized_dataset(self, case_id: str, dataset_id: str) -> Path:
        return self.datasets_dir / case_id / dataset_id / "standardized.parquet"

    def experiment_dir(self, experiment_id: str) -> Path:
        return self.experiments_dir / experiment_id

    def result_grid(self, result_id: str) -> Path:
        return self.results_dir / result_id / "grid.npz"

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
        )
