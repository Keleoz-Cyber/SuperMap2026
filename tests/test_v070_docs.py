"""v0.7.0 Batch 1：文档与版本面合同（Task 10）。

锁定：版本面全部 0.7.0；README 与状态文档描述微震 CSV 预置新流程
（CSV 预置 / 普通克里金 / NetCDF / builtin_preset），并明确 DAT 导入
不在产品面；拒绝把「导入微震 DAT」写成产品操作指引。
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

EXPECTED = "0.7.0"

README = Path("README.md")
STATUS_DOC = Path("docs/status/current-status.md")

REQUIRED_TERMS = ("CSV 预置", "普通克里金", "NetCDF", "builtin_preset")

# 状态文档必须明确 DAT 导入已退出产品面（措辞可不同，事实必须在）
DAT_EXIT_MARKERS = ("DAT", "退出产品", "不在产品面", "不再提供")

# 产品指引中不得再出现 DAT 导入操作话术
STALE_DAT_INSTRUCTION = "导入微震 DAT"


def _read(path: Path) -> str:
    assert path.exists(), f"{path} 不存在"
    return path.read_text(encoding="utf-8")


def test_version_surfaces_are_070():
    doc = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert doc["project"]["version"] == EXPECTED
    pkg = json.loads(Path("web/package.json").read_text(encoding="utf-8"))
    assert pkg["version"] == EXPECTED


def test_status_doc_describes_preset_flow_and_dat_exit():
    text = _read(STATUS_DOC)
    missing = [term for term in REQUIRED_TERMS if term not in text]
    assert not missing, "状态文档缺少 v0.7.0 关键事实词: " + "; ".join(missing)
    assert any(marker in text for marker in DAT_EXIT_MARKERS), (
        "状态文档必须明确 DAT 导入已退出产品面"
    )


def test_readme_describes_preset_flow_and_dat_exit():
    text = _read(README)
    missing = [term for term in REQUIRED_TERMS if term not in text]
    assert not missing, "README 缺少 v0.7.0 关键事实词: " + "; ".join(missing)
    assert any(marker in text for marker in DAT_EXIT_MARKERS), (
        "README 必须明确 DAT 导入已退出产品面"
    )


def test_no_stale_dat_import_instructions():
    for path in (README, STATUS_DOC):
        assert STALE_DAT_INSTRUCTION not in _read(path), (
            f"{path} 不得再把「导入微震 DAT」写作产品操作"
        )
