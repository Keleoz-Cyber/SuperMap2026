from geomodeling.platform.property_semantics import normalize_property_unit
from geomodeling.platform.results import read_materialized_metadata
from geomodeling.platform import PlatformRuntime, tables
import json


def test_resistivity_preset_legacy_unit_is_normalized():
    assert normalize_property_unit(
        case_id="resistivity",
        workspace_kind="builtin_preset",
        value_name="RHO",
        value_unit="RHO 单位待来源确认",
    ) == "Ω·m"


def test_resistivity_preset_missing_unit_is_normalized():
    assert normalize_property_unit(
        case_id="resistivity",
        workspace_kind="builtin_preset",
        value_name="RHO",
        value_unit=None,
    ) == "Ω·m"


def test_user_upload_rho_unit_is_not_rewritten():
    assert normalize_property_unit(
        case_id="user-rho",
        workspace_kind="user_upload",
        value_name="RHO",
        value_unit="待确认",
    ) == "待确认"


def test_read_legacy_resistivity_metadata_uses_authoritative_unit(tmp_path):
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    with runtime.session() as session:
        session.add(tables.Case(id="resistivity", name="电阻率", case_type="generic"))
        session.flush()
        session.add(tables.Experiment(
            id="exp-rho", case_id="resistivity", name="旧实验",
            params_json='{"dataset_version_id":"ds-rho","algorithm":"idw"}',
        ))
        session.flush()
        session.add(tables.Run(id="run-rho", experiment_id="exp-rho", status="succeeded"))
        session.flush()
        session.add(tables.CandidateResult(
            id="result-rho", run_id="run-rho", status="succeeded",
            fingerprint="fp", params_json="{}", metrics_json="{}",
        ))
        session.commit()
    metadata_path = runtime.settings.result_grid("result-rho").parent / "metadata.json"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps({
        "property_name": "RHO", "units": "RHO 单位待来源确认"
    }), encoding="utf-8")

    assert read_materialized_metadata(runtime, "result-rho")["units"] == "Ω·m"
    runtime.close()
