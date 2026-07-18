import pytest
from pydantic import ValidationError

from geomodeling.config import load_config
from geomodeling.schemas import EvidenceLevel, ModelStatus, ResultCategory, SuperMapResultRegistration
from geomodeling.supermap import formal_results, verification_report, verify_supermap_results


def _enum_value(value):
    return getattr(value, "value", value)


def test_supermap_file_verification_marks_file_level_only(tmp_path):
    fake = tmp_path / "expore1.udbx"
    fake.write_bytes(b"fake udbx bytes")
    config = load_config()
    config.supermap["udbx_path"] = str(fake)
    records = verify_supermap_results(config, compute_hash=True)
    assert len(records) == 3
    assert all(record.file_verified for record in records)
    assert all(not record.dataset_verified for record in records)
    assert all(_enum_value(record.evidence_level) == EvidenceLevel.FILE_VERIFIED.value for record in records)
    formal = formal_results(records)
    assert [record.dataset for record in formal] == ["RHO_KRIG_FINAL_20M_40"]
    assert all(record.file_size_bytes == fake.stat().st_size for record in records)
    report = verification_report(config, records)
    assert report.file_exists is True
    assert report.file_verified is True
    assert report.dataset_verified is False


def test_supermap_missing_file_stays_declared(tmp_path):
    config = load_config()
    config.supermap["udbx_path"] = str(tmp_path / "missing.udbx")
    records = verify_supermap_results(config)
    assert all(not record.file_verified for record in records)
    assert all(_enum_value(record.evidence_level) == EvidenceLevel.DECLARED.value for record in records)
    report = verification_report(config, records)
    assert report.file_exists is False
    assert report.file_verified is False


def test_dataset_verified_cannot_be_faked_without_file():
    with pytest.raises(ValidationError):
        SuperMapResultRegistration(
            dataset="FAKE_DATASET_VERIFIED",
            model_id="rho_kriging_20m_n40_v1",
            dataset_type="voxel_grid",
            method="KRIGING_ORDINARY",
            datasource_alias="expore1",
            status=ModelStatus.SUCCEEDED,
            result_category=ResultCategory.FORMAL,
            object_count=1,
            openable=True,
            evidence_level=EvidenceLevel.DATASET_VERIFIED,
            file_verified=False,
            dataset_verified=True,
        )
