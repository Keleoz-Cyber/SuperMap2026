from __future__ import annotations

import pytest

from geomodeling.config import load_config


def _local_data_available() -> bool:
    try:
        config = load_config()
        paths = [
            config.paths["standardized"],
            config.paths["training"],
            config.paths["validation"],
            config.paths["metrics_baseline"],
            *config.paths["prediction_files"].values(),
        ]
        return all(config.resolve_path(path).is_file() for path in paths)
    except Exception:
        return False


LOCAL_DATA_AVAILABLE = _local_data_available()


def pytest_collection_modifyitems(config, items):
    if LOCAL_DATA_AVAILABLE:
        return
    skip = pytest.mark.skip(reason="adjacent read-only reference data is not available")
    for item in items:
        if "local_data" in item.keywords:
            item.add_marker(skip)
