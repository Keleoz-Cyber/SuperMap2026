from __future__ import annotations

from pathlib import Path

from .config import MicroseismicConfig
from .parser import parse_dat_file
from .schemas import SourceFileManifestEntry, VelocitySample


def _source_dir(config: MicroseismicConfig, data_dir: str | Path | None) -> Path:
    """Explicit source directory wins; the default stays config.data_dir."""
    if data_dir is None:
        return config.data_dir
    return Path(data_dir)


def discover_dat_files(
    config: MicroseismicConfig,
    data_dir: str | Path | None = None,
) -> tuple[dict[str, Path], list[str]]:
    source_dir = _source_dir(config, data_dir)
    found: dict[str, Path] = {}
    missing: list[str] = []
    for line, point in config.formal_points():
        candidate = source_dir / point.source_file
        if candidate.is_file():
            found[point.point_id] = candidate
        else:
            missing.append(point.source_file)
    return found, missing


def unexpected_dat_files(config: MicroseismicConfig, data_dir: str | Path | None = None) -> list[str]:
    source_dir = _source_dir(config, data_dir)
    if not source_dir.is_dir():
        return []
    expected = {name.lower() for name in config.expected_file_names()}
    return sorted(path.name for path in source_dir.glob("*.dat") if path.name.lower() not in expected)


def snapshot_sha256(paths: list[Path]) -> dict[str, str]:
    from ..io import sha256_file

    return {str(path): sha256_file(path) for path in paths}


def build_inventory(
    config: MicroseismicConfig,
    data_dir: str | Path | None = None,
) -> tuple[list[SourceFileManifestEntry], list[VelocitySample], dict[str, list[str]]]:
    found, missing = discover_dat_files(config, data_dir=data_dir)
    manifest: list[SourceFileManifestEntry] = []
    samples: list[VelocitySample] = []
    problems = {"missing_files": missing, "unexpected_files": unexpected_dat_files(config, data_dir=data_dir)}
    for line, point in config.formal_points():
        path = found.get(point.point_id)
        if path is None:
            continue
        entry, file_samples = parse_dat_file(path, point.point_id, line.line_id)
        manifest.append(entry)
        samples.extend(file_samples)
    return manifest, samples, problems
