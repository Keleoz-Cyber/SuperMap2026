from pathlib import Path

import yaml

HEADER = "         WL/2(km)          Vx"


def write_dat(path: Path, rows: list[str], trailing_nul: bool = True) -> Path:
    content = "\r\n".join([HEADER, *rows]) + "\r\n"
    data = content.encode("ascii")
    if trailing_nul:
        data += b"\x00"
    path.write_bytes(data)
    return path


def write_fixture_tree(base: Path) -> Path:
    data_dir = base / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    write_dat(data_dir / "W1.dat", ["        0.050000        0.524804", "        0.055556        0.438684", "        0.060000        0.500000"])
    write_dat(data_dir / "W2.dat", ["        0.050000        1.#QNAN0", "        0.055556        0.400000"])
    write_dat(data_dir / "WA.dat", ["        0.100000        1.000000", "        0.200000        2.000000"], trailing_nul=False)
    return data_dir


def write_fixture_config(base: Path, data_dir: Path, **overrides) -> Path:
    expected = {
        "dat_file_count": 3,
        "nul_terminator_count": 2,
        "line_point_counts": {"L1": 2, "L2": 1},
        "source_record_counts": {"L1": 5, "L2": 2},
        "source_record_total": 7,
        "valid_numeric_counts": {"L1": 4, "L2": 2},
        "valid_numeric_total": 6,
        "invalid_numeric_total": 1,
        "special_nan_token": "1.#QNAN0",
        "special_nan_point": "W2",
        "paper_counts": {"L1": 5, "L2": 1, "total": 6},
    }
    expected.update(overrides.pop("expected", {}))
    config = {
        "project": {"name": "GeoModelingPlatform", "version": "0.2a"},
        "source": {
            "data_dir": str(data_dir),
            "interval_workbook": "点间距.xlsx",
            "paper_reference": "fixture-paper.pdf",
            "line_map_image": "fixture-lines.jpg",
            "source_unit": "WL/2(km); Vx km/s",
        },
        "lines": [
            {
                "line_id": "L1",
                "point_start": "W1",
                "point_end": "W2",
                "points": [
                    {"point_id": "W1", "source_file": "W1.dat"},
                    {"point_id": "W2", "source_file": "W2.dat"},
                ],
            },
            {
                "line_id": "L2",
                "point_start": "WA",
                "point_end": "WA",
                "points": [{"point_id": "WA", "source_file": "WA.dat"}],
            },
        ],
        "intervals_m": {"L1": [{"from": "W1", "to": "W2", "distance_m": 100}], "L2": []},
        "excluded_points": [
            {
                "point_id": "W99",
                "line_id": "L1",
                "conflict_interval_m": 350,
                "interval_from": "W2",
                "reason": "fixture conflict-only point",
                "issue_code": "L3_W28_SOURCE_CONFLICT",
            }
        ],
        "local_coordinates": [
            {"point_id": "W1", "x_local_m": 0, "y_local_m": 220},
            {"point_id": "W2", "x_local_m": 100, "y_local_m": 220},
            {"point_id": "WA", "x_local_m": 0, "y_local_m": 0},
        ],
        "derivation": {
            "rule_version": "microseismic_local_3d_v0.2b_confirmed_2026-07-20",
            "adapter_version": "0.5.0",
            "depth_multiplier": 1000.0,
            "z_multiplier": -1.0,
            "vx_unit": "km/s",
            "sigma_threshold": 3.0,
            "sigma_ddof": 1,
            "aggregation_method": "arithmetic_mean_exact_xyz",
            # Fixture-specific contract: the fixture's 6 finite rows yield no
            # 3-sigma rejections and no exact-xyz conflicts. Never copy the
            # real 2006/1925/80/1911 counts into this portable fixture.
            "expected_rejected": 0,
            "expected_accepted": 6,
            "expected_conflict_groups": 0,
            "expected_conflict_rows": 0,
            "expected_modeling_nodes": 6,
            # Provisional fixture-only golden pins (sha256 of the fixture's
            # accepted sample-id list and of its empty rejected set). Task 4/5
            # must re-pin these to the computed canonical-byte hashes once the
            # canonical CSV serializer exists.
            "golden": {
                "accepted_sha256": "5ec0fdb46865423c165f570ed6314ce6935d519e57a2a3e93235e585b04b83dc",
                "rejected_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            },
        },
        "expected": expected,
        "cleaning_conflicts": {
            "outlier_count_claim": 80,
            "rate_claim_percent": 3.59,
            "computed_rate_percent": 3.99,
            "method_a": "linear interpolation",
            "method_b": "nearest 5 point IDW",
        },
        "outputs": {"default_dir": str(base / "out")},
    }
    config_path = base / "microseismic_fixture.yaml"
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    return config_path
