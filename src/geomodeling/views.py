from __future__ import annotations

from .config import AppConfig
from .schemas import ViewConfiguration


def view_configurations_from_config(config: AppConfig, udbx_path: str | None = None) -> list[ViewConfiguration]:
    views = []
    for entry in config.views:
        data = dict(entry)
        info = dict(data.get("external_open_info", {}))
        if udbx_path or config.supermap.get("udbx_path"):
            info["udbx_path"] = udbx_path or config.supermap.get("udbx_path")
        data["external_open_info"] = info
        views.append(ViewConfiguration.model_validate(data))
    return views
