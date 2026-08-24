# 运维手册

> 受众：平台维护者与发布执行者。本文是免安装包、源码开发、打包发布、测试 CI 与故障排查的唯一权威说明。命令用法全表见 [api-reference.md](api-reference.md)。
>
> 更新时间：2026-08-15；适用版本：1.0.0。除特别注明外，命令均在仓库根目录的 **PowerShell** 中运行。

## 1. Windows 免安装包

### 1.1 使用

1. 下载 `GeoModelingPlatform-1.0.0-win-x64.zip`，完整解压到可写目录；
2. 双击 `启动平台.cmd`，浏览器自动打开 <http://127.0.0.1:8000/>；
3. 结束后双击 `停止平台.cmd`。

包内含 Python 运行时、前端、SuperMap3D SDK、SQLite 与三个内置案例，无需安装 Python、Node.js、Docker 或 iServer。首次启动从只读模板复制 `runtime` 工作目录，用户数据只写入该目录。

### 1.2 诊断

```cmd
GeoModelingPlatform.exe doctor
```

检查包完整性（`portable-manifest.json` 逐文件 SHA-256）、端口占用与运行状态。端口身份不明、哈希不符或文件损坏时启动器 fail-closed，拒绝启动。

## 2. 源码开发

### 2.1 环境与启动

```powershell
python -m pip install -e ".[api,test]"
npm --prefix web ci
python -m geomodeling.cli demo-check
powershell -ExecutionPolicy Bypass -File scripts\start_demo.ps1
```

要求 Python 3.12+ 与 Node 22。开发态前端 `npm --prefix web run dev` 由 Vite 代理 `/api` 到本机 FastAPI。

### 2.2 SuperMap3D SDK 预检

SDK 不入库，由安装脚本放置并钉住哈希：

```powershell
python scripts/install_supermap3d.py --destination web/public/SuperMap3D-2026 --verify-only --expected-sha256 d69dadab01fc452a79f1fa88a46aced3cf29885df7bf4febbd6f24ce5b578120
```

安装（首次或升级）去掉 `--verify-only`；脚本使用 staging + 原子替换，校验必需条目后改名生效。

### 2.3 运行数据与凭据

- 数据目录由 `GEOMODELING_DATA_DIR` 指定（默认 `var/geomodeling/`）；演示脚本使用独立目录避免污染开发库。
- iServer 与 DeepSeek 凭据只允许通过环境变量或产品内「AI 设置」（Windows 凭据管理器）传入，不得写入仓库或配置文件。

## 3. 便携包制作

```powershell
python -m pip install -e ".[api,package]"
python scripts/build_portable.py
```

流程：隔离 venv（防全局环境泄漏）-> 前端构建（校验 dist 与 SDK 存在）-> 用真实后端 seed 三个预置案例并预生成渲染资产（runtime-template）-> PyInstaller 单目录打包 -> 复制启动脚本与三方声明 -> 写 `portable-manifest.json` 全文件 SHA-256 -> 移动后冒烟测试（doctor/start/health/内置案例断言）-> 输出 zip 与 `.zip.sha256` 到 `release/`。

发布前需通过中文/空格路径移动验收。`build/`、`release/`、运行数据库、日志与缓存均不进入 Git。

## 4. 测试、CI 与验收

### 4.1 本地完整质量门

```powershell
python -m pytest -q -m "not local_data"
python -m pytest -q -m local_data
npm --prefix web run test:unit
npm --prefix web run type-check
npm --prefix web run build
npm --prefix web run test:e2e
npm --prefix web run test:e2e:live -- e2e-live/platform-live.spec.ts
git diff --check
```

`local_data` 只在相邻只读研究资料存在时运行，并核对前后源哈希不变；需要 SuperMap SDK/GPU 的规格只属于本机发布门，不得用 Mock 冒充。

### 4.2 双速 CI

项目进入维护期后默认直接在 `main` 上修改，不再为日常小修建立功能分支和 PR。自动 CI 只监听 `main`：一次 push 只执行一次快速门（快速 Python 合同测试 + 完整前端单元测试、类型检查与构建）；纯 Markdown 或 `docs/` 变更不触发 CI。`v*` 标签或人工触发才执行完整后端、Mock E2E 与真实 FastAPI/SQLite Live E2E。

日常修改先运行与改动直接相关的测试即可；准备推送时再运行快速门，发布前才运行完整门。这样既保留回归保护，也避免“分支 push、PR、合并 main”重复执行三遍。若未来出现跨模块高风险改造，再按实际风险临时恢复隔离分支，不把分支流程作为普通小修的默认要求。

免安装包的 `release/<版本目录>` 是只读构建产物，禁止在原目录内启动。压缩前构建脚本会重新核对 `portable-manifest.json`，发现根级 `runtime/`、清单外文件或清单后改写时直接拒绝打包；评测运行数据只允许在解压副本中生成。

### 4.3 发布前人工确认清单

- `demo-check` 无阻断，8000/8090 端口与服务身份正确；
- 三案例、上传、调参、比较、成果、切片、导出与返回路径可用；
- 1920×1080、1440×900 和 390×844 没有关键截断或横向溢出；
- Volume/Contour/Slice 有真实像素变化；iServer 离线时界面如实降级；
- 截图、视频、Release 包和源码来自同一版本。

测试代码属于工程质量合同：保留在源码仓库与比赛"工程源代码"目录，但不进入免安装运行包。

## 5. 故障排查

### 5.1 NetCDF / 体渲染问题定位

按七类依次定位，避免无方向试错：`source_contract`（数据合同）-> `netcdf_export`（写包）-> `asset_identity`（资产身份与哈希）-> `sdk_runtime`（SDK 加载与 WebGL2）-> `camera_or_bounds`（包围盒与相机）-> `browser_or_gpu`（浏览器/显卡）-> `message_protocol`（iframe 协议消息）。

### 5.2 中断恢复语义

- 进程重启后：进行中的 run / 分析任务标记 `interrupted`；`creating` 状态的渲染资产恢复为 `interrupted`；
- `interrupted` 资产必须显式 `retry_failed` 重建，不得静默覆盖；
- 未完成的两阶段删除在启动时自动恢复或回滚。

### 5.3 常见问题

| 现象 | 处理 |
|---|---|
| `DEEPSEEK_NOT_CONFIGURED` | 环境变量未传给进程：先停止平台，再从已设变量的同一 CMD 窗口启动；或改用产品内「AI 设置」 |
| 启动器拒绝启动 | 运行 `doctor` 查看哈希/端口/文件完整性报告 |
| 预置案例 409 `PRESET_NOT_INITIALIZED` | 执行 `python -m geomodeling.preset_cli seed-resistivity --data-dir <目录>` 等对应 seed 命令 |
| 上传失败 | 确认文件 ≤ 50 MiB、≤ 500,000 行；失败不留半成品，直接重传 |
| 切片/统计与三维不一致 | 确认两者引用同一 result 身份；切片只读持久工件，缓存过期即重新拉取 |

### 5.4 微震维护入口

微震领域链重建（审计 -> 派生 -> 导入）：

```powershell
python -m geomodeling.cli microseismic derive --help
python -m geomodeling.cli microseismic import-case --help
```

黄金哈希不一致时导入 fail-closed；先核对 `config/microseismic.yaml` 与源 DAT 是否被改动，再排查派生规则版本。

### 5.5 预置案例重建

预置案例由 seed 命令经完整生命周期幂等创建（同身份同指纹复用）；官方基线 JSON 冻结在 `config/presets/*-official-baseline.json`，基线不符即拒绝 seed。命令全表见 [api-reference.md](api-reference.md) 第 3.5 节。
