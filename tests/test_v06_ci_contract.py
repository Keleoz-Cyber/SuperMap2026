"""Task 22: v0.6 CI contract — professional synthetic loop stays locked in CI.

在 v0.5 三 job 合同（``tests/test_v05_ci_contract.py``）之上锁定 v0.6 增量：

- 三个 job（portable-tests / browser-smoke / browser-live）一个不少、不重复；
- portable-tests 依旧跑整套排除 ``local_data`` 的便携 pytest——新的合成
  结构验收测试不带 ``local_data`` 标记，默认进入该套件；
- Mock E2E 规格（``web/e2e/platform-flow.spec.ts``）必须覆盖专业建模链
  （质量门禁数据集 → 诊断 → 确认 → 专业 Kriging 实验 → 折分检查 → 不确
  定性图层 → 已保存异常 → 兼容比较）；
- Live E2E 规格（``web/e2e-live/platform-live.spec.ts``）必须覆盖真实专
  业链路并保持隔离运行时（``GEOMODELING_DATA_DIR``）与有界轮询；
- browser-live 保持隔离目录分配与失败工件上传；整个 workflow 依旧无凭
  据、无私有证据标记。
"""

from __future__ import annotations

from pathlib import Path

import yaml

CI = Path(".github/workflows/ci.yml")
MOCK_SPEC = Path("web/e2e/platform-flow.spec.ts")
LIVE_SPEC = Path("web/e2e-live/platform-live.spec.ts")
SYNTHETIC_TESTS = Path("tests/test_professional_synthetic_structures.py")
EXPECTED_JOBS = {"portable-tests", "browser-smoke", "browser-live"}

# Mock E2E 专业链路必须出现的控件/页面锚点（与 platform-flow.spec.ts 一致）
# v0.7.0: professional-toggle removed; confirmation auto-enables professional mode
MOCK_PROFESSIONAL_MARKERS = (
    "professional-entry",
    "start-diagnosis",
    "suggestion-label",
    "confirm-note",
    "confirm-submit",
    "confirmation-snapshot",
    "goto-experiment",
    "professional-confirmation",
    "fold-inspector",
    "layer-tab-empirical",
    "layer-tab-kriging-std",
    "anomaly-save",
    "extraction-identity",
    "comparison-run",
    "comparison-compatible",
)

# Live E2E 专业链路锚点（真实 FastAPI + 隔离 SQLite + 导出 professional/ 证据）
# v0.7.0: professional-toggle removed; confirmation auto-enables professional mode
LIVE_PROFESSIONAL_MARKERS = (
    "professional-entry",
    "start-diagnosis",
    "confirm-submit",
    "goto-experiment",
    "fold-inspector",
    "layer-tab-empirical",
    "anomaly-save",
    "comparison-compatible",
    "professional/manifest.json",
)


def _jobs() -> dict:
    doc = yaml.safe_load(CI.read_text(encoding="utf-8"))
    return doc["jobs"]


def _steps(job: dict) -> list[str]:
    return [str(step.get("run", "") or step.get("uses", "")) for step in job["steps"]]


def _joined(job: dict) -> str:
    return "\n".join(_steps(job))


def test_three_jobs_survive_unchanged():
    jobs = _jobs()
    assert set(jobs) == EXPECTED_JOBS, (
        f"v0.6 不得增删 CI job：必须恰好为 {sorted(EXPECTED_JOBS)}；实际：{sorted(jobs)}"
    )


def test_portable_job_still_runs_whole_portable_suite():
    steps = _steps(_jobs()["portable-tests"])
    assert any('pytest -q -m "not local_data"' in step for step in steps), (
        "portable-tests 必须运行整套排除 local_data 的便携 pytest，"
        "不得为跳过 v0.6 合成验收而缩小范围"
    )


def test_synthetic_acceptance_tests_are_portable():
    assert SYNTHETIC_TESTS.is_file(), "合成结构数值验收测试必须存在"
    text = SYNTHETIC_TESTS.read_text(encoding="utf-8")
    assert "local_data" not in text, (
        "合成结构验收必须是便携测试：不得依赖 local_data 私有资料"
    )


def test_mock_e2e_spec_covers_professional_browser_loop():
    assert MOCK_SPEC.is_file()
    text = MOCK_SPEC.read_text(encoding="utf-8")
    missing = [marker for marker in MOCK_PROFESSIONAL_MARKERS if marker not in text]
    assert not missing, f"Mock E2E 规格缺少专业建模链路锚点：{missing}"


def test_live_e2e_spec_covers_professional_loop_with_isolation():
    assert LIVE_SPEC.is_file()
    text = LIVE_SPEC.read_text(encoding="utf-8")
    missing = [marker for marker in LIVE_PROFESSIONAL_MARKERS if marker not in text]
    assert not missing, f"Live E2E 规格缺少专业建模链路锚点：{missing}"
    assert "GEOMODELING_DATA_DIR" in text, "Live 规格必须保持隔离运行时目录断言"
    assert "timeout" in text, "Live 规格必须保持有界轮询（超时上限）"


def test_browser_live_job_keeps_isolation_and_failure_artifacts():
    job = _jobs()["browser-live"]
    steps = _steps(job)
    alloc_idx = next(
        (i for i, s in enumerate(steps) if "GEOMODELING_DATA_DIR" in s and "RUNNER_TEMP" in s),
        None,
    )
    assert alloc_idx is not None, "browser-live 必须在 RUNNER_TEMP 下分配隔离数据目录"
    live_idx = next(i for i, s in enumerate(steps) if "test:e2e:live" in s)
    assert alloc_idx < live_idx, "隔离目录分配必须先于 Live E2E"
    artifact_steps = [
        step
        for step in job["steps"]
        if "upload-artifact" in str(step.get("uses", ""))
    ]
    assert artifact_steps, "browser-live 必须保留失败工件上传步骤"
    assert any(step.get("if") == "failure()" for step in artifact_steps), (
        "失败工件上传必须只在 failure() 时触发"
    )


def test_workflow_free_of_secrets_and_private_markers():
    whole = CI.read_text(encoding="utf-8")
    assert "secrets." not in whole, "CI 不得引用任何凭据"
    for private_marker in ("2006", "1925", "超图杯资料"):
        assert private_marker not in whole, f"CI 不得嵌入私有证据标记：{private_marker}"
