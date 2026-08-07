"""Task 14 contract tests: experiment integration and candidate fingerprints.

创建契约：Kriging 专业模式要求匹配成功诊断的不可变确认（数据集不匹配
409 ``PROFESSIONAL_CONFIRMATION_DATASET_MISMATCH``）；IDW 携带确认一律
409（``PROFESSIONAL_CAPABILITY_NOT_APPLICABLE``）；Kriging 携带邻域/经验
不确定性但缺确认 → 409 ``PROFESSIONAL_CONFIRMATION_REQUIRED``；legacy
（三字段全缺）行为与指纹逐位不变。

候选指纹：标准化数据 SHA-256、算法、确认快照指纹、Kriging 各向异性变换、
搜索邻域、折分计划指纹与不确定性配置的规范化哈希——同输入同指纹，改
邻域/确认必变指纹。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from geomodeling.modeling.anisotropy import KrigingAnisotropySpec
from geomodeling.modeling.professional_contracts import (
    EmpiricalUncertaintySpec,
    NeighborhoodSpec,
)
from geomodeling.platform import PlatformRuntime, tables
from geomodeling.platform.errors import PlatformError, platform_error_handler

# ---------------------------------------------------------------------------
# 夹具：运行时 / API / 诊断与确认 / 有效实验载荷
# ---------------------------------------------------------------------------

AUTO_CONFIG = {
    "model": "spherical",
    "parameter_strategy": "automatic_candidate",
    "parameter_origin": "automatic_candidate",
    "fitted_models_sha256": "e" * 64,
    "anisotropy": {"keep_isotropic": True},
}

MANUAL_CONFIG = {
    "model": "spherical",
    "parameter_strategy": "manual",
    "parameter_origin": "manual_confirmed",
    "prior": "user_prior",
    "manual_parameters": {"nugget": 0.05, "sill": 3.0, "range": 120.0},
    "anisotropy": {
        "keep_isotropic": False,
        "azimuth_deg": 90.0,
        "dip_deg": None,
        "roll_deg": None,
        "major_minor_ratio": 6.0,
        "major_vertical_ratio": None,
        "candidate_rank": 1,
        "anisotropy_candidates_sha256": "d" * 64,
    },
}

NEIGHBORHOOD_2D = {"radii": [100.0, 50.0], "azimuth_deg": 45.0}
EMPIRICAL_UNCERTAINTY = {"min_neighbors": 2, "max_neighbors": 8, "power": 2.0}


@dataclass(frozen=True)
class DiagnosisSetup:
    case_id: str
    dataset_id: str
    other_dataset_id: str
    diagnosis_id: str
    confirmation_id: str
    manual_confirmation_id: str
    failed_confirmation_id: str


@pytest.fixture
def runtime(tmp_path: Path) -> PlatformRuntime:
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    return runtime


@pytest.fixture
def api(runtime: PlatformRuntime) -> TestClient:
    from geomodeling.api.routes import experiments

    app = FastAPI()
    app.add_exception_handler(PlatformError, platform_error_handler)
    app.include_router(experiments.router)
    app.state.platform_runtime = runtime
    return TestClient(app)


def _profile() -> dict:
    return {
        "mapping": {
            "dimension": "2d",
            "x": "x",
            "y": "y",
            "value": "value",
            "value_name": "属性",
            "coordinate_kind": "local_linear",
        },
        "source_sha256": "a" * 64,
        "standardized_sha256": "b" * 64,
        "quality": {"status": "passed", "confirmed": True},
    }


@pytest.fixture
def diagnosis(runtime: PlatformRuntime) -> DiagnosisSetup:
    """两个已验证数据集 + 一条成功诊断（挂两条确认快照）+ 一条失败诊断。"""

    case_id, dataset_id, other_dataset_id = "c1", "ds1", "ds2"
    with runtime.session() as session:
        session.add(
            tables.Case(id=case_id, name="专业案例", case_type="generic", config_json="{}")
        )
        for version, ds in ((1, dataset_id), (2, other_dataset_id)):
            session.add(
                tables.DatasetVersion(
                    id=ds,
                    case_id=case_id,
                    version=version,
                    status="validated",
                    source_path="x.csv",
                    profile_json=tables.dumps_canonical(_profile()),
                )
            )
        session.add(
            tables.ProfessionalDiagnostic(
                id="diag-1",
                dataset_version_id=dataset_id,
                status="succeeded",
                config_json="{}",
                fingerprint="a" * 64,
                manifest_json="{}",
            )
        )
        # 失败诊断上的确认（真实流程不可达，防御校验必须拒绝）
        session.add(
            tables.ProfessionalDiagnostic(
                id="diag-failed",
                dataset_version_id=dataset_id,
                status="failed",
                config_json="{}",
                fingerprint="b" * 64,
                manifest_json="{}",
            )
        )
        session.commit()
        session.add(
            tables.ProfessionalConfirmation(
                id="conf-auto",
                diagnostic_id="diag-1",
                config_json=tables.dumps_canonical(AUTO_CONFIG),
                fingerprint="f" * 64,
                note="采纳自动候选",
            )
        )
        session.add(
            tables.ProfessionalConfirmation(
                id="conf-manual",
                diagnostic_id="diag-1",
                config_json=tables.dumps_canonical(MANUAL_CONFIG),
                fingerprint="0" * 64,
                note="人工固定参数",
            )
        )
        session.add(
            tables.ProfessionalConfirmation(
                id="conf-failed",
                diagnostic_id="diag-failed",
                config_json=tables.dumps_canonical(AUTO_CONFIG),
                fingerprint="1" * 64,
                note="失败诊断的确认",
            )
        )
        session.commit()
    return DiagnosisSetup(
        case_id=case_id,
        dataset_id=dataset_id,
        other_dataset_id=other_dataset_id,
        diagnosis_id="diag-1",
        confirmation_id="conf-auto",
        manual_confirmation_id="conf-manual",
        failed_confirmation_id="conf-failed",
    )


@pytest.fixture
def valid_experiment_payload():
    def build(*, case_id: str, dataset_version_id: str, algorithm: str, **overrides):
        parameters = (
            {"neighbor_count": 8}
            if algorithm == "ordinary_kriging"
            else {"power": 2.0, "neighbor_count": 8}
        )
        payload = {
            "case_id": case_id,
            "name": "专业实验",
            "algorithm": algorithm,
            "dataset_version_id": dataset_version_id,
            "search_mode": "manual",
            "parameters": parameters,
            "validation": {
                "method": "spatial_kfold",
                "folds": 3,
                "seed": 11,
                "holdout_fraction": 0.2,
            },
            "grid": None,
        }
        payload.update(overrides)
        return payload

    return build


# ---------------------------------------------------------------------------
# 创建契约：确认匹配 / 能力适用 / legacy 不变
# ---------------------------------------------------------------------------


class TestProfessionalExperimentCreation:
    def test_kriging_professional_experiment_requires_matching_confirmation(
        self, api, diagnosis, valid_experiment_payload
    ):
        payload = valid_experiment_payload(
            case_id=diagnosis.case_id,
            dataset_version_id=diagnosis.other_dataset_id,
            algorithm="ordinary_kriging",
        )
        payload["professional_confirmation_id"] = diagnosis.confirmation_id
        response = api.post("/api/experiments", json=payload)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "PROFESSIONAL_CONFIRMATION_DATASET_MISMATCH"

    def test_matching_confirmation_creates_professional_kriging_experiment(
        self, api, diagnosis, valid_experiment_payload
    ):
        payload = valid_experiment_payload(
            case_id=diagnosis.case_id,
            dataset_version_id=diagnosis.dataset_id,
            algorithm="ordinary_kriging",
        )
        payload["professional_confirmation_id"] = diagnosis.confirmation_id
        payload["neighborhood"] = NEIGHBORHOOD_2D
        payload["empirical_uncertainty"] = EMPIRICAL_UNCERTAINTY
        response = api.post("/api/experiments", json=payload)
        assert response.status_code == 201, response.text

        params = response.json()["params"]
        professional = params["professional"]
        assert professional["confirmation_id"] == diagnosis.confirmation_id
        assert professional["confirmation_fingerprint"] == "f" * 64
        assert professional["model"] == "spherical"
        assert professional["parameter_strategy"] == "automatic_candidate"
        # 保持各向同性确认 → 规范各向同性变换（azimuth 0、比例全 1）
        anisotropy = professional["anisotropy"]
        assert anisotropy["dimension"] == "2d"
        assert anisotropy["azimuth_deg"] == 0.0
        assert anisotropy["major_scale"] == 1.0
        assert anisotropy["minor_scale"] == 1.0
        # 邻域与不确定性配置规范化落库（含默认值补全）
        assert professional["neighborhood"]["radii"] == [100.0, 50.0]
        assert professional["neighborhood"]["azimuth_deg"] == 45.0
        assert professional["neighborhood"]["min_neighbors"] == 3
        assert professional["empirical_uncertainty"]["min_neighbors"] == 2
        assert professional["empirical_uncertainty"]["power"] == 2.0

    def test_manual_confirmation_lands_fixed_triple_and_ratio_transform(
        self, api, diagnosis, valid_experiment_payload
    ):
        payload = valid_experiment_payload(
            case_id=diagnosis.case_id,
            dataset_version_id=diagnosis.dataset_id,
            algorithm="ordinary_kriging",
        )
        payload["professional_confirmation_id"] = diagnosis.manual_confirmation_id
        response = api.post("/api/experiments", json=payload)
        assert response.status_code == 201, response.text

        professional = response.json()["params"]["professional"]
        assert professional["parameter_strategy"] == "manual"
        # 固定 nugget/sill/range 标记 user prior（§6.4）
        assert professional["manual_parameters"] == {"nugget": 0.05, "sill": 3.0, "range": 120.0}
        anisotropy = professional["anisotropy"]
        assert anisotropy["azimuth_deg"] == 90.0
        # 主/次 range 比 6.0 → 次向尺度比取倒数
        assert anisotropy["minor_scale"] == pytest.approx(1.0 / 6.0)

    def test_idw_rejects_kriging_confirmation(self, api, diagnosis, valid_experiment_payload):
        payload = valid_experiment_payload(
            case_id=diagnosis.case_id,
            dataset_version_id=diagnosis.dataset_id,
            algorithm="idw",
        )
        payload["professional_confirmation_id"] = diagnosis.confirmation_id
        response = api.post("/api/experiments", json=payload)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "PROFESSIONAL_CAPABILITY_NOT_APPLICABLE"

    def test_kriging_neighborhood_without_confirmation_is_rejected(
        self, api, diagnosis, valid_experiment_payload
    ):
        payload = valid_experiment_payload(
            case_id=diagnosis.case_id,
            dataset_version_id=diagnosis.dataset_id,
            algorithm="ordinary_kriging",
        )
        payload["neighborhood"] = NEIGHBORHOOD_2D
        response = api.post("/api/experiments", json=payload)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "PROFESSIONAL_CONFIRMATION_REQUIRED"

    def test_unknown_confirmation_is_404(self, api, diagnosis, valid_experiment_payload):
        payload = valid_experiment_payload(
            case_id=diagnosis.case_id,
            dataset_version_id=diagnosis.dataset_id,
            algorithm="ordinary_kriging",
        )
        payload["professional_confirmation_id"] = "ghost"
        response = api.post("/api/experiments", json=payload)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "PROFESSIONAL_CONFIRMATION_NOT_FOUND"

    def test_confirmation_of_failed_diagnosis_is_rejected(
        self, api, diagnosis, valid_experiment_payload
    ):
        payload = valid_experiment_payload(
            case_id=diagnosis.case_id,
            dataset_version_id=diagnosis.dataset_id,
            algorithm="ordinary_kriging",
        )
        payload["professional_confirmation_id"] = diagnosis.failed_confirmation_id
        response = api.post("/api/experiments", json=payload)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "PROFESSIONAL_DIAGNOSIS_NOT_SUCCEEDED"

    def test_legacy_z_scale_conflicts_with_confirmation_anisotropy(
        self, api, diagnosis, valid_experiment_payload
    ):
        payload = valid_experiment_payload(
            case_id=diagnosis.case_id,
            dataset_version_id=diagnosis.dataset_id,
            algorithm="ordinary_kriging",
            parameters={"neighbor_count": 8, "z_scale": 2.0},
        )
        payload["professional_confirmation_id"] = diagnosis.confirmation_id
        response = api.post("/api/experiments", json=payload)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "PROFESSIONAL_Z_SCALE_CONFLICT"

    def test_idw_neighborhood_and_uncertainty_create_professional_experiment(
        self, api, diagnosis, valid_experiment_payload
    ):
        payload = valid_experiment_payload(
            case_id=diagnosis.case_id,
            dataset_version_id=diagnosis.dataset_id,
            algorithm="idw",
        )
        payload["neighborhood"] = NEIGHBORHOOD_2D
        payload["empirical_uncertainty"] = EMPIRICAL_UNCERTAINTY
        response = api.post("/api/experiments", json=payload)
        assert response.status_code == 201, response.text

        professional = response.json()["params"]["professional"]
        assert professional["confirmation_id"] is None
        assert professional["confirmation_fingerprint"] is None
        assert professional["anisotropy"] is None
        assert professional["neighborhood"]["radii"] == [100.0, 50.0]
        assert professional["empirical_uncertainty"]["max_neighbors"] == 8

    def test_invalid_neighborhood_payload_is_rejected(self, api, diagnosis, valid_experiment_payload):
        payload = valid_experiment_payload(
            case_id=diagnosis.case_id,
            dataset_version_id=diagnosis.dataset_id,
            algorithm="idw",
        )
        payload["neighborhood"] = {"radii": [0.0, 50.0]}  # 半径必须 > 0
        response = api.post("/api/experiments", json=payload)
        # 与 platform.professional 的诊断/异常配置失败一致：非法配置 400
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "PROFESSIONAL_CONFIG_INVALID"

    def test_legacy_experiment_creation_unchanged(self, api, diagnosis, valid_experiment_payload):
        payload = valid_experiment_payload(
            case_id=diagnosis.case_id,
            dataset_version_id=diagnosis.dataset_id,
            algorithm="idw",
        )
        response = api.post("/api/experiments", json=payload)
        assert response.status_code == 201, response.text
        params = response.json()["params"]
        # legacy 载荷不落任何专业键：行为与指纹逐位不变
        assert set(params) == {
            "algorithm",
            "dataset_version_id",
            "search_mode",
            "parameters",
            "validation",
            "grid",
        }


# ---------------------------------------------------------------------------
# 候选指纹与参数落地（expand_candidates 纯函数层）
# ---------------------------------------------------------------------------

ISOTROPIC_2D = KrigingAnisotropySpec.isotropic("2d").model_dump(mode="json")
NEIGHBORHOOD_CANONICAL = NeighborhoodSpec(
    radii=(100.0, 50.0), azimuth_deg=45.0
).model_dump(mode="json")
UNCERTAINTY_CANONICAL = EmpiricalUncertaintySpec(
    min_neighbors=2, max_neighbors=8
).model_dump(mode="json")

VALIDATION = {"method": "spatial_kfold", "folds": 3, "seed": 11, "holdout_fraction": 0.2}


def professional_search(**professional_overrides) -> dict:
    professional = {
        "confirmation_id": "conf-1",
        "confirmation_fingerprint": "f" * 64,
        "model": "spherical",
        "parameter_strategy": "automatic_candidate",
        "manual_parameters": None,
        "anisotropy": ISOTROPIC_2D,
        "neighborhood": NEIGHBORHOOD_CANONICAL,
        "empirical_uncertainty": UNCERTAINTY_CANONICAL,
        "dataset_sha256": "b" * 64,
        "validation_fingerprint": "c" * 64,
    }
    professional.update(professional_overrides)
    return {
        "algorithm": "ordinary_kriging",
        "search_mode": "manual",
        "parameters": {"neighbor_count": 8},
        "validation": VALIDATION,
        "grid": None,
        "professional": professional,
    }


class TestCandidateFingerprint:
    def test_same_input_produces_same_fingerprint(self):
        from geomodeling.platform.experiments import expand_candidates

        first = expand_candidates(professional_search())
        second = expand_candidates(professional_search())
        assert [c.fingerprint for c in first] == [c.fingerprint for c in second]
        assert len(first[0].fingerprint) == 64

    def test_fingerprint_changes_with_neighborhood(self):
        from geomodeling.platform.experiments import expand_candidates

        baseline = expand_candidates(professional_search())[0].fingerprint
        changed = NeighborhoodSpec(radii=(200.0, 50.0), azimuth_deg=45.0).model_dump(mode="json")
        mutated = expand_candidates(professional_search(neighborhood=changed))[0].fingerprint
        assert mutated != baseline

    def test_fingerprint_changes_with_confirmation(self):
        from geomodeling.platform.experiments import expand_candidates

        baseline = expand_candidates(professional_search())[0].fingerprint
        mutated = expand_candidates(
            professional_search(confirmation_id="conf-2", confirmation_fingerprint="9" * 64)
        )[0].fingerprint
        assert mutated != baseline

    def test_legacy_fingerprint_bitwise_unchanged(self):
        """legacy 载荷逐位锁定：algorithm/parameters/grid/validation 规范化哈希。"""

        from geomodeling.platform.experiments import expand_candidates

        search = {
            "algorithm": "idw",
            "search_mode": "manual",
            "parameters": {"power": 2.0, "neighbor_count": 8},
            "validation": VALIDATION,
            "grid": None,
        }
        expected_payload = {
            "algorithm": "idw",
            "parameters": {"power": 2.0, "neighbor_count": 8},
            "grid": None,
            "validation": VALIDATION,
        }
        expected = hashlib.sha256(
            json.dumps(expected_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            .encode("utf-8")
        ).hexdigest()
        assert expand_candidates(search)[0].fingerprint == expected


class TestProfessionalParameterLanding:
    def test_automatic_strategy_merges_model_transform_and_neighborhood(self):
        from geomodeling.modeling.kriging import KrigingParameters
        from geomodeling.platform.experiments import expand_candidates

        candidate = expand_candidates(professional_search())[0]
        merged = candidate.parameters
        assert merged["variogram_model"] == "spherical"
        assert merged["variogram_mode"] == "auto"  # 折内 auto 拟合
        assert merged["anisotropy"] == ISOTROPIC_2D
        assert merged["neighborhood"] == NEIGHBORHOOD_CANONICAL
        assert merged["neighbor_count"] == 8
        # 合并结果必须直接进入 Kriging 参数契约
        KrigingParameters.model_validate(merged)

    def test_automatic_strategy_overrides_manual_triple(self):
        from geomodeling.platform.experiments import expand_candidates

        search = professional_search()
        search["parameters"] = {
            "neighbor_count": 8,
            "variogram_mode": "manual",
            "nugget": 0.1,
            "sill": 2.0,
            "range": 50.0,
        }
        merged = expand_candidates(search)[0].parameters
        assert merged["variogram_mode"] == "auto"
        for key in ("nugget", "sill", "range"):
            assert key not in merged

    def test_manual_strategy_lands_fixed_triple_marked_user_prior(self):
        from geomodeling.modeling.kriging import KrigingParameters
        from geomodeling.platform.experiments import expand_candidates

        anisotropy = KrigingAnisotropySpec(
            dimension="2d", azimuth_deg=90.0, major_scale=1.0, minor_scale=1.0 / 6.0
        ).model_dump(mode="json")
        search = professional_search(
            parameter_strategy="manual",
            manual_parameters={"nugget": 0.05, "sill": 3.0, "range": 120.0},
            anisotropy=anisotropy,
        )
        merged = expand_candidates(search)[0].parameters
        assert merged["variogram_mode"] == "manual"
        assert merged["nugget"] == 0.05
        assert merged["sill"] == 3.0
        assert merged["range"] == 120.0
        assert merged["anisotropy"] == anisotropy
        KrigingParameters.model_validate(merged)

    def test_idw_merges_neighborhood_only(self):
        from geomodeling.modeling.idw import IDWParameters
        from geomodeling.platform.experiments import expand_candidates

        search = professional_search(
            confirmation_id=None,
            confirmation_fingerprint=None,
            model=None,
            parameter_strategy=None,
            manual_parameters=None,
            anisotropy=None,
        )
        search["algorithm"] = "idw"
        search["parameters"] = {"power": 2.0, "neighbor_count": 8}
        merged = expand_candidates(search)[0].parameters
        assert merged["neighborhood"] == NEIGHBORHOOD_CANONICAL
        assert merged["power"] == 2.0
        for key in ("variogram_model", "variogram_mode", "anisotropy"):
            assert key not in merged
        IDWParameters.model_validate(merged)


# ---------------------------------------------------------------------------
# Task 1: Normalize horizontal-only 3D confirmation geometry
# ---------------------------------------------------------------------------


def test_horizontal_only_3d_confirmation_uses_neutral_vertical_defaults():
    """3D confirmation with null dip/roll/vertical_ratio normalizes to neutral defaults."""
    from geomodeling.platform.experiments import _confirmation_anisotropy_spec

    spec = _confirmation_anisotropy_spec(
        {
            "keep_isotropic": False,
            "azimuth_deg": 90.0,
            "dip_deg": None,
            "roll_deg": None,
            "major_minor_ratio": 2.0,
            "major_vertical_ratio": None,
        },
        "3d",
    )
    assert spec.azimuth_deg == 90.0
    assert spec.dip_deg == 0.0
    assert spec.roll_deg == 0.0
    assert spec.major_scale == 1.0
    assert spec.minor_scale == 0.5
    assert spec.vertical_scale == 1.0


@pytest.mark.parametrize(
    "field,value",
    [
        ("major_minor_ratio", 0.0),
        ("major_minor_ratio", -1.0),
        ("major_minor_ratio", float("nan")),
        ("major_vertical_ratio", 0.0),
        ("major_vertical_ratio", float("inf")),
        ("azimuth_deg", float("nan")),
    ],
)
def test_confirmation_geometry_rejects_non_finite_or_non_positive_values(field, value):
    from geomodeling.platform.experiments import (
        PROFESSIONAL_CONFIG_INVALID,
        _confirmation_anisotropy_spec,
    )

    payload = {
        "keep_isotropic": False,
        "azimuth_deg": 45.0,
        "dip_deg": None,
        "roll_deg": None,
        "major_minor_ratio": 2.0,
        "major_vertical_ratio": None,
    }
    payload[field] = value
    with pytest.raises(PlatformError) as exc_info:
        _confirmation_anisotropy_spec(payload, "3d")
    assert exc_info.value.code == PROFESSIONAL_CONFIG_INVALID
