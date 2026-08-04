"""Preflight tests for ``scripts/install_supermap3d.py``.

The installer copies the verified SuperMap iClient3D 2026 (SuperMap3D 12.1)
runtime into ``web/public/SuperMap3D-2026`` and refuses to run unless the
required entries and the pinned ``SuperMap3D.js`` sha256 match. These tests
exercise the CLI against a minimal fake SDK tree.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "install_supermap3d.py"

SCRIPT_BYTES = b"// fake SuperMap3D runtime for preflight tests\n"
REQUIRED_DIRS = ("Assets", "Workers", "ThirdParty", "Widgets")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_sdk_tree(root: Path, script_bytes: bytes = SCRIPT_BYTES) -> str:
    """Create a minimal fake SDK tree; return the SuperMap3D.js sha256."""
    for name in REQUIRED_DIRS:
        (root / name).mkdir(parents=True)
    (root / "SuperMap3D.js").write_bytes(script_bytes)
    (root / "Widgets" / "widgets.css").write_bytes(b"/* fake widgets css */\n")
    return _sha256(root / "SuperMap3D.js")


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_install_copies_verified_tree(tmp_path: Path):
    source = tmp_path / "sdk"
    expected = _make_sdk_tree(source)
    destination = tmp_path / "web" / "public" / "SuperMap3D-2026"

    result = _run(
        "--source", str(source),
        "--destination", str(destination),
        "--expected-sha256", expected,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert (destination / "SuperMap3D.js").read_bytes() == SCRIPT_BYTES
    for entry in (*REQUIRED_DIRS, "Widgets/widgets.css"):
        assert (destination / entry).exists(), entry
    assert expected in result.stdout


def test_install_is_noop_when_destination_already_matches(tmp_path: Path):
    source = tmp_path / "sdk"
    expected = _make_sdk_tree(source)
    destination = tmp_path / "SuperMap3D-2026"
    _make_sdk_tree(destination)

    result = _run(
        "--source", str(source),
        "--destination", str(destination),
        "--expected-sha256", expected,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert (destination / "SuperMap3D.js").read_bytes() == SCRIPT_BYTES


def test_install_refuses_different_existing_tree_without_replace(tmp_path: Path):
    source = tmp_path / "sdk"
    expected = _make_sdk_tree(source)
    destination = tmp_path / "SuperMap3D-2026"
    _make_sdk_tree(destination, script_bytes=b"// older runtime\n")

    result = _run(
        "--source", str(source),
        "--destination", str(destination),
        "--expected-sha256", expected,
    )

    assert result.returncode != 0
    assert "--replace" in result.stderr + result.stdout
    assert (destination / "SuperMap3D.js").read_bytes() == b"// older runtime\n"


def test_install_replace_overwrites_different_existing_tree(tmp_path: Path):
    source = tmp_path / "sdk"
    expected = _make_sdk_tree(source)
    destination = tmp_path / "SuperMap3D-2026"
    _make_sdk_tree(destination, script_bytes=b"// older runtime\n")

    result = _run(
        "--source", str(source),
        "--destination", str(destination),
        "--expected-sha256", expected,
        "--replace",
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert (destination / "SuperMap3D.js").read_bytes() == SCRIPT_BYTES


def test_missing_required_directory_fails(tmp_path: Path):
    source = tmp_path / "sdk"
    expected = _make_sdk_tree(source)
    (source / "Workers").rename(source / "Workers-removed")
    destination = tmp_path / "SuperMap3D-2026"

    result = _run(
        "--source", str(source),
        "--destination", str(destination),
        "--expected-sha256", expected,
    )

    assert result.returncode != 0
    assert "Workers" in result.stderr + result.stdout
    assert not destination.exists()


def test_missing_widgets_css_fails(tmp_path: Path):
    source = tmp_path / "sdk"
    expected = _make_sdk_tree(source)
    (source / "Widgets" / "widgets.css").unlink()
    destination = tmp_path / "SuperMap3D-2026"

    result = _run(
        "--source", str(source),
        "--destination", str(destination),
        "--expected-sha256", expected,
    )

    assert result.returncode != 0
    assert "widgets.css" in result.stderr + result.stdout
    assert not destination.exists()


def test_wrong_expected_hash_fails_and_leaves_no_partial_copy(tmp_path: Path):
    source = tmp_path / "sdk"
    _make_sdk_tree(source)
    destination = tmp_path / "SuperMap3D-2026"

    result = _run(
        "--source", str(source),
        "--destination", str(destination),
        "--expected-sha256", "0" * 64,
    )

    assert result.returncode != 0
    assert not destination.exists()
    leftovers = [p for p in destination.parent.iterdir() if p.name != "sdk"]
    assert leftovers == []


def test_source_equal_destination_fails(tmp_path: Path):
    sdk = tmp_path / "sdk"
    expected = _make_sdk_tree(sdk)

    result = _run(
        "--source", str(sdk),
        "--destination", str(sdk),
        "--expected-sha256", expected,
    )

    assert result.returncode != 0
    combined = (result.stderr + result.stdout).lower()
    assert "source" in combined and "destination" in combined


def test_verify_only_accepts_valid_tree_without_source(tmp_path: Path):
    destination = tmp_path / "SuperMap3D-2026"
    expected = _make_sdk_tree(destination)

    result = _run(
        "--destination", str(destination),
        "--expected-sha256", expected,
        "--verify-only",
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert expected in result.stdout


def test_verify_only_rejects_wrong_hash(tmp_path: Path):
    destination = tmp_path / "SuperMap3D-2026"
    _make_sdk_tree(destination)

    result = _run(
        "--destination", str(destination),
        "--expected-sha256", "0" * 64,
        "--verify-only",
    )

    assert result.returncode != 0


def test_verify_only_fails_when_destination_missing(tmp_path: Path):
    destination = tmp_path / "SuperMap3D-2026"

    result = _run(
        "--destination", str(destination),
        "--expected-sha256", "0" * 64,
        "--verify-only",
    )

    assert result.returncode != 0
