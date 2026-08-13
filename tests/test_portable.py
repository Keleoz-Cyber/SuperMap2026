from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from geomodeling.portable import (
    ORIGIN_FILE,
    TEMPLATE_ROOT_MARKER,
    PortableError,
    PortableLayout,
    _is_this_platform,
    initialize_runtime,
    relocate_runtime,
    verify_manifest,
)


def test_health_identity_requires_exact_version() -> None:
    assert _is_this_platform({"status": "ok", "version": "0.9.2"})
    assert not _is_this_platform({"status": "ok", "version": "0.9.0"})
    assert not _is_this_platform({"status": "healthy", "version": "0.9.2"})


def test_template_root_marker_is_not_an_absolute_machine_path() -> None:
    assert not Path(TEMPLATE_ROOT_MARKER).is_absolute()
    assert ":" not in TEMPLATE_ROOT_MARKER


def _layout(tmp_path: Path) -> PortableLayout:
    root = tmp_path / "package"
    root.mkdir()
    template = tmp_path / "resources" / "runtime-template"
    template.mkdir(parents=True)
    frontend = tmp_path / "resources" / "web" / "dist"
    frontend.mkdir(parents=True)
    runtime = root / "runtime"
    return PortableLayout(
        package_root=root,
        runtime_dir=runtime,
        logs_dir=runtime / "logs",
        state_path=runtime / "portable-state.json",
        manifest_path=root / "portable-manifest.json",
        template_dir=template,
        frontend_dist=frontend,
    )


def test_verify_manifest_accepts_matching_file(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    payload = b"portable"
    (layout.package_root / "asset.bin").write_bytes(payload)
    layout.manifest_path.write_text(
        json.dumps(
            {
                "files": [
                    {
                        "path": "asset.bin",
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    verify_manifest(layout)


def test_verify_manifest_rejects_tampered_file(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    (layout.package_root / "asset.bin").write_bytes(b"tampered")
    layout.manifest_path.write_text(
        json.dumps({"files": [{"path": "asset.bin", "sha256": "0" * 64}]}),
        encoding="utf-8",
    )
    with pytest.raises(PortableError, match="损坏"):
        verify_manifest(layout)


def test_initialize_runtime_copies_template_only_once(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    (layout.template_dir / "platform.sqlite3").write_bytes(b"seed")
    (layout.template_dir / ORIGIN_FILE).write_text("C:\\build\\runtime", encoding="utf-8")
    # Keep this unit focused on one-time semantics; relocation has its own DB test.
    import geomodeling.portable as portable

    original = portable.relocate_runtime
    portable.relocate_runtime = lambda *_args: None
    try:
        initialize_runtime(layout)
    finally:
        portable.relocate_runtime = original
    assert (layout.runtime_dir / "platform.sqlite3").read_bytes() == b"seed"
    (layout.runtime_dir / "platform.sqlite3").write_bytes(b"user-data")
    initialize_runtime(layout)
    assert (layout.runtime_dir / "platform.sqlite3").read_bytes() == b"user-data"


def test_relocate_runtime_rewrites_text_and_json_paths(tmp_path: Path) -> None:
    import sqlite3

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    db = sqlite3.connect(runtime / "platform.sqlite3")
    db.execute("CREATE TABLE datasets (source_path TEXT, profile_json TEXT, count INTEGER)")
    db.execute(
        "INSERT INTO datasets VALUES (?, ?, ?)",
        (r"C:\\build\\runtime\\uploads\\a.csv", r'{"path":"C:\\\\build\\\\runtime\\\\data"}', 1),
    )
    db.commit()
    db.close()
    (runtime / "manifest.json").write_text(
        '{"path":"C:\\\\build\\\\runtime\\\\results"}', encoding="utf-8"
    )

    relocate_runtime(runtime, r"C:\\build\\runtime", r"D:\\r")

    db = sqlite3.connect(runtime / "platform.sqlite3")
    source_path, profile, count = db.execute("SELECT * FROM datasets").fetchone()
    db.close()
    assert source_path.startswith(r"D:\\r")
    assert "D:" in profile and "C:" not in profile
    assert count == 1
    manifest_text = (runtime / "manifest.json").read_text(encoding="utf-8")
    assert "D:" in manifest_text and "C:" not in manifest_text
    assert b"C:\\build\\runtime" not in (runtime / "platform.sqlite3").read_bytes()
