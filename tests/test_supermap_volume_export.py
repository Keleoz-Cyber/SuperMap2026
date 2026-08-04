from __future__ import annotations

import json
import math
import struct
import zipfile

import numpy as np

from geomodeling.platform import PlatformRuntime
import geomodeling.platform.supermap_volume as volume_export


def test_supermap_volume_export_writes_idempotent_geotiff_package(tmp_path, monkeypatch):
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    result_id = "result-volume"
    result_dir = runtime.settings.results_dir / result_id
    result_dir.mkdir(parents=True)

    axes = np.array(
        [np.array([-1.0, 0.0, 1.0]), np.array([10.0, 20.0, 30.0]), np.array([100.0, 110.0])],
        dtype=object,
    )
    values = np.arange(18, dtype=np.float64).reshape(3, 3, 2)
    is_nodata = np.zeros_like(values, dtype=bool)
    is_nodata[1, 1, 1] = True
    np.savez_compressed(result_dir / "grid.npz", axes=axes, values=values, is_nodata=is_nodata)
    metadata = {
        "dimension": "3d",
        "dataset_version_id": "dataset-1",
        "grid_sha256": volume_export._sha256(result_dir / "grid.npz"),
    }
    (result_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    monkeypatch.setattr(volume_export, "materialize", lambda _runtime, _result_id: metadata)

    first = volume_export.export_supermap_volume(runtime, result_id)
    second = volume_export.export_supermap_volume(runtime, result_id)

    assert first["export_id"] == second["export_id"]
    assert first["package_sha256"] == second["package_sha256"]
    manifest = first["manifest"]
    assert manifest["shape"] == [3, 3, 2]
    assert manifest["version"] == 2
    assert manifest["coordinate_contract"] == "wgs84_display_anchor_v1"
    assert manifest["geolocation_status"] == "display_anchor_only"
    assert manifest["model_coordinate_contract"]["axis_spacing"] == [1.0, 10.0, 10.0]
    assert manifest["render_coordinate_contract"]["epsg"] == 4326
    assert manifest["render_coordinate_contract"]["anchor"] == {
        "longitude": 120.0,
        "latitude": 30.0,
        "height": 0.0,
    }
    assert math.isclose(manifest["axis_min"][0], 120.0 - manifest["axis_spacing"][0])
    assert math.isclose(manifest["axis_max"][0], 120.0 + manifest["axis_spacing"][0])
    assert math.isclose(manifest["axis_min"][1], 30.0 - manifest["axis_spacing"][1])
    assert math.isclose(manifest["axis_max"][1], 30.0 + manifest["axis_spacing"][1])
    assert manifest["axis_spacing"][2] == 10.0
    assert len(first["manifest"]["slices"]) == 2

    package = runtime.settings.supermap_volume_package(first["export_id"])
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        assert "manifest.json" in names
        assert "checksums.sha256" in names
        assert "slices/z_0000.tif" in names
        geotiff = archive.read("slices/z_0000.tif")
        assert geotiff[:4] == b"II*\x00"
        ifd_offset = struct.unpack_from("<I", geotiff, 4)[0]
        entry_count = struct.unpack_from("<H", geotiff, ifd_offset)[0]
        tags = {
            struct.unpack_from("<H", geotiff, ifd_offset + 2 + index * 12)[0]
            for index in range(entry_count)
        }
        assert 34735 in tags
