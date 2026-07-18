import pytest
from pydantic import ValidationError

from geomodeling.model_tasks import ModelTaskRegistry, build_model_task, select_models
from geomodeling.schemas import ModelStatus


def _task(model_id="m1", parameters=None):
    parameters = parameters or {"resolution_xy_m": 20, "neighbor_count": 40}
    return build_model_task(
        model_id=model_id,
        display_name=model_id,
        method="KRIGING_ORDINARY",
        input_dataset_id="rho_training_v1",
        input_sha256="0" * 64,
        parameters=parameters,
        config_snapshot={"model_id": model_id, "parameters": parameters},
        role="candidate",
    )


def test_create_model_task_rejects_duplicate_model_id(tmp_path):
    registry = ModelTaskRegistry(tmp_path / "models")
    registry.create(_task())
    with pytest.raises(ValueError, match="duplicate model_id"):
        registry.create(_task())


def test_model_task_rejects_dsi_method():
    with pytest.raises(ValidationError):
        build_model_task(
            model_id="dsi_bad",
            display_name="dsi_bad",
            method="DSI",
            input_dataset_id="rho_training_v1",
            input_sha256="0" * 64,
            parameters={},
            config_snapshot={},
        )


def test_ensure_same_task_is_idempotent_but_different_config_fails(tmp_path):
    registry = ModelTaskRegistry(tmp_path / "models")
    task = _task()
    first, created_first = registry.ensure(task)
    second, created_second = registry.ensure(task)
    assert created_first is True
    assert created_second is False
    assert first.fingerprint == second.fingerprint
    with pytest.raises(ValueError, match="different configuration"):
        registry.ensure(_task(parameters={"resolution_xy_m": 10, "neighbor_count": 40}))


def test_select_models_uses_roles_and_keeps_rationale(tmp_path):
    default = _task("default_model")
    default = default.model_copy(update={"role": "default", "status": ModelStatus.SUCCEEDED})
    comparison = _task("comparison_model")
    comparison = comparison.model_copy(update={"role": "comparison"})
    selection = select_models([comparison, default])
    assert selection.default_model_id == "default_model"
    assert selection.comparison_model_id == "comparison_model"
    assert "single_overall_winner" in selection.rationale


def test_registry_list_ignores_selection_file(tmp_path):
    registry = ModelTaskRegistry(tmp_path / "models")
    default = _task("default_model").model_copy(update={"role": "default"})
    comparison = _task("comparison_model").model_copy(update={"role": "comparison"})
    registry.create(default)
    registry.create(comparison)
    selection = select_models([comparison, default])
    registry.save_selection(selection)
    assert [task.model_id for task in registry.list()] == ["comparison_model", "default_model"]
