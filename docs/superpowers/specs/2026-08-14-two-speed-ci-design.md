# 双速 CI 设计

## 目标

普通分支提交、`main` 推送和 Pull Request 只运行快速检查，将反馈时间控制在约 3–5 分钟；仅在推送 `v*` 版本标签或手动选择完整模式时运行现有完整 CI。

## 触发与执行规则

| 事件 | 快速门 | 全量后端 | Browser Smoke | Browser Live |
|---|---:|---:|---:|---:|
| 普通分支 push | 是 | 否 | 否 | 否 |
| `main` push | 是 | 否 | 否 | 否 |
| Pull Request | 是 | 否 | 否 | 否 |
| `v*` 标签 push | 否 | 是 | 是 | 是 |
| workflow_dispatch | 否 | 是 | 是 | 是 |

`workflow_dispatch` 固定代表人工完整验收，不再增加模式输入，避免出现“手工点了 CI 却只跑快速门”的歧义。

## 快速门内容

快速门保留一个稳定 job 名 `portable-tests`，包含：

1. 安装 Python 3.12 和项目 API/test 依赖；
2. CLI help smoke；
3. 运行版本一致性、便携启动、运行路径、API 健康和构建命令等关键 Python 合同测试；
4. 安装 Node.js 22 和前端依赖；
5. 前端完整 unit tests、type-check 和 production build。

快速门不安装 Chromium，不运行全量 Python 测试、Mock Playwright 或 Live E2E。

## 完整门内容

标签与手工触发保留当前三个 job 名与实际步骤：

- `portable-tests`：`pytest -m "not local_data"`、前端单测、类型检查和构建；
- `browser-smoke`：Mock API Playwright；
- `browser-live`：真实 FastAPI、隔离 SQLite 和 Playwright Live E2E。

由于快速门和完整门不会在同一事件同时执行，`portable-tests` 可继续作为稳定的必需检查名称。`browser-smoke` 和 `browser-live` 不应配置为 PR 必需检查；它们是发布门。

## 实现方式

继续使用一个 `.github/workflows/ci.yml`：

- `on.push.branches: ["**"]` 与 `on.push.tags: ["v*"]`；
- `portable-tests` 始终创建，根据 `is_full` 条件选择快速 Python 测试或全量 Python 测试；
- `browser-smoke`、`browser-live` 仅在 `v*` 标签或 `workflow_dispatch` 时创建；
- 前端单测、type-check、build 在快速与完整模式都执行，避免普通提交出现类型或构建破坏。

## 验证

增加静态 CI 合同测试，解析 workflow 文本并确认：

- 普通事件不会满足完整门条件；
- `v*` 标签与 `workflow_dispatch` 会满足完整门；
- 快速 Python 测试清单存在；
- 三个完整发布 job 和原有 E2E 命令仍保留；
- job 名 `portable-tests` 不变。
