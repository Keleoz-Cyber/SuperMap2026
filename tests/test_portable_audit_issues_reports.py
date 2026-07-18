import json

from geomodeling.audit import AuditLogger
from geomodeling.config import load_config
from geomodeling.issues import current_issues
from geomodeling.reports import export_issues_markdown, export_view_configurations_markdown
from geomodeling.views import view_configurations_from_config


def test_audit_logger_writes_jsonl_and_redacts_sensitive_values(tmp_path):
    logger = AuditLogger(tmp_path / "logs")
    path = logger.log(
        command="unit-test",
        status="succeeded",
        inputs=[],
        parameters={"token": "secret-value", "safe": 1},
        supermap_version="iDesktopX 2026",
        outputs=[tmp_path / "out"],
    )
    record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert record["command"] == "unit-test"
    assert record["status"] == "succeeded"
    assert record["parameters"]["token"] == "<redacted>"
    assert record["parameters"]["safe"] == 1
    assert record["supermap_version"] == "iDesktopX 2026"


def test_current_issues_include_required_boundaries():
    config = load_config()
    issues = current_issues(config)
    codes = {issue.code for issue in issues}
    assert {
        "RHO_UNIT_PENDING",
        "LOCAL_CRS_EPSG_UNCONFIRMED",
        "VERTICAL_SLICE_UNVERIFIED",
        "NATIVE_ISOSURFACE_FAILED",
        "SUPERMAP_DATASET_VERIFICATION_BOUNDARY",
    }.issubset(codes)
    assert any(issue.code == "NATIVE_ISOSURFACE_FAILED" and issue.blocking for issue in issues)


def test_view_configuration_and_issue_reports_export(tmp_path):
    config = load_config()
    views = view_configurations_from_config(config, udbx_path="../Project/expore1.udbx")
    assert len(views) == 1
    view = views[0]
    assert view.dataset == "RHO_KRIG_FINAL_20M_40"
    assert view.threshold is not None
    assert view.threshold.demonstration_only is True
    assert view.vertical_slice_status == "unverified"
    assert view.isosurface_status == "failed"
    issue_path = export_issues_markdown(current_issues(config), tmp_path / "issues.md")
    view_path = export_view_configurations_markdown(views, tmp_path / "views.md")
    assert issue_path.exists()
    assert view_path.exists()
