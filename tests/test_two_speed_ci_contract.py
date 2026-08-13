"""Two-speed CI contract: fast commits, full release tags/manual runs."""

from __future__ import annotations

from pathlib import Path

import yaml


CI = Path(".github/workflows/ci.yml")
FULL_CONDITION = "startsWith(github.ref, 'refs/tags/v') || github.event_name == 'workflow_dispatch'"


def _document() -> dict:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))


def _steps(job: dict) -> list[dict]:
    return list(job["steps"])


def test_workflow_declares_branch_and_release_tag_pushes() -> None:
    text = CI.read_text(encoding="utf-8")
    assert 'branches: ["**"]' in text
    assert 'tags: ["v*"]' in text
    assert "workflow_dispatch:" in text


def test_portable_job_exposes_full_mode_expression() -> None:
    job = _document()["jobs"]["portable-tests"]
    assert job["env"]["FULL_CI"] == "${{ " + FULL_CONDITION + " }}"


def test_fast_and_full_python_steps_are_mutually_exclusive() -> None:
    steps = _steps(_document()["jobs"]["portable-tests"])
    fast = next(step for step in steps if step.get("name") == "Run fast Python contract tests")
    full = next(step for step in steps if step.get("name") == "Run full portable tests")
    assert fast["if"] == "env.FULL_CI != 'true'"
    assert full["if"] == "env.FULL_CI == 'true'"
    fast_command = fast["run"]
    assert "tests/test_version_consistency.py" in fast_command
    assert "tests/test_portable.py" in fast_command
    assert "tests/test_two_speed_ci_contract.py" in fast_command
    assert 'pytest -q -m "not local_data"' in full["run"]


def test_browser_jobs_only_run_for_release_or_manual_full_ci() -> None:
    jobs = _document()["jobs"]
    expected = "${{ " + FULL_CONDITION + " }}"
    assert jobs["browser-smoke"]["if"] == expected
    assert jobs["browser-live"]["if"] == expected


def test_frontend_gates_remain_unconditional_in_portable_job() -> None:
    steps = _steps(_document()["jobs"]["portable-tests"])
    names = ("Frontend unit tests", "Frontend type-check", "Frontend build")
    for name in names:
        step = next(item for item in steps if item.get("name") == name)
        assert "if" not in step
