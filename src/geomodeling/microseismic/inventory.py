from __future__ import annotations

from pathlib import Path

from .config import MicroseismicConfig
from .parser import parse_dat_file
from .schemas import SourceFileManifestEntry, VelocitySample


def discover_dat_files(config: MicroseismicConfig) -> tuple[dict[str, Path], list[str]]:
    data_dir = config.data_dir
    found: dict[str, Path] = {}
    missing: list[str] = []
    for line, point in config.formal_points():
        candidate = data_dir / point.source_file
        if candidate.is_file():
            found[point.point_id] = candidate
        else:
            missing.append(point.source_file)
    return found, missing


def unexpected_dat_files(config: MicroseismicConfig) -> list[str]:
    data_dir = config.data_dir
    if not data_dir.is_dir():
        return []
    expected = {name.lower() for name in config.expected_file_names()}
    return sorted(path.name for path in data_dir.glob("*.dat") if path.name.lower() not in expected)


def snapshot_sha256(paths: list[Path]) -> dict[str, str]:
    from ..io import sha256_file

    return {str(path): sha256_file(path) for path in paths}


def build_inventory(
    config: MicroseismicConfig,
) -> tuple[list[SourceFileManifestEntry], list[VelocitySample], dict[str, list[str]]]:
    found, missing = discover_dat_files(config)
    manifest: list[SourceFileManifestEntry] = []
    samples: list[VelocitySample] = []
    problems = {"missing_files": missing, "unexpected_files": unexpected_dat_files(config)}
    for line, point in config.formal_points():
        path = found.get(point.point_id)
        if path is None:
            continue
        entry, file_samples = parse_dat_file(path, point.point_id, line.line_id)
        manifest.append(entry)
        samples.extend(file_samples)
    return manifest, samples, problems
