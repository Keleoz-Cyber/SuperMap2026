"""Task 18: professional analysis CLI parity（设计 §15）。

五个命令（diagnose/confirm/inspect-result/extract-anomalies/compare）与 API
共用同一平台服务层：隔离数据目录上跑通 诊断→确认→成果证据→异常提取→比较
全链路；JSON 输出只含逻辑身份、相对工件名、SHA-256 与计数，绝不泄露绝对路
径；结构化失败统一 exit 1 并打印统一错误码与消息。

Red-phase note: 本模块刻意不 import ``geomodeling.professional_cli``——命令
组注册前每个测试以 exit_code != 0（No such command）失败，而非 collection
ImportError。
"""

from __future__ import annotations

import json
import math
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from typer.testing import CliRunner

from geomodeling.cli import app
from geomodeling.modeling.variogram import VARIOGRAM_FIT_FAILED
from geomodeling.platform import PlatformRuntime, tables
from geomodeling.platform.professional import sha256_file
from geomodeling.platform.settings import PlatformSettings

from test_public_dto import assert_no_path_leak

runner = CliRunner()

CASE_ID = "c1"
DATASET_ID = "ds1"
SEED_DIAGNOSIS_ID = "diag-seed"
SEED_CONFIRMATION_ID = "conf-seed"

MAPPING_2D = {
    "dimension": "2d",
    "x": "x",
    "y": "y",
    "z": None,
    "value": "value",
    "value_name": "属性",
    "coordinate_kind": "local_linear",
}

VALIDATION = {"method": "spatial_kfold", "folds": 3, "seed": 11, "holdout_fraction": 0.2}
NEIGHBORHOOD = {"radii": [500.0, 500.0], "min_neighbors": 2, "max_neighbors": 8}
EMPIRICAL = {"min_neighbors": 2, "max_neighbors": 8}

DIAGNOSIS_CONFIG = {
    "variogram": {
        "lag_count": 12,
        "min_pairs_per_bin": 20,
        "max_pairs": 50000,
        "directions": [
            {"dimension": "2d", "azimuth_deg": 0.0, "azimuth_tolerance_deg": 25.0},
            {"dimension": "2d", "azimuth_deg": 90.0, "azimuth_tolerance_deg": 25.0},
        ],
    }
}

# min_pairs_per_bin 取契约上限、超过任何 bin 的点对数 → 有效 bin 不足，执行期结构化失败
INSUFFICIENT_CONFIG = {
    "variogram": {"lag_count": 12, "min_pairs_per_bin": 10000, "max_pairs": 50000}
}

# lag_count 低于契约下限 → 请求期即 PROFESSIONAL_CONFIG_INVALID
INVALID_CONFIG = {"variogram": {"lag_count": 2}}

KRIGING_SEED_CONFIRMATION_CONFIG = {
    "model": "spherical",
    "parameter_strategy": "automatic_candidate",
    "parameter_origin": "automatic_candidate",
    "fitted_models_sha256": "e" * 64,
    "anisotropy": {"keep_isotropic": True},
}

DIAGNOSIS_ARTIFACT_NAMES = {
    "metadata",
    "omnidirectional",
    "directional",
    "fitted_models",
    "anisotropy_candidates",
}


# ---------------------------------------------------------------------------
# 夹具：隔离数据目录上的真实服务链路（沿用 test_professional_result_materialization 模式）
# ---------------------------------------------------------------------------


def _write_standardized(runtime: PlatformRuntime) -> Path:
    """14×14 规则点阵标准化 parquet（与专业 API 测试同一生成器）。"""

    grid = [index * 10.0 for index in range(14)]
    points = [(x, y) for x in grid for y in grid]
    frame = pd.DataFrame(
        {
            "source_row": list(range(1, len(points) + 1)),
            "x": [x for x, _ in points],
            "y": [y for _, y in points],
            "z": [float("nan")] * len(points),
            "value": [2.0 * math.sin(x / 25.0) + math.cos(y / 60.0) + 10.0 for x, y in points],
            "is_numeric_valid": [True] * len(points),
        }
    )
    target = runtime.settings.standardized_dataset(CASE_ID, DATASET_ID)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(target, index=False)
    return target


def _insert_dataset(runtime: PlatformRuntime, standardized_path: Path) -> None:
    with runtime.session() as session:
        session.add(tables.Case(id=CASE_ID, name="CLI 案例", case_type="generic", config_json="{}"))
        session.add(
            tables.DatasetVersion(
                id=DATASET_ID,
                case_id=CASE_ID,
                version=1,
                status="validated",
                source_path="grid.csv",
                profile_json=tables.dumps_canonical(
                    {
                        "mapping": MAPPING_2D,
                        "source_sha256": "a" * 64,
                        "standardized_sha256": sha256_file(standardized_path),
                        "standardized_path": str(standardized_path),
                        "quality": {"status": "passed", "confirmed": True},
                    }
                ),
            )
        )
        session.commit()


def _insert_seed_confirmation(runtime: PlatformRuntime) -> None:
    """专业 run 需要的确认快照（与物化测试同一合成行模式）。"""

    with runtime.session() as session:
        session.add(
            tables.ProfessionalDiagnostic(
                id=SEED_DIAGNOSIS_ID,
                dataset_version_id=DATASET_ID,
                status="succeeded",
                config_json="{}",
                fingerprint="a" * 64,
                manifest_json="{}",
            )
        )
        session.commit()
        session.add(
            tables.ProfessionalConfirmation(
                id=SEED_CONFIRMATION_ID,
                diagnostic_id=SEED_DIAGNOSIS_ID,
                config_json=tables.dumps_canonical(KRIGING_SEED_CONFIRMATION_CONFIG),
                fingerprint="f" * 64,
                note="种子确认",
            )
        )
        session.commit()


def _search(algorithm: str) -> dict:
    return {
        "algorithm": algorithm,
        "dataset_version_id": DATASET_ID,
        "search_mode": "manual",
        "parameters": (
            {"neighbor_count": 8}
            if algorithm == "ordinary_kriging"
            else {"power": 2.0, "neighbor_count": 8}
        ),
        "validation": dict(VALIDATION),
        "grid": None,
    }


def _insert_experiment(runtime: PlatformRuntime, search: dict) -> str:
    experiment_id = str(uuid.uuid4())
    with runtime.session() as session:
        session.add(
            tables.Experiment(
                id=experiment_id,
                case_id=CASE_ID,
                name="CLI 实验",
                params_json=tables.dumps_canonical(search),
            )
        )
        session.commit()
    return experiment_id


def _execute(runtime: PlatformRuntime, experiment_id: str) -> str:
    """同步驱动 run 到成功，返回成功候选 id（Task 14 证据链真实路径）。"""

    from geomodeling.modeling.runner import execute_run

    run_id = str(uuid.uuid4())
    with runtime.session() as session:
        session.add(tables.Run(id=run_id, experiment_id=experiment_id, status="queued"))
        session.commit()
    outcome = execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "succeeded"
    with runtime.session() as session:
        row = (
            session.query(tables.CandidateResult)
            .filter(tables.CandidateResult.run_id == run_id)
            .one()
        )
        return row.id


def _run_professional_candidate(
    runtime: PlatformRuntime, *, algorithm: str, confirmation_id: str | None = None
) -> str:
    """经服务层解析专业上下文并运行到成功候选（与物化测试同一模式）。"""

    from geomodeling.platform.experiments import resolve_professional_context
    from geomodeling.platform.repositories import DatasetRepository
    from geomodeling.platform.schemas import ExperimentCreateRequest

    search = _search(algorithm)
    experiment_id = _insert_experiment(runtime, search)
    request_kwargs: dict = {
        "algorithm": algorithm,
        "parameters": search["parameters"],
        "neighborhood": dict(NEIGHBORHOOD),
        "empirical_uncertainty": dict(EMPIRICAL),
    }
    if confirmation_id is not None:
        request_kwargs["professional_confirmation_id"] = confirmation_id
    request = ExperimentCreateRequest(
        case_id=CASE_ID,
        name="专业实验",
        dataset_version_id=DATASET_ID,
        **request_kwargs,
    )
    with runtime.session() as session:
        dataset = DatasetRepository(session).get(DATASET_ID)
        professional = resolve_professional_context(session, request, dataset)
    with runtime.session() as session:
        row = session.get(tables.Experiment, experiment_id)
        params = tables.loads_canonical(row.params_json)
        params["professional"] = professional
        row.params_json = tables.dumps_canonical(params)
        session.commit()
    return _execute(runtime, experiment_id)


@pytest.fixture(scope="module")
def professional_data(tmp_path_factory):
    """隔离数据目录：196 点数据版本 + Kriging/IDW 专业候选（物化）+ legacy 候选。"""

    from geomodeling.platform.results import materialize

    data_dir = tmp_path_factory.mktemp("prof_cli") / "data"
    runtime = PlatformRuntime(settings=PlatformSettings(data_dir=data_dir))
    runtime.initialize()
    try:
        _insert_dataset(runtime, _write_standardized(runtime))
        _insert_seed_confirmation(runtime)
        kriging_result_id = _run_professional_candidate(
            runtime, algorithm="ordinary_kriging", confirmation_id=SEED_CONFIRMATION_ID
        )
        kriging_metadata = materialize(runtime, kriging_result_id)
        idw_result_id = _run_professional_candidate(runtime, algorithm="idw")
        materialize(runtime, idw_result_id)
        legacy_result_id = _execute(runtime, _insert_experiment(runtime, _search("idw")))
        low, high = kriging_metadata["value_range"]
        anomaly_config = {"direction": "high", "threshold": low + 0.1 * (high - low)}
    finally:
        runtime.close()
    return SimpleNamespace(
        data_dir=data_dir,
        kriging_result_id=kriging_result_id,
        idw_result_id=idw_result_id,
        legacy_result_id=legacy_result_id,
        anomaly_config=anomaly_config,
    )


# ---------------------------------------------------------------------------
# 断言助手
# ---------------------------------------------------------------------------


def _invoke_ok(args: list[str], data_dir: Path) -> dict:
    """成功调用：exit 0 + 可解析 JSON + 递归无路径泄露 + 数据目录绝不出现在输出中。"""

    result = runner.invoke(app, [*args, "--data-dir", str(data_dir)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert_no_path_leak(payload, "$.cli")
    assert str(data_dir) not in result.output
    return payload


def _invoke_failed(args: list[str], data_dir: Path) -> dict:
    """结构化失败：exit 1 + 可解析 JSON + 无路径泄露。"""

    result = runner.invoke(app, [*args, "--data-dir", str(data_dir)])
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert_no_path_leak(payload, "$.cli_error")
    assert str(data_dir) not in result.output
    return payload


def _assert_manifest_artifacts(manifest: dict) -> None:
    """manifest 摘要只含逻辑工件名 + file/sha256/bytes，绝无服务器目录。"""

    assert "directory" not in json.dumps(manifest)
    for entry in manifest["artifacts"].values():
        assert set(entry) <= {"file", "sha256", "bytes"}
        assert len(entry["sha256"]) == 64
        assert entry["bytes"] > 0


# ---------------------------------------------------------------------------
# 帮助与全链路工作流
# ---------------------------------------------------------------------------


def test_professional_help_lists_commands():
    result = runner.invoke(app, ["professional", "--help"])
    assert result.exit_code == 0
    for command in ("diagnose", "confirm", "inspect-result", "extract-anomalies", "compare"):
        assert command in result.output


def test_diagnose_then_confirm_workflow(professional_data):
    diagnosis = _invoke_ok(
        [
            "professional",
            "diagnose",
            "--dataset-id",
            DATASET_ID,
            "--config-json",
            json.dumps(DIAGNOSIS_CONFIG),
        ],
        professional_data.data_dir,
    )
    assert diagnosis["status"] == "succeeded"
    assert diagnosis["dataset_version_id"] == DATASET_ID
    assert len(diagnosis["id"]) > 0
    assert len(diagnosis["fingerprint"]) == 64
    assert diagnosis["job_id"]
    assert diagnosis["reused"] is False
    manifest = diagnosis["manifest"]
    assert set(manifest["artifacts"]) == DIAGNOSIS_ARTIFACT_NAMES
    _assert_manifest_artifacts(manifest)
    assert manifest["summary"]["min_sse_model"] in {"spherical", "exponential", "gaussian"}
    assert "best_model" not in manifest["summary"]

    confirm_config = {
        "model": "spherical",
        "parameter_strategy": "automatic_candidate",
        "fitted_models_sha256": manifest["artifacts"]["fitted_models"]["sha256"],
        "anisotropy": {"keep_isotropic": True},
    }
    confirmation = _invoke_ok(
        [
            "professional",
            "confirm",
            "--diagnosis-id",
            diagnosis["id"],
            "--note",
            "CLI 采纳自动候选",
            "--config-json",
            json.dumps(confirm_config),
        ],
        professional_data.data_dir,
    )
    assert len(confirmation["id"]) > 0
    assert confirmation["diagnostic_id"] == diagnosis["id"]
    assert len(confirmation["fingerprint"]) == 64
    assert confirmation["note"] == "CLI 采纳自动候选"
    assert confirmation["config"]["parameter_origin"] == "automatic_candidate"


def test_diagnose_same_config_reuses_success(professional_data):
    args = [
        "professional",
        "diagnose",
        "--dataset-id",
        DATASET_ID,
        "--config-json",
        json.dumps(DIAGNOSIS_CONFIG),
    ]
    first = _invoke_ok(args, professional_data.data_dir)
    second = _invoke_ok(args, professional_data.data_dir)
    assert second["status"] == "succeeded"
    assert second["reused"] is True
    assert second["job_id"] is None
    assert second["id"] == first["id"]


def test_inspect_result_outputs_capabilities_provenance_and_manifest(professional_data):
    payload = _invoke_ok(
        ["professional", "inspect-result", "--result-id", professional_data.kriging_result_id],
        professional_data.data_dir,
    )
    assert payload["available"] is True
    assert payload["algorithm"] == "ordinary_kriging"
    assert payload["capabilities"]
    provenance = payload["parameter_provenance"]
    assert provenance["final"]["origin"] == "final_full_data_fit"
    assert provenance["validation"]["origin"] == "automatic_candidate"
    _assert_manifest_artifacts(payload["manifest"])


def test_inspect_result_legacy_candidate_explicit_not_computed(professional_data):
    payload = _invoke_ok(
        ["professional", "inspect-result", "--result-id", professional_data.legacy_result_id],
        professional_data.data_dir,
    )
    assert payload["available"] is False
    assert payload["reason"] == "LEGACY_RESULT_NOT_COMPUTED"
    assert payload["algorithm"] == "idw"
    assert "capabilities" not in payload
    assert "manifest" not in payload


def test_extract_anomalies_outputs_component_count(professional_data):
    payload = _invoke_ok(
        [
            "professional",
            "extract-anomalies",
            "--result-id",
            professional_data.kriging_result_id,
            "--config-json",
            json.dumps(professional_data.anomaly_config),
        ],
        professional_data.data_dir,
    )
    assert payload["status"] == "succeeded"
    assert payload["job_id"]
    assert len(payload["fingerprint"]) == 64
    assert payload["manifest"]["summary"]["component_count"] >= 1
    _assert_manifest_artifacts(payload["manifest"])


def test_compare_outputs_compatibility_deltas_and_fingerprint(professional_data):
    payload = _invoke_ok(
        [
            "professional",
            "compare",
            "--first",
            professional_data.kriging_result_id,
            "--second",
            professional_data.idw_result_id,
        ],
        professional_data.data_dir,
    )
    assert payload["compatible"] is True
    assert payload["mismatches"] == []
    assert payload["common_valid_count"] > 0
    assert payload["metric_deltas"]
    assert payload["grid_difference_available"] is True
    assert len(payload["comparison_fingerprint"]) == 64


# ---------------------------------------------------------------------------
# 结构化失败：exit 1 + 统一错误码
# ---------------------------------------------------------------------------


def test_diagnose_unknown_dataset_exits_1_with_structured_error(professional_data):
    payload = _invoke_failed(
        ["professional", "diagnose", "--dataset-id", "missing-dataset"],
        professional_data.data_dir,
    )
    assert payload["error"]["code"] == "DATASET_NOT_FOUND"
    assert payload["error"]["message"]


def test_diagnose_insufficient_pairs_fails_structured(professional_data):
    payload = _invoke_failed(
        [
            "professional",
            "diagnose",
            "--dataset-id",
            DATASET_ID,
            "--config-json",
            json.dumps(INSUFFICIENT_CONFIG),
        ],
        professional_data.data_dir,
    )
    assert payload["status"] == "failed"
    assert payload["error"]["code"] == VARIOGRAM_FIT_FAILED


def test_diagnose_invalid_config_exits_1_with_config_error(professional_data):
    payload = _invoke_failed(
        [
            "professional",
            "diagnose",
            "--dataset-id",
            DATASET_ID,
            "--config-json",
            json.dumps(INVALID_CONFIG),
        ],
        professional_data.data_dir,
    )
    assert payload["error"]["code"] == "PROFESSIONAL_CONFIG_INVALID"


def test_compare_same_candidate_exits_1(professional_data):
    payload = _invoke_failed(
        [
            "professional",
            "compare",
            "--first",
            professional_data.kriging_result_id,
            "--second",
            professional_data.kriging_result_id,
        ],
        professional_data.data_dir,
    )
    assert payload["error"]["code"] == "COMPARISON_SAME_CANDIDATE"
