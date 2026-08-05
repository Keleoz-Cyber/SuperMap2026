"""Install and preflight the SuperMap iClient3D 2026 (SuperMap3D 12.1) runtime.

The runtime is the official ``Build/SuperMap3D`` tree from the local
SuperMap iClient3D for WebGL/WebGPU 2026 distribution. It is copied into
``web/public/SuperMap3D-2026`` via a sibling staging directory, verified
against the required entries and a pinned ``SuperMap3D.js`` sha256, then
atomically renamed into place. The runtime is never committed to Git.

Usage::

    python scripts/install_supermap3d.py \
        --source <SDK Build/SuperMap3D directory> \
        --destination web/public/SuperMap3D-2026 \
        --expected-sha256 <sha256 of SuperMap3D.js> [--replace]

    python scripts/install_supermap3d.py \
        --destination web/public/SuperMap3D-2026 \
        --expected-sha256 <sha256 of SuperMap3D.js> --verify-only
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tempfile
from pathlib import Path

SCRIPT_NAME = "SuperMap3D.js"
REQUIRED_ENTRIES = [
    SCRIPT_NAME,
    "Assets",
    "Workers",
    "ThirdParty",
    "Widgets",
    "Widgets/widgets.css",
]


class PreflightError(RuntimeError):
    """Raised when a runtime tree misses required entries or the pinned hash."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def preflight_tree(root: Path, expected_sha256: str) -> str:
    """Verify required entries and the script hash under ``root``.

    Returns the actual ``SuperMap3D.js`` sha256 on success.
    """
    missing = [entry for entry in REQUIRED_ENTRIES if not (root / entry).exists()]
    if missing:
        raise PreflightError(f"missing required entries under {root}: {', '.join(missing)}")
    actual = sha256_file(root / SCRIPT_NAME)
    if actual.lower() != expected_sha256.lower():
        raise PreflightError(
            f"{SCRIPT_NAME} sha256 mismatch under {root}: "
            f"expected {expected_sha256.lower()}, got {actual}"
        )
    return actual


def _report(root: Path, actual: str) -> None:
    print(f"  {SCRIPT_NAME} sha256: {actual}")
    for entry in REQUIRED_ENTRIES:
        print(f"  ok {entry}")
    print(f"  location: {root}")


def verify_only(destination: Path, expected_sha256: str) -> int:
    if not destination.exists():
        print(f"error: destination does not exist: {destination}", file=sys.stderr)
        return 1
    try:
        actual = preflight_tree(destination, expected_sha256)
    except PreflightError as exc:
        print(f"error: preflight failed: {exc}", file=sys.stderr)
        return 1
    print("SuperMap3D runtime verified:")
    _report(destination, actual)
    return 0


def install(source: Path, destination: Path, expected_sha256: str, replace: bool) -> int:
    if not source.is_dir():
        print(f"error: source directory does not exist: {source}", file=sys.stderr)
        return 1
    if source.resolve() == destination.resolve():
        print("error: source and destination must be different paths", file=sys.stderr)
        return 1

    if destination.exists():
        try:
            preflight_tree(destination, expected_sha256)
        except PreflightError as exc:
            if not replace:
                print(
                    f"error: destination {destination} exists and does not match the "
                    f"expected runtime ({exc}); pass --replace to overwrite it",
                    file=sys.stderr,
                )
                return 1
        else:
            print("SuperMap3D runtime already installed and verified:")
            _report(destination, expected_sha256.lower())
            return 0

    try:
        preflight_tree(source, expected_sha256)
    except PreflightError as exc:
        print(f"error: source failed preflight: {exc}", file=sys.stderr)
        return 1

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging_parent = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=destination.parent)
    )
    staging = staging_parent / destination.name
    try:
        print(f"copying {source} -> {staging} ...")
        shutil.copytree(source, staging)
        actual = preflight_tree(staging, expected_sha256)
        if destination.exists():
            shutil.rmtree(destination)
        staging.rename(destination)
    except PreflightError as exc:
        print(f"error: staged copy failed preflight: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: install failed: {exc}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)

    print("installed SuperMap3D runtime:")
    _report(destination, actual)
    print("runtime is local-only and git-ignored.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="SDK source directory (Build/SuperMap3D)")
    parser.add_argument(
        "--destination",
        type=Path,
        required=True,
        help="install target, e.g. web/public/SuperMap3D-2026",
    )
    parser.add_argument(
        "--expected-sha256",
        required=True,
        help="pinned sha256 of SuperMap3D.js",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="overwrite an existing destination that does not match the expected runtime",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="verify the destination without copying anything",
    )
    args = parser.parse_args()

    if args.verify_only:
        return verify_only(args.destination, args.expected_sha256)
    if args.source is None:
        parser.error("--source is required unless --verify-only is used")
    return install(args.source, args.destination, args.expected_sha256, args.replace)


if __name__ == "__main__":
    raise SystemExit(main())
