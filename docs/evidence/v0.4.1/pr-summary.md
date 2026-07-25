# v0.4.1 答辩演示加固 PR 摘要

## 目标

在不重做视觉、不破坏 v0.4.0 通用建模与 v0.3.1 电阻率只读链路的前提下，消除演示现场风险：导航死路、启动前无预检、缺真实浏览器验收、演示资料分散。**本 PR 不自动合并；合并/标签/Release 需显式批准。**

## 导航矩阵

| 页面/状态 | 动作 | 目标路由 |
|---|---|---|
| 新建案例 | 返回首页 | `home` |
| 数据准备向导（含加载失败） | 返回首页 | `home` |
| 调参实验室·新建 | 返回首页 | `home` |
| 调参实验室·详情/排行榜 | 返回首页 / 新建实验 | `home` / `experiment-create`（不取消在途任务） |
| 成果工作台（含加载失败） | 返回实验 / 返回首页 | `experiment-detail`（精确 ID）/ `home` |

全部命名路由，不用 `history.back()`；可访问名称 + `data-test` 齐全。

## 预检与启动

- `geomodeling demo-check [--json]`：7 项阻断（导入/配置/前端构建/演示数据哈希/数据目录/SQLite/端口身份）+ 3 项 iServer 可选警告；未知占用阻断、本平台健康实例提示复用（精确 OpenAPI 标题匹配）。
- `scripts/start_demo.ps1`：独立数据目录 `var/demo_v041`、单进程前台启动、`-CheckOnly`/`-NoBrowser`；不安装、不删除、不杀进程、不写凭据。

## 演示数据

- 唯一权威 `demo/platform_demo_3d.csv`（144 行，合成样例），SHA-256 固定：`deb9c25f713ae79d7b1c6300cc8066a6ae927879767c67ab03ef4ad76e8a2bb3`。
- 下载端点 `GET /api/demo/datasets/platform-demo-3d`（不暴露本机路径）；哈希不符 fail-closed。

## Mock vs Live E2E

- Mock（页面契约 + 导航恢复，含深链 404 返回首页）：`2 passed`。
- Live（真实 FastAPI + 隔离 SQLite + 真实 Worker，独立 `GEOMODELING_DATA_DIR` 与端口 5201，结束无残留监听）：`1 passed`，覆盖上传→映射→质量→IDW→排行榜→完整场/切片→选择→真实 ZIP 下载→首页持久化。CI `browser-live` 失败上传 trace 工件。

## 真实 Windows 彩排（2026-07-25，全新 var/demo_v041）

- 路线 A：IDW 1/1、普通克里金 1/1（公共有效 144）、完整场/切片、正式选择、七文件 ZIP（1,331 行 grid.csv）、返回导航。
- 路线 B iServer 在线：六级证据链全 `ok=True`（含 browser_report），体元 7,056 格、三模式切换。
- iServer 关闭：路线 B 如实降级「未验证但建模证据不丢失」，路线 A 不受影响。
- 杀进程重启：案例/实验/成果全部恢复，无误标 interrupted。
- 证据：`docs/evidence/v0.4.1/`（live/fallback 已标注）。

## 测试与 CI

- 后端 `pytest 420 passed`（含 demo_check/demo_assets/demo_api/demo_docs/ci_contract/version_consistency 等新契约）；`local_data 23 passed`（哈希不变）。
- 前端 `vitest 43 passed`、type-check/build 零告警；`git diff --check` 干净；危险文件扫描为空。
- CI：portable-tests、browser-smoke、browser-live 三 job。

## 不变的边界

- v0.3.1 电阻率 legacy 路由、S3M fail-closed 契约、六级证据链、点云/体元/叠加切换（removeAll/重建）不变。
- 通用成果发布仍为 manual_required；微震仅 upload_required 预设（派生未代码化）；瓦斯暂缓；任意斜切未实现。

## 明确非目标

UI 视觉重构、主题/动画体系、Cesium 渲染重写、微震/瓦斯接入、新插值算法、iServer 自动发布、账户与云部署。

## 版本

pyproject / API（importlib.metadata 唯一版本源）/ package.json / lockfile / 首页徽标统一 `0.4.1`，自动一致性测试防漂移。
