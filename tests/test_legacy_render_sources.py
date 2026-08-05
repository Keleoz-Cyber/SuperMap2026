"""v0.6.1 Task 5: legacy resistivity authoritative regular-grid registration.

夹具是非对称规则网格（轴长 3/4/5），值公式 ``10000*i + 100*j + k``，CSV 行序
已确定性打乱——导入正确性绝不依赖 CSV 顺序。登记是原子的：暂存目录写
``grid.npz`` + ``metadata.json`` → 回读校验形状/值/哈希 → 原子改名为
``render-sources/builtin_legacy/<source_id>/<grid_sha256>/``，再原子写
``current.json``（只含逻辑身份与相对目录，绝无绝对输入路径）。拒收重复坐标、
缺失笛卡尔格点、不规则轴、非有限坐标与覆盖不同已登记网格；字节相同的重导入
幂等。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from geomodeling.cli import app as cli_app
from geomodeling.platform import PlatformRuntime
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.legacy_render_sources import (
    LEGACY_IMPORT_AXIS_IRREGULAR,
    LEGACY_IMPORT_COORDINATE_INVALID,
    LEGACY_IMPORT_DUPLICATE_COORDINATES,
    LEGACY_IMPORT_GRID_INCOMPLETE,
    LEGACY_RENDER_SOURCE_CONFLICT,
    LEGACY_RENDER_SOURCE_NOT_REGISTERED,
    import_legacy_grid,
    resolve_legacy_render_source,
)
from geomodeling.render_cli import render_app
from geomodeling.platform.render_coordinates import sha256_file

runner = CliRunner()

FIXTURE = Path(__file__).parent / "fixtures" / "legacy_rho_regular_grid.csv"

IMPORT_KWARGS = {
    "source_id": "resistivity",
    "x_column": "X",
    "y_column": "Y",
    "z_column": "Z",
    "value_column": "RHO",
    "property_name": "RHO",
    "units": "unknown",
}

EXPECTED_SHAPE = [3, 4, 5]
EXPECTED_X = [0.0, 20.0, 40.0]
EXPECTED_Y = [0.0, 20.0, 40.0, 60.0]
EXPECTED_Z = [-80.0, -60.0, -40.0, -20.0, 0.0]


@pytest.fixture
def runtime(tmp_path: Path):
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    try:
        yield runtime
    finally:
        runtime.close()


def _import(runtime: PlatformRuntime, csv_path: Path = FIXTURE, **overrides):
    kwargs = {**IMPORT_KWARGS, **overrides}
    return import_legacy_grid(runtime, csv_path=csv_path, **kwargs)


def _write_csv(tmp_path: Path, name: str, rows: list[str]) -> Path:
    path = tmp_path / name
    path.write_text("X,Y,Z,RHO\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return path


def _fixture_rows() -> list[str]:
    return FIXTURE.read_text(encoding="utf-8").splitlines()[1:]


def _source_root(runtime: PlatformRuntime, source_id: str = "resistivity") -> Path:
    return runtime.settings.render_sources_dir / "builtin_legacy" / source_id


def _read_current(runtime: PlatformRuntime, source_id: str = "resistivity") -> dict:
    return json.loads((_source_root(runtime, source_id) / "current.json").read_text(encoding="utf-8"))


def _load_grid(runtime: PlatformRuntime, source_id: str = "resistivity"):
    current = _read_current(runtime, source_id)
    grid_path = runtime.settings.render_sources_dir / current["artifact_dir"] / "grid.npz"
    bundle = np.load(grid_path, allow_pickle=True)
    return current, grid_path, bundle


def test_import_registers_authoritative_grid(runtime: PlatformRuntime) -> None:
    record = _import(runtime)
    assert record.source_kind == "builtin_legacy"
    assert record.source_id == "resistivity"
    assert record.shape == EXPECTED_SHAPE

    current, grid_path, bundle = _load_grid(runtime)
    axes = [np.asarray(axis, dtype="float64") for axis in bundle["axes"]]
    np.testing.assert_allclose(axes[0], EXPECTED_X)
    np.testing.assert_allclose(axes[1], EXPECTED_Y)
    np.testing.assert_allclose(axes[2], EXPECTED_Z)

    values = np.asarray(bundle["values"], dtype="float64")
    assert list(values.shape) == EXPECTED_SHAPE
    for i in range(3):
        for j in range(4):
            for k in range(5):
                # 无转置、无 Y 翻转：索引序即升序轴序
                assert values[i, j, k] == 10000 * i + 100 * j + k
    assert not np.asarray(bundle["is_nodata"], dtype=bool).any()

    grid_sha256 = sha256_file(grid_path)
    assert record.grid_sha256 == grid_sha256
    assert current["grid_sha256"] == grid_sha256
    assert current["source_id"] == "resistivity"
    assert current["property_name"] == "RHO"
    assert current["units"] == "unknown"
    assert current["shape"] == EXPECTED_SHAPE
    assert current["import_source_sha256"] == sha256_file(FIXTURE)
    # 工件目录内容寻址：builtin_legacy/resistivity/<grid_sha256>
    assert current["artifact_dir"] == f"builtin_legacy/resistivity/{grid_sha256}"
    assert grid_path.parent.name == grid_sha256


def test_current_json_has_no_absolute_input_path(runtime: PlatformRuntime, tmp_path: Path) -> None:
    _import(runtime)
    raw = (_source_root(runtime) / "current.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in raw
    assert str(FIXTURE) not in raw
    assert FIXTURE.name not in raw
    current = json.loads(raw)
    assert set(current) == {
        "source_id",
        "grid_sha256",
        "artifact_dir",
        "property_name",
        "units",
        "shape",
        "import_source_sha256",
    }


def test_reimport_identical_content_is_idempotent(runtime: PlatformRuntime) -> None:
    first = _import(runtime)
    current_path = _source_root(runtime) / "current.json"
    current_bytes = current_path.read_bytes()
    second = _import(runtime)
    assert second == first
    assert current_path.read_bytes() == current_bytes
    grid_dirs = [path for path in _source_root(runtime).iterdir() if path.is_dir()]
    assert len(grid_dirs) == 1
    # 暂存目录全部清理，无残留
    assert not list(runtime.settings.render_sources_dir.rglob(".import-*"))


def test_reject_duplicate_coordinates(runtime: PlatformRuntime, tmp_path: Path) -> None:
    rows = _fixture_rows()
    csv_path = _write_csv(tmp_path, "duplicate.csv", [*rows, rows[0]])
    with pytest.raises(PlatformError) as excinfo:
        _import(runtime, csv_path)
    assert excinfo.value.code == LEGACY_IMPORT_DUPLICATE_COORDINATES


def test_reject_missing_cartesian_cell(runtime: PlatformRuntime, tmp_path: Path) -> None:
    rows = _fixture_rows()
    csv_path = _write_csv(tmp_path, "missing.csv", rows[:-1])
    with pytest.raises(PlatformError) as excinfo:
        _import(runtime, csv_path)
    assert excinfo.value.code == LEGACY_IMPORT_GRID_INCOMPLETE


def test_reject_irregular_axis(runtime: PlatformRuntime, tmp_path: Path) -> None:
    rows = _fixture_rows()
    target = next(index for index, row in enumerate(rows) if row.startswith("40,"))
    rows[target] = rows[target].replace("40,", "41,", 1)
    csv_path = _write_csv(tmp_path, "irregular.csv", rows)
    with pytest.raises(PlatformError) as excinfo:
        _import(runtime, csv_path)
    assert excinfo.value.code == LEGACY_IMPORT_AXIS_IRREGULAR


def test_reject_non_finite_coordinates(runtime: PlatformRuntime, tmp_path: Path) -> None:
    rows = _fixture_rows()
    index = next(i for i, row in enumerate(rows) if row.startswith("0,0,"))
    rows[index] = "," + rows[index].split(",", 1)[1]
    csv_path = _write_csv(tmp_path, "nonfinite.csv", rows)
    with pytest.raises(PlatformError) as excinfo:
        _import(runtime, csv_path)
    assert excinfo.value.code == LEGACY_IMPORT_COORDINATE_INVALID


def test_reject_overwrite_of_different_grid(runtime: PlatformRuntime, tmp_path: Path) -> None:
    first = _import(runtime)
    rows = _fixture_rows()
    x, y, z, value = rows[0].split(",")
    rows[0] = f"{x},{y},{z},{float(value) + 0.5}"
    csv_path = _write_csv(tmp_path, "different.csv", rows)
    with pytest.raises(PlatformError) as excinfo:
        _import(runtime, csv_path)
    assert excinfo.value.code == LEGACY_RENDER_SOURCE_CONFLICT
    # 已登记网格与 current.json 保持原样
    assert _read_current(runtime)["grid_sha256"] == first.grid_sha256
    assert sha256_file(_load_grid(runtime)[1]) == first.grid_sha256
    assert not list(runtime.settings.render_sources_dir.rglob(".import-*"))


def test_failed_import_leaves_no_registry_state(runtime: PlatformRuntime, tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path, "missing.csv", _fixture_rows()[:-1])
    with pytest.raises(PlatformError):
        _import(runtime, csv_path)
    source_root = _source_root(runtime)
    assert not (source_root / "current.json").exists()
    survivors = [p for p in source_root.rglob("*") if p.is_dir()] if source_root.exists() else []
    assert survivors == []


def test_resolve_legacy_render_source(runtime: PlatformRuntime) -> None:
    record = _import(runtime)
    source = resolve_legacy_render_source(runtime, "resistivity")
    assert source.source_kind == "builtin_legacy"
    assert source.source_id == "resistivity"
    assert source.grid_sha256 == record.grid_sha256
    assert source.property_name == "RHO"
    assert source.units == "unknown"
    assert source.dimension == "3d"
    assert source.grid_path.is_file()


def test_resolve_unregistered_source_fails_closed(runtime: PlatformRuntime) -> None:
    with pytest.raises(PlatformError) as excinfo:
        resolve_legacy_render_source(runtime, "resistivity")
    assert excinfo.value.code == LEGACY_RENDER_SOURCE_NOT_REGISTERED


def test_render_cli_import_csv(tmp_path: Path) -> None:
    data_dir = tmp_path / "runtime"
    result = runner.invoke(
        render_app,
        [
            "import-csv",
            "--source-id", "resistivity",
            "--csv", str(FIXTURE),
            "--x", "X",
            "--y", "Y",
            "--z", "Z",
            "--value", "RHO",
            "--property-name", "RHO",
            "--units", "unknown",
            "--data-dir", str(data_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["source_kind"] == "builtin_legacy"
    assert payload["source_id"] == "resistivity"
    assert payload["shape"] == EXPECTED_SHAPE
    assert str(tmp_path) not in result.output
    current = json.loads(
        (data_dir / "render-sources" / "builtin_legacy" / "resistivity" / "current.json").read_text(encoding="utf-8")
    )
    assert current["grid_sha256"] == payload["grid_sha256"]


def test_render_cli_import_conflict_exits_one(tmp_path: Path) -> None:
    data_dir = tmp_path / "runtime"
    base_args = [
        "import-csv",
        "--source-id", "resistivity",
        "--x", "X",
        "--y", "Y",
        "--z", "Z",
        "--value", "RHO",
        "--property-name", "RHO",
        "--units", "unknown",
        "--data-dir", str(data_dir),
    ]
    assert runner.invoke(render_app, [*base_args, "--csv", str(FIXTURE)]).exit_code == 0
    rows = _fixture_rows()
    x, y, z, value = rows[0].split(",")
    rows[0] = f"{x},{y},{z},{float(value) + 0.5}"
    csv_path = _write_csv(tmp_path, "different.csv", rows)
    result = runner.invoke(render_app, [*base_args, "--csv", str(csv_path)])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error"]["code"] == LEGACY_RENDER_SOURCE_CONFLICT
    assert str(tmp_path) not in result.output


def test_render_grid_group_registered_on_main_cli() -> None:
    result = runner.invoke(cli_app, ["render-grid", "--help"])
    assert result.exit_code == 0
    assert "import-csv" in result.output


def test_render_cli_help_lists_import_csv() -> None:
    result = runner.invoke(render_app, ["--help"])
    assert result.exit_code == 0
    assert "import-csv" in result.output
