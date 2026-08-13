# Windows 便携交付说明

## 交付目标

`GeoModelingPlatform-0.9.1-win-x64.zip` 面向竞赛评测组。评委只需解压并双击启动，不需要安装 Python、Node.js、数据库、Docker 或 iServer。

便携包包含：

- `GeoModelingPlatform.exe`：内置 Python 后端、建模算法与 FastAPI 服务；
- 预构建 Vue 前端与 SuperMap3D 2026 浏览器 SDK；
- 电阻率、微震波速和瓦斯含量三个内置案例及成果级 NetCDF 渲染资产；
- `启动平台.cmd`、`停止平台.cmd` 和中文使用说明；
- `portable-manifest.json`：包内文件大小与 SHA-256 完整性清单。

## 评测组操作

1. 将 ZIP 完整解压到本机可写目录，目录名可包含中文和空格。
2. 双击 `启动平台.cmd`，等待浏览器打开 <http://127.0.0.1:8000/>。
3. 直接查看三个内置案例，或上传 CSV/XLSX 走质量校验、调参、空间验证、切片与导出流程。
4. 使用结束后双击 `停止平台.cmd`。

首次启动会从只读模板复制独立 `runtime` 工作目录。之后产生的数据只写入该目录，不修改内置模板；移动整个解压目录后，启动器会自动迁移数据库和证据文件中的绝对路径。

## 诊断与降级

- 双击无响应时，在文件夹地址栏输入 `cmd`，运行 `GeoModelingPlatform.exe doctor`。
- 启动日志位于 `runtime/logs/server.log`。
- 8000 端口被其他程序占用时，启动器会拒绝覆盖，不会结束身份不明的进程。
- iServer 是可选增强能力。离线时核心上传、插值、比较、三维展示、切片与导出仍可运行；界面必须如实显示 iServer 未验证，不能把降级状态描述为发布成功。
- 若完整性清单不匹配，程序会拒绝启动并指出损坏文件。此时应重新解压原始 ZIP，不应手工替换包内 DLL 或资源。

## 制作命令（项目维护者）

PowerShell：

```powershell
python -m pip install -e ".[api,package]"
python scripts/build_portable.py
```

脚本会依次执行前端构建、三案例模板生成、PyInstaller onedir 冻结、完整性清单生成、中文/空格路径移动验收和 ZIP 压缩。输出：

- `release/GeoModelingPlatform-0.9.1-win-x64.zip`
- `release/GeoModelingPlatform-0.9.1-win-x64.zip.sha256`

`build/` 与 `release/` 是本地生成物，不进入 Git。发布前必须保留移动路径冒烟测试，不允许只验证构建机原目录。

## 能力边界

- 交付包目标系统为 Windows x64；未宣称支持 macOS、Linux 或 ARM。
- 当前三维完整场是经过验证的浏览器点元/体元表达，不宣称为 SuperMap 原生 GPU 体渲染。
- 通用成果自动发布到 iServer 仍是可选人工流程；iServer 管理员凭据、许可和本机工作空间不得打入便携包。
- 便携包不包含测试源码、Git 历史、开发缓存、真实凭据或评委不需要的原始论文资料。
