"""Task 14: v0.5 CI contract — three jobs cover the microseismic browser loop.

The workflow must keep exactly three jobs (portable-tests, browser-smoke,
browser-live): release-mode portable pytest with ``local_data`` excluded, frontend
unit/type-check/build, the mock-API browser E2E, and the real-FastAPI live
E2E. The live job allocates an isolated ``GEOMODELING_DATA_DIR`` and points
``GEOMODELING_MICROSEISMIC_CONFIG`` at the runtime-generated synthetic
fixture contract inside it — never at the private bundle or the real
confirmed config. A fourth duplicate E2E job is forbidden; no secrets may
appear anywhere in the workflow.
"""

from __future__ import annotations

from pathlib import Path

import yaml

CI = Path(".github/workflows/ci.yml")
EXPECTED_JOBS = {"portable-tests", "browser-smoke", "browser-live"}


def _jobs() -> dict:
    doc = yaml.safe_load(CI.read_text(encoding="utf-8"))
    return doc["jobs"]


def _steps(job: dict) -> list[str]:
    return [str(step.get("run", "") or step.get("uses", "")) for step in job["steps"]]


def _joined(job: dict) -> str:
    return "\n".join(_steps(job))


def test_exactly_three_jobs_no_duplicate_e2e_job():
    jobs = _jobs()
    assert set(jobs) == EXPECTED_JOBS, (
        f"ci.yml 必须恰好为 {sorted(EXPECTED_JOBS)} 三个 job，"
        f"不得新增第四个重复 job；实际：{sorted(jobs)}"
    )
    mock_runners = [
        name
        for name, job in jobs.items()
        if "run test:e2e" in _joined(job) and "test:e2e:live" not in _joined(job)
    ]
    live_runners = [name for name, job in jobs.items() if "test:e2e:live" in _joined(job)]
    assert mock_runners == ["browser-smoke"], "Mock E2E 必须且只能由 browser-smoke 运行"
    assert live_runners == ["browser-live"], "Live E2E 必须且只能由 browser-live 运行"


def test_release_mode_retains_portable_pytest_excluding_local_data():
    job = _jobs()["portable-tests"]
    steps = _steps(job)
    assert any('pytest -q -m "not local_data"' in step for step in steps), (
        "portable-tests 必须运行排除 local_data 的便携 pytest"
    )
    whole = _joined(job)
    assert "local_data" not in whole.replace('pytest -q -m "not local_data"', ""), (
        "除排除标记外不得出现 local_data 依赖"
    )


def test_portable_job_runs_frontend_gates_in_order():
    steps = _steps(_jobs()["portable-tests"])
    unit_idx = next(i for i, s in enumerate(steps) if "run test:unit" in s)
    type_idx = next(i for i, s in enumerate(steps) if "run type-check" in s)
    build_idx = next(i for i, s in enumerate(steps) if "run build" in s)
    assert unit_idx < type_idx < build_idx, (
        "前端门禁顺序必须为 test:unit → type-check → build"
    )


def test_browser_smoke_job_builds_and_runs_mock_e2e_without_backend():
    job = _jobs()["browser-smoke"]
    whole = _joined(job)
    assert "npm --prefix web run build" in whole, "browser-smoke 必须先构建前端产物"
    assert "playwright install chromium" in whole
    assert "test:e2e:live" not in whole, "browser-smoke 只跑 Mock E2E"
    # Mock E2E 不依赖后端/iServer：job 内不得分配数据目录或微震配置
    assert "GEOMODELING_DATA_DIR" not in whole
    assert "GEOMODELING_MICROSEISMIC_CONFIG" not in whole


def test_browser_live_job_allocates_isolated_runtime_and_microseismic_fixture():
    job = _jobs()["browser-live"]
    steps = _steps(job)
    alloc_idx = next(
        (i for i, s in enumerate(steps) if "GEOMODELING_DATA_DIR" in s and "RUNNER_TEMP" in s),
        None,
    )
    assert alloc_idx is not None, "browser-live 必须在 RUNNER_TEMP 下分配隔离 GEOMODELING_DATA_DIR"
    alloc = steps[alloc_idx]
    assert "GEOMODELING_MICROSEISMIC_CONFIG" in alloc, (
        "同一分配步骤必须给出 GEOMODELING_MICROSEISMIC_CONFIG，"
        "指向隔离目录内运行时生成的合成夹具配置"
    )
    live_idx = next(i for i, s in enumerate(steps) if "test:e2e:live" in s)
    assert alloc_idx < live_idx, "隔离运行时分配必须先于 Live E2E"
    build_idx = next(i for i, s in enumerate(steps) if "npm --prefix web run build" in s)
    assert build_idx < live_idx, "前端 build 必须先于 test:e2e:live"
    env_text = yaml.safe_dump(job.get("env", {}))
    assert "var/geomodeling" not in env_text, "browser-live 不得使用默认运行时目录"


def test_workflow_never_references_private_evidence_or_secrets():
    whole = CI.read_text(encoding="utf-8")
    assert "secrets." not in whole, "CI 不得引用任何凭据"
    for private_marker in ("2006", "1925", "超图杯资料"):
        assert private_marker not in whole, f"CI 不得嵌入私有证据标记：{private_marker}"
