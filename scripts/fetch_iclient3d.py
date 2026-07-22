"""Fetch the SuperMap iClient3D for Cesium SDK used by the browser app.

The SDK is the official SuperMap distribution bundled inside the npm
package ``@supermap/iclient3d-vue-for-webgl`` (``public/Cesium`` tree,
Cesium 1.67 + SuperMap S3M/volume plugins). It is downloaded from the
public npm registry, extracted into ``web/public/Cesium`` and
``vendor/iclient3d/Cesium``, and is never committed to Git.

Usage::

    python scripts/fetch_iclient3d.py            # fetch + verify
    python scripts/fetch_iclient3d.py --force    # re-download
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

NPM_PACKAGE = "@supermap/iclient3d-vue-for-webgl"
NPM_VERSION = "1.2.2"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    PROJECT_ROOT / "web" / "public" / "Cesium",
    PROJECT_ROOT / "vendor" / "iclient3d" / "Cesium",
]
REQUIRED_ENTRIES = ["Cesium.js", "Widgets", "Workers", "Assets", "ThirdParty"]


def sdk_ready(target: Path) -> bool:
    return all((target / entry).exists() for entry in REQUIRED_ENTRIES)


def extract_sdk(tgz_path: Path, temp_dir: Path) -> Path:
    with tarfile.open(tgz_path, "r:gz") as tar:
        tar.extractall(temp_dir)
    source = temp_dir / "package" / "public" / "Cesium"
    if not sdk_ready(source):
        raise RuntimeError(f"extracted SDK incomplete under {source}")
    return source


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-download even if present")
    args = parser.parse_args()

    if not args.force and all(sdk_ready(target) for target in TARGETS):
        print("iClient3D SDK already present:")
        for target in TARGETS:
            print(f"  {target}")
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        tgz = tmp_path / "sdk.tgz"
        spec = f"{NPM_PACKAGE}@{NPM_VERSION}"
        print(f"downloading {spec} from npm registry ...")
        subprocess.run(
            ["npm", "pack", spec, "--pack-destination", str(tmp_path)],
            check=True,
            shell=(sys.platform == "win32"),
        )
        archives = list(tmp_path.glob("*.tgz"))
        if not archives:
            raise RuntimeError("npm pack produced no tarball")
        source = extract_sdk(archives[0], tmp_path)
        for target in TARGETS:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
            print(f"installed SDK -> {target}")
    print("done. SDK is local-only and git-ignored.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
