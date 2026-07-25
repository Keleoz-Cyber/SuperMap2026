"""Task 7: CI workflow structure contract for the Live E2E job."""

from __future__ import annotations

from pathlib import Path

import yaml

CI = Path(".github/workflows/ci.yml")


def _jobs() -> dict:
    doc = yaml.safe_load(CI.read_text(encoding="utf-8"))
    return doc["jobs"]


def _live_job() -> dict:
    jobs = _jobs()
    assert "browser-live" in jobs, "ci.yml 缺少 browser-live job"
    return jobs["browser-live"]


def _steps(job: dict) -> list[str]:
    return [str(step.get("run", "") or step.get("uses", "")) for step in job["steps"]]


def test_existing_jobs_remain():
    jobs = _jobs()
    assert "portable-tests" in jobs
    assert "browser-smoke" in jobs


def test_live_job_installs_and_builds_before_running():
    steps = _steps(_live_job())
    joined = "\n".join(steps)
    assert ".[test]" in joined or ".[api,test]" in joined, "缺少 Python 依赖安装"
    assert "npm --prefix web ci" in joined, "缺少前端依赖安装"
    # 构建必须先于 Live E2E
    build_idx = next(i for i, s in enumerate(steps) if "npm --prefix web run build" in s)
    live_idx = next(i for i, s in enumerate(steps) if "test:e2e:live" in s)
    assert build_idx < live_idx, "前端 build 必须先于 test:e2e:live"
    assert "playwright install chromium" in joined


def test_live_job_isolates_runtime_under_runner_temp():
    job = _live_job()
    text = "\n".join(_steps(job))
    assert "RUNNER_TEMP" in text
    assert "GEOMODELING_DATA_DIR" in text
    env_text = yaml.safe_dump(job.get("env", {}))
    assert "var/geomodeling" not in env_text


def test_live_job_uploads_failure_artifacts_without_iserver_secrets():
    job = _live_job()
    artifact_steps = [
        step for step in job["steps"]
        if "upload-artifact" in str(step.get("uses", ""))
    ]
    assert artifact_steps, "缺少失败工件上传步骤"
    for step in artifact_steps:
        assert step.get("if") == "failure()"
        path_text = yaml.safe_dump(step.get("with", {}))
        assert "web/test-results" in path_text
        assert "web/playwright-report" in path_text
    whole = CI.read_text(encoding="utf-8")
    assert "ISERVER_ADMIN_PASSWORD" not in whole
    assert "secrets." not in whole, "browser-live 不得引用任何凭据"
