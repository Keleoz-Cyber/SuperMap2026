# ADR-0001 技术栈与浏览器优先架构

- 状态：已接受
- 日期：2026-07-18（v0.1.0 起），2026-08-15 补记
- 关联：[ADR-0002](0002-supermap3d-iframe-netcdf-rendering.md)、[ADR-0004](0004-sqlite-immutable-artifacts.md)

## 背景

比赛要求浏览器三维展示与现场答辩；评测机器环境不可控（不保证 Python、Node、数据库、Docker 或 iServer）。传统桌面 GIS 工作流分散在多个软件中，难以形成可追溯证据链。

## 决策

- 架构：Vue 3 + TypeScript 浏览器前端 / FastAPI 后端 / SQLite + 不可变文件工件存储 / SuperMap3D 浏览器 SDK 表达层；iDesktopX 与 iServer 只作人工复核与可选发布层，不是主链依赖。
- 浏览器只与自建 API 通信（同源），不直连数据库或外部服务；凭据只在服务端。
- 交付形态：源码仓库 + Windows x64 免安装发行包（PyInstaller + 内置运行时与三案例），评测零安装。
- 不引入 Docker、消息队列或服务型数据库；任务执行为单进程单工作线程。

## 后果

- 正面：评测与答辩环境零依赖；离线可用；版本一致性（后端/前端/包清单）可由测试锁定。
- 代价：并发能力受单 worker 限制（本项目规模足够）；跨机部署需重新设计。
- SuperMap 能力以浏览器 SDK 为主线（见 ADR-0002），iServer 在线与否不影响建模主链，发布状态如实降级。
