"""Build the offline Windows x64 one-directory evaluation package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST_ROOT = ROOT / "release"
BUILD_ROOT = ROOT / "build" / "portable"
APP_NAME = "GeoModelingPlatform"
VERSION = "0.9.2"
ISOLATED_ENV_FLAG = "GMP_PORTABLE_BUILD_ENV"


def resolve_command(command: list[str]) -> list[str]:
    """Resolve Windows batch-based CLI entry points for ``CreateProcess``."""

    resolved = list(command)
    if os.name == "nt" and resolved and resolved[0].lower() == "npm":
        resolved[0] = "npm.cmd"
    return resolved


def isolated_python_path() -> Path:
    return BUILD_ROOT / "venv" / "Scripts" / "python.exe"


def relaunch_in_isolated_environment() -> int | None:
    """Build from a project-only venv so global Conda packages cannot leak in."""

    if os.environ.get(ISOLATED_ENV_FLAG) == "1":
        return None
    python = isolated_python_path()
    if not python.is_file():
        BUILD_ROOT.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, "-m", "venv", str(python.parents[1])], check=True)
    subprocess.run(
        [str(python), "-m", "pip", "install", "--upgrade", "pip", "setuptools>=70,<81"],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [str(python), "-m", "pip", "install", "-e", ".[api,package]"],
        cwd=ROOT,
        check=True,
    )
    env = dict(os.environ)
    env[ISOLATED_ENV_FLAG] = "1"
    completed = subprocess.run(
        [str(python), str(Path(__file__).resolve()), *sys.argv[1:]],
        cwd=ROOT,
        env=env,
        check=False,
    )
    return completed.returncode


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    resolved = resolve_command(command)
    print("+", subprocess.list2cmdline(resolved), flush=True)
    subprocess.run(resolved, cwd=ROOT, env=env, check=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare_runtime_template(target: Path) -> dict[str, str]:
    from geomodeling.portable import TEMPLATE_ROOT_MARKER, relocate_runtime
    from geomodeling.platform import PlatformRuntime
    from geomodeling.platform import render_assets
    from geomodeling.platform.gas_preset import seed_gas_preset
    from geomodeling.platform.microseismic_preset import seed_microseismic_preset
    from geomodeling.platform.resistivity_preset import seed_resistivity_preset
    from geomodeling.platform.settings import PlatformSettings

    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    runtime = PlatformRuntime(settings=PlatformSettings(data_dir=target))
    runtime.initialize()
    try:
        seeds = (
            seed_resistivity_preset(runtime),
            seed_microseismic_preset(runtime),
            seed_gas_preset(runtime),
        )
        result: dict[str, str] = {}
        for seed in seeds:
            result_id = seed.official_result.result_id
            source = render_assets.resolve_candidate_render_source(runtime, result_id)
            asset, _created = render_assets.create_render_asset(runtime, source)
            result[seed.case_id] = result_id
            result[f"{seed.case_id}_asset"] = asset.id
    finally:
        runtime.close()
    relocate_runtime(target, str(target.resolve()), TEMPLATE_ROOT_MARKER)
    (target / "portable-origin.txt").write_text(TEMPLATE_ROOT_MARKER, encoding="utf-8")
    for transient in target.glob("platform.sqlite3-*"):
        transient.unlink(missing_ok=True)
    return result


def build_frontend() -> None:
    run(["npm", "--prefix", "web", "ci"])
    run(["npm", "--prefix", "web", "run", "build"])
    required = (
        ROOT / "web" / "dist" / "index.html",
        ROOT / "web" / "dist" / "SuperMap3D-2026" / "SuperMap3D.js",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"frontend build is incomplete: {missing}")


def build_executable(template: Path, clean: bool) -> Path:
    output = DIST_ROOT / f"{APP_NAME}-{VERSION}-win-x64"
    work = BUILD_ROOT / "pyinstaller"
    spec = BUILD_ROOT / "spec"
    if clean:
        shutil.rmtree(output, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(spec, ignore_errors=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    spec.mkdir(parents=True, exist_ok=True)
    separator = os.pathsep
    add_data = [
        (ROOT / "config", "config"),
        (ROOT / "demo", "demo"),
        (ROOT / "example_data", "example_data"),
        (ROOT / "web" / "dist", "web/dist"),
        (template, "runtime-template"),
    ]
    command = pyinstaller_command(template, work, spec)
    for source, destination in add_data:
        command.extend(["--add-data", f"{source}{separator}{destination}"])
    command.append(str(ROOT / "src" / "geomodeling" / "portable.py"))
    run(command)
    pyinstaller_output = DIST_ROOT / APP_NAME
    if output.exists():
        shutil.rmtree(output)
    pyinstaller_output.rename(output)
    return output


def pyinstaller_command(template: Path, work: Path, spec: Path) -> list[str]:
    """Return a deterministic command without collecting unrelated global packages."""

    return [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--console",
        "--name",
        APP_NAME,
        "--distpath",
        str(DIST_ROOT),
        "--workpath",
        str(work),
        "--specpath",
        str(spec),
        "--hidden-import",
        "geomodeling.api.app",
        "--collect-submodules",
        "uvicorn",
        "--copy-metadata",
        "geomodeling-platform",
        "--hidden-import",
        "uvicorn.logging",
        "--hidden-import",
        "uvicorn.loops.auto",
        "--hidden-import",
        "uvicorn.protocols.http.auto",
        "--hidden-import",
        "uvicorn.protocols.websockets.auto",
        "--hidden-import",
        "uvicorn.lifespan.on",
    ]


def add_delivery_files(output: Path, seed_ids: dict[str, str]) -> None:
    shutil.copy2(ROOT / "portable" / "启动平台.cmd", output / "启动平台.cmd")
    shutil.copy2(ROOT / "portable" / "停止平台.cmd", output / "停止平台.cmd")
    shutil.copy2(
        ROOT / "portable" / "THIRD_PARTY_NOTICES.txt",
        output / "THIRD_PARTY_NOTICES.txt",
    )
    guide = f"""GeoModelingPlatform {VERSION} 评测组使用说明

1. 将整个文件夹解压到本机可写目录，不要只运行压缩包内的程序。
2. 双击“启动平台.cmd”，等待浏览器自动打开。
3. 首页已内置电阻率、微震波速和瓦斯含量三个案例。
4. 也可上传 CSV/XLSX，完成字段映射、质量校验、调参、空间验证和三维展示。
5. 使用结束后双击“停止平台.cmd”。用户数据保存在 runtime 目录。

AI 辅助研判（可选）：
- 在页面右上角点击“AI 设置”，输入自己的 DeepSeek API Key，先测试连接再保存。
- Key 由当前 Windows 用户的凭据管理器保存，不会写入本文件夹、浏览器或成果包。
- 不配置 AI 不影响数据校验、插值、三维展示、规则分析和导出。
- 不要将团队 API Key 写入本文件夹或随压缩包分发。
- 管理员备用：可在启动进程前设置 DEEPSEEK_API_KEY 环境变量；该配置在页面中只读。

不需要安装 Python、Node.js、数据库或 Docker。iServer 为可选增强能力，离线不影响核心建模。
默认地址：http://127.0.0.1:8000/
诊断命令：GeoModelingPlatform.exe doctor
版本：{VERSION}
内置成果身份：{json.dumps(seed_ids, ensure_ascii=False)}
"""
    (output / "使用说明.txt").write_text(guide, encoding="utf-8-sig")


def write_manifest(output: Path) -> Path:
    manifest_path = output / "portable-manifest.json"
    entries = []
    for path in sorted(output.rglob("*")):
        if not path.is_file() or path == manifest_path:
            continue
        relative = path.relative_to(output).as_posix()
        entries.append({"path": relative, "size": path.stat().st_size, "sha256": sha256(path)})
    payload = {
        "format": "geomodeling-portable/v1",
        "version": VERSION,
        "platform": "windows-x64",
        "files": entries,
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def create_zip(output: Path) -> Path:
    archive = DIST_ROOT / f"{output.name}.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                bundle.write(path, Path(output.name) / path.relative_to(output))
    (archive.with_suffix(archive.suffix + ".sha256")).write_text(
        f"{sha256(archive)}  {archive.name}\n", encoding="ascii"
    )
    return archive


def smoke_test_moved_package(output: Path, port: int = 18080) -> None:
    with tempfile.TemporaryDirectory(prefix="GMP 评测 移动测试 ") as temp:
        moved = Path(temp) / "GeoModelingPlatform 便携版"
        shutil.copytree(output, moved)
        executable = moved / f"{APP_NAME}.exe"
        run_at = lambda args: subprocess.run(
            [str(executable), *args], cwd=moved, check=True, text=True, capture_output=True
        )
        doctor = run_at(["doctor"])
        if '"ok": true' not in doctor.stdout.lower():
            raise RuntimeError(f"portable doctor failed: {doctor.stdout} {doctor.stderr}")
        run_at(["start", "--port", str(port), "--no-browser"])
        try:
            deadline = time.time() + 30
            payload = None
            while time.time() < deadline:
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/health", timeout=2
                    ) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                    break
                except OSError:
                    time.sleep(0.5)
            if not payload or payload.get("status") != "ok":
                raise RuntimeError("moved portable package did not become healthy")
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/cases", timeout=5) as response:
                cases = json.loads(response.read().decode("utf-8"))["cases"]
            case_ids = {item["case_id"] for item in cases}
            if not {"resistivity", "builtin-microseismic-vx-1911", "gas"}.issubset(case_ids):
                raise RuntimeError(f"built-in cases missing after move: {sorted(case_ids)}")
        finally:
            run_at(["stop"])


def main() -> int:
    isolated_exit = relaunch_in_isolated_environment()
    if isolated_exit is not None:
        return isolated_exit
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-smoke", action="store_true")
    parser.add_argument("--no-clean", action="store_true")
    args = parser.parse_args()
    build_frontend()
    template = BUILD_ROOT / "runtime-template"
    seed_ids = prepare_runtime_template(template)
    output = build_executable(template, clean=not args.no_clean)
    add_delivery_files(output, seed_ids)
    write_manifest(output)
    if not args.skip_smoke:
        smoke_test_moved_package(output)
    archive = create_zip(output)
    print(json.dumps({"output": str(output), "archive": str(archive), "sha256": sha256(archive)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
