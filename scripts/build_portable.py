"""Build native Windows x64 and macOS ARM64 one-directory packages."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
DIST_ROOT = ROOT / "release"
BUILD_ROOT = ROOT / "build" / "portable"
APP_NAME = "GeoModelingPlatform"
VERSION = "1.0.1"
ISOLATED_ENV_FLAG = "GMP_PORTABLE_BUILD_ENV"


@dataclass(frozen=True)
class BuildTarget:
    tag: str
    manifest_platform: str
    executable_name: str
    executable_relative: Path
    python_relative: Path
    launchers: tuple[str, str]
    credential_label: str
    start_label: str
    stop_label: str
    app_bundle_name: str | None = None

    @property
    def is_macos(self) -> bool:
        return self.tag == "macos-arm64"


def detect_build_target(
    *, system: str | None = None, machine: str | None = None
) -> BuildTarget:
    """Resolve the only two native package targets supported by this project."""

    detected_system = system or platform.system()
    detected_machine = (machine or platform.machine()).lower()
    if detected_system == "Windows" and detected_machine in {"amd64", "x86_64"}:
        return BuildTarget(
            tag="win-x64",
            manifest_platform="windows-x64",
            executable_name=f"{APP_NAME}.exe",
            executable_relative=Path(f"{APP_NAME}.exe"),
            python_relative=Path("venv/Scripts/python.exe"),
            launchers=("启动平台.cmd", "停止平台.cmd"),
            credential_label="当前 Windows 用户的凭据管理器",
            start_label="启动平台.cmd",
            stop_label="停止平台.cmd",
        )
    if detected_system == "Darwin" and detected_machine in {"arm64", "aarch64"}:
        return BuildTarget(
            tag="macos-arm64",
            manifest_platform="macos-arm64",
            executable_name=APP_NAME,
            executable_relative=Path(
                f"{APP_NAME}.app/Contents/MacOS/{APP_NAME}"
            ),
            python_relative=Path("venv/bin/python"),
            launchers=("启动平台.command", "停止平台.command"),
            credential_label="当前 macOS 用户的钥匙串",
            start_label=f"{APP_NAME}.app",
            stop_label="停止平台.command",
            app_bundle_name=f"{APP_NAME}.app",
        )
    raise RuntimeError(
        f"不支持的便携包构建平台：{detected_system}/{detected_machine}；"
        "仅支持 Windows x64 和 macOS ARM64。"
    )


def resolve_command(command: list[str]) -> list[str]:
    """Resolve Windows batch-based CLI entry points for ``CreateProcess``."""

    resolved = list(command)
    if os.name == "nt" and resolved and resolved[0].lower() == "npm":
        resolved[0] = "npm.cmd"
    return resolved


def isolated_python_path(target: BuildTarget | None = None) -> Path:
    return BUILD_ROOT / (target or detect_build_target()).python_relative


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


def build_executable(
    template: Path,
    clean: bool,
    target: BuildTarget | None = None,
) -> Path:
    resolved_target = target or detect_build_target()
    output = DIST_ROOT / f"{APP_NAME}-{VERSION}-{resolved_target.tag}"
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
    command = pyinstaller_command(template, work, spec, resolved_target)
    for source, destination in add_data:
        command.extend(["--add-data", f"{source}{separator}{destination}"])
    command.append(str(ROOT / "src" / "geomodeling" / "portable.py"))
    run(command)
    pyinstaller_output = DIST_ROOT / APP_NAME
    if output.exists():
        shutil.rmtree(output)
    if resolved_target.is_macos:
        wrap_macos_app(pyinstaller_output, output, resolved_target)
    else:
        pyinstaller_output.rename(output)
    return output


def wrap_macos_app(
    pyinstaller_output: Path,
    output: Path,
    target: BuildTarget,
    *,
    linker: Callable[..., None] = os.symlink,
) -> Path:
    """Wrap the console-capable onedir payload in a standard Finder app bundle."""

    if not target.is_macos or target.app_bundle_name is None:
        raise RuntimeError("仅 macOS ARM64 目标可以生成 .app。")
    if not (pyinstaller_output / target.executable_name).is_file():
        raise RuntimeError("PyInstaller macOS 可执行文件缺失。")
    app = output / target.app_bundle_name
    contents = app / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    output.mkdir(parents=True, exist_ok=True)
    macos.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    executable = pyinstaller_output / target.executable_name
    executable.rename(macos / target.executable_name)
    internal = pyinstaller_output / "_internal"
    if not internal.is_dir():
        raise RuntimeError("PyInstaller macOS _internal 目录缺失。")
    internal.rename(resources / "_internal")
    for child in list(pyinstaller_output.iterdir()):
        child.rename(resources / child.name)
    pyinstaller_output.rmdir()
    linker(
        "../Resources/_internal",
        macos / "_internal",
        target_is_directory=True,
    )
    info = {
        "CFBundleDevelopmentRegion": "zh_CN",
        "CFBundleDisplayName": APP_NAME,
        "CFBundleExecutable": APP_NAME,
        "CFBundleIdentifier": "com.keleoz.geomodelingplatform",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": APP_NAME,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "11.0",
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
    }
    (contents / "Info.plist").write_bytes(plistlib.dumps(info, sort_keys=True))
    (contents / "PkgInfo").write_text("APPL????", encoding="ascii")
    return app


def pyinstaller_command(
    template: Path,
    work: Path,
    spec: Path,
    target: BuildTarget | None = None,
) -> list[str]:
    """Return a deterministic command without collecting unrelated global packages."""

    resolved_target = target or detect_build_target()
    command = [
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
    if resolved_target.is_macos:
        command.extend(
            [
                "--hidden-import",
                "keyring.backends.macOS",
                "--copy-metadata",
                "keyring",
            ]
        )
    return command


def add_delivery_files(
    output: Path,
    seed_ids: dict[str, str],
    target: BuildTarget | None = None,
) -> None:
    resolved_target = target or detect_build_target()
    for launcher in resolved_target.launchers:
        destination = output / launcher
        shutil.copy2(ROOT / "portable" / launcher, destination)
        if resolved_target.is_macos:
            destination.chmod(destination.stat().st_mode | 0o111)
    shutil.copy2(
        ROOT / "portable" / "THIRD_PARTY_NOTICES.txt",
        output / "THIRD_PARTY_NOTICES.txt",
    )
    guide = f"""GeoModelingPlatform {VERSION} 本地免安装版使用说明

1. 将整个文件夹解压到本机可写目录，不要只运行压缩包内的程序。
2. 双击“{resolved_target.start_label}”，等待浏览器自动打开。
3. 首页已内置电阻率、微震波速和瓦斯含量三个案例。
4. 也可上传 CSV/XLSX，完成字段映射、质量校验、调参、空间验证和三维展示。
5. 使用结束后双击“{resolved_target.stop_label}”。用户数据保存在 runtime 目录。

AI 辅助研判（可选）：
- 在页面右上角点击“AI 设置”，输入自己的 DeepSeek API Key，先测试连接再保存。
- Key 由{resolved_target.credential_label}保存，不会写入本文件夹、浏览器或成果包。
- 不配置 AI 不影响数据校验、插值、三维展示、规则分析和导出。
- 不要将团队 API Key 写入本文件夹或随压缩包分发。
- 管理员备用：可在启动进程前设置 DEEPSEEK_API_KEY 环境变量；该配置在页面中只读。

不需要安装 Python、Node.js、数据库或 Docker。iServer 为可选增强能力，离线不影响核心建模。
默认地址：http://127.0.0.1:8000/
诊断命令：{resolved_target.executable_relative.as_posix()} doctor
版本：{VERSION}
内置成果身份：{json.dumps(seed_ids, ensure_ascii=False)}
"""
    (output / "使用说明.txt").write_text(guide, encoding="utf-8-sig")


def write_manifest(output: Path, target: BuildTarget | None = None) -> Path:
    resolved_target = target or detect_build_target()
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
        "platform": resolved_target.manifest_platform,
        "files": entries,
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def validate_release_tree(output: Path) -> None:
    """Reject a portable tree that changed after its manifest was written.

    ``runtime`` is created only on the evaluator's first launch.  Its presence
    in a release tree means the build output was started in place and now
    contains machine-local state that must never be redistributed.
    """

    runtime = output / "runtime"
    if runtime.exists():
        raise RuntimeError(
            "发行目录包含 runtime 运行态数据；请重新执行干净构建，不要在 release 目录内启动平台"
        )

    manifest_path = output / "portable-manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("发行目录缺少 portable-manifest.json")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = payload.get("files")
    if not isinstance(entries, list) or not entries:
        raise RuntimeError("portable-manifest.json 文件清单无效")

    declared: dict[str, tuple[int, str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise RuntimeError("portable-manifest.json 包含无效条目")
        relative = entry.get("path")
        size = entry.get("size")
        digest = entry.get("sha256")
        if not isinstance(relative, str) or not isinstance(size, int) or not isinstance(digest, str):
            raise RuntimeError("portable-manifest.json 包含无效条目")
        candidate = (output / relative).resolve()
        if output.resolve() not in candidate.parents or relative in declared:
            raise RuntimeError(f"portable-manifest.json 包含非法或重复路径：{relative}")
        declared[relative] = (size, digest)

    actual = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file() and path != manifest_path
    }
    missing = sorted(set(declared) - actual)
    extra = sorted(actual - set(declared))
    if missing:
        raise RuntimeError(f"发行目录缺少清单文件：{missing[:5]}")
    if extra:
        raise RuntimeError(f"发行目录包含清单外文件：{extra[:5]}")

    mismatched = []
    for relative, (expected_size, expected_digest) in declared.items():
        path = output / relative
        if path.stat().st_size != expected_size or sha256(path) != expected_digest:
            mismatched.append(relative)
    if mismatched:
        raise RuntimeError(f"发行目录清单校验失败：{mismatched[:5]}")


def create_zip(output: Path) -> Path:
    validate_release_tree(output)
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


def macos_archive_command(output: Path, archive: Path) -> list[str]:
    """Use the native archiver so Finder extraction preserves executable modes."""

    return [
        "ditto",
        "-c",
        "-k",
        "--sequesterRsrc",
        "--keepParent",
        str(output),
        str(archive),
    ]


def macos_sign_commands(app: Path, target: BuildTarget) -> list[list[str]]:
    if not target.is_macos:
        return []
    return [
        ["codesign", "--force", "--sign", "-", str(app)],
        [
            "codesign",
            "--verify",
            "--strict",
            "--verbose=2",
            str(app),
        ],
    ]


def sign_macos_app(output: Path, target: BuildTarget) -> None:
    if not target.is_macos or target.app_bundle_name is None:
        return
    app = output / target.app_bundle_name
    for command in macos_sign_commands(app, target):
        run(command)


def create_archive(output: Path, target: BuildTarget | None = None) -> Path:
    resolved_target = target or detect_build_target()
    if not resolved_target.is_macos:
        return create_zip(output)
    validate_release_tree(output)
    archive = DIST_ROOT / f"{output.name}.zip"
    archive.unlink(missing_ok=True)
    run(macos_archive_command(output, archive))
    if not archive.is_file():
        raise RuntimeError("ditto 未生成 macOS 便携包。")
    (archive.with_suffix(archive.suffix + ".sha256")).write_text(
        f"{sha256(archive)}  {archive.name}\n", encoding="ascii"
    )
    return archive


def copy_portable_tree(source: Path, destination: Path) -> None:
    """Preserve macOS app-bundle links during moved-package smoke tests."""

    shutil.copytree(source, destination, symlinks=True)


def smoke_test_moved_package(
    output: Path,
    port: int = 18080,
    target: BuildTarget | None = None,
) -> None:
    resolved_target = target or detect_build_target()
    with tempfile.TemporaryDirectory(prefix="GMP 评测 移动测试 ") as temp:
        moved = Path(temp) / "GeoModelingPlatform 便携版"
        copy_portable_tree(output, moved)
        executable = moved / resolved_target.executable_relative
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
    target = detect_build_target()
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
    output = build_executable(template, clean=not args.no_clean, target=target)
    add_delivery_files(output, seed_ids, target)
    sign_macos_app(output, target)
    write_manifest(output, target)
    if not args.skip_smoke:
        smoke_test_moved_package(output, target=target)
    archive = create_archive(output, target)
    print(json.dumps({"output": str(output), "archive": str(archive), "sha256": sha256(archive)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
