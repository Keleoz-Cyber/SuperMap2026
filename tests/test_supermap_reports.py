from geomodeling.config import load_config
from geomodeling.reports import export_inventory_markdown, export_metrics_markdown, model_metadata_from_config
from geomodeling.schemas import EvidenceLevel, ModelStatus, ResultCategory
from geomodeling.supermap import formal_results, registrations_from_config, result_inventory, select_supermap_result_for_model


def test_supermap_config_registration_separates_failed_empty():
    config = load_config()
    records = registrations_from_config(config, udbx_path="D:/data/expore1.udbx")
    assert len(records) == 3
    assert all(record.evidence_level == EvidenceLevel.DECLARED for record in records)
    assert all(record.dataset_verified is False for record in records)
    formal = formal_results(records)
    assert [record.dataset for record in formal] == ["RHO_KRIG_FINAL_20M_40"]
    failed = {record.dataset: record for record in records if record.result_category == ResultCategory.FAILED_EMPTY}
    assert failed["RHO_ISO_77_K40"].status == ModelStatus.FAILED
    assert failed["RHO_ISO_HIGH_P95_K40"].object_count == 0
    inventory = result_inventory(records)
    assert len(inventory) == 3
    assert all(item.supermap_dataset for item in inventory)


def test_reports_and_model_metadata_export(tmp_path):
    config = load_config()
    records = registrations_from_config(config, udbx_path="D:/data/expore1.udbx")
    model = next(item for item in config.models if item["model_id"] == "rho_kriging_20m_n40_v1")
    metadata = model_metadata_from_config(
        model,
        "rho_training_v1",
        "0" * 64,
        select_supermap_result_for_model(records, model["model_id"]),
    )
    assert metadata.status == ModelStatus.SUCCEEDED
    assert metadata.grid["rows"] == 7
    assert metadata.grid["columns"] == 23
    assert metadata.grid["bands"] == 42
    items = result_inventory(records)
    path = export_inventory_markdown(items, tmp_path / "inventory.md")
    assert path.exists()
