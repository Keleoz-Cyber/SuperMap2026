# SuperMap 杯提交与文件保留规则

> 依据：2026 年第 24 届 SuperMap 杯高校 GIS 大赛开发组要求，<http://www.giscontest.com/cn/view-1000-382.aspx>。提交前应再次核对官网是否更新。

## 1. 总原则

- Git 仓库用于开发、审计和复现；最终比赛 ZIP 用于评审和部署，两者不能简单等同。
- 仓库保留源码、测试、CI、配置模板、运行脚本和必要技术证据。
- 运行包只保留启动系统需要的文件，不携带测试缓存、开发数据库、日志、凭据或本机绝对路径。
- 所有第三方数据必须具有合法使用和传播权限，并在数据说明中列出来源和许可。

## 2. 官方目录结构

最终提交为单层 ZIP，ZIP 和解压后的根目录名称均使用 `CD+团队邀请码`。根目录至少包含：

1. `工程源代码/`
2. `数据/`
3. `运行文件/`
4. `作品文档/`
5. `代表性截图/`
6. 演示视频和 PPT

不要在根目录再套一层压缩包。

## 3. 工程源代码

建议保留：

- `src/`、`web/src/`、`web/public/`；
- `tests/`、前端单元测试、Mock E2E 和必要的 Live E2E 规格；
- `config/`、`scripts/`、`demo/`、`example_data/`；
- `pyproject.toml`、`web/package.json` 和锁文件；
- `.github/workflows/ci.yml`，用于说明自动化质量门；
- README 和正式技术文档。

测试代码要保留：官方评分包含代码结构、编码规范和稳定性，测试是工程质量证据，不是运行垃圾。可在《工程源代码目录说明》里注明哪些测试是便携测试、哪些需要本机 SuperMap 或私有原始数据。

不应包含：

- `.git/`、`.worktrees/`；
- `node_modules/`、`.pytest_cache/`、`.ruff_cache/`；
- `web/dist/` 的重复副本；
- `var/`、临时 SQLite、上传文件、日志和浏览器缓存；
- `.env`、API Key、iServer 管理员密码和许可证文件；
- 已被 Git 历史替代的过程计划、Agent 提示词、交接副本和重复截图。

官方要求源码目录提供《工程源代码目录说明》Excel，至少说明目录、用途、入口、是否运行必需和测试依赖。

## 4. 数据

建议包含：

- 可公开传播的 `example_data/`；
- 数据字段、单位、坐标、NoData、哈希和许可证说明；
- 可直接运行演示的最小测试数据；
- 需要导入数据库或工作空间时的导入步骤。

不包含未获授权的论文原始资料、私有 DOC/DAT、个人路径或密钥。若正式数据涉密，应按官方要求提供可运行测试数据并明确声明。

官方要求提供《数据说明文档》Excel。

## 5. 运行文件

B/S 运行目录应是可部署产物，而不是整个开发仓库复制：

- 后端安装包或明确的 Python 环境安装清单；
- 前端 production build；
- 启动/停止脚本；
- Windows x64 免安装包的制作与验收见 [Windows 便携交付说明](portable-delivery.md)；
- 配置模板与环境变量说明；
- 必要的 SuperMap3D 前端运行时；
- 健康检查和演示前检查说明。

测试源码不需要复制到运行目录。开发依赖、构建缓存和本地数据库也不进入运行目录。

## 6. 作品文档与答辩材料

按照官方模板准备：

- 系统介绍 DOCX；
- 系统部署说明 DOCX；
- 至少 3 张代表性截图；
- 不超过 20 分钟、分辨率不低于 1920×1080 的 MP4 演示视频；
- 答辩 PPT；
- 如适用，补充往届作品差异说明或指导教师报告。

仓库里的 Markdown 是内容源，不能代替官方要求的 DOCX 模板。

## 7. 提交前检查

```powershell
python -m geomodeling.cli demo-check
python -m pytest -q -m "not local_data"
npm --prefix web run test:unit
npm --prefix web run type-check
npm --prefix web run build
npm --prefix web run test:e2e
git diff --check
```

另外人工确认：

- ZIP 解压后只有一层根目录；
- 无密钥、绝对路径、日志、缓存和临时数据库；
- 演示数据有来源和单位；
- iServer/SuperMap 依赖、端口和许可证状态写清楚；
- 视频中的功能与实际提交版本一致；
- 不把 DSI-like、模型离散度、局部坐标或 AI 研判夸大成未经验证的科学结论。
