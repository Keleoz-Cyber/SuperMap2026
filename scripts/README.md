# scripts 维护脚本

面向维护者的三个入口脚本；面向用户的启动方式见 [docs/operations.md](../docs/operations.md)。

| 脚本 | 作用 |
|---|---|
| `start_demo.ps1` | 答辩演示启动：使用独立数据目录（避免污染开发库）-> 先跑 `geomodeling demo-check --json` -> 端口占用检测 -> 健康等待后开浏览器 -> 前台运行 uvicorn（Ctrl+C 结束）。 |
| `build_portable.py` | 离线 Windows x64 免安装包构建：隔离 venv -> 前端构建（校验 dist 与 SDK 存在）-> 真实后端 seed 三案例与渲染资产（runtime-template）-> PyInstaller 单目录打包 -> manifest 全文件 SHA-256 -> 移动后冒烟测试 -> 输出 zip 与 `.zip.sha256` 到 `release/`。 |
| `install_supermap3d.py` | SuperMap3D SDK 安装/校验：从本地发行版复制到 `web/public/SuperMap3D-2026`，staging + 原子替换，钉住 `SuperMap3D.js` SHA-256（`--expected-sha256`），支持 `--verify-only` 只读校验。 |

## 规则

- SDK 不入 Git：`web/public/SuperMap3D-2026/` 由本脚本从官方发行版安装；升级 SDK 必须重钉哈希并重测单轴切片行为（见 [docs/architecture.md](../docs/architecture.md) 第 9 节）。
- `build_portable.py` 产物（`build/`、`release/`）不入 Git。
- 构建机需可安装 Python 包（`.[api,package]`）与 Node 22，但产物本身离线自洽。
