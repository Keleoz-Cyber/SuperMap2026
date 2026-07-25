# v0.4.1 演示证据目录

## 收录策略

- 本目录只收录**真实 Windows 彩排之后**、经人工筛选的截图或小型文本证据。
- 禁止提交：本机绝对路径、凭据、个人数据、私有原始资料、运行时 SQLite、导出的成果 ZIP、原始 Playwright trace。
- Playwright trace/失败截图只作为 CI 工件（`browser-live-evidence`）保存，不进入仓库。
- 每张提交的图片必须在本文登记：路由、构建 commit、属于实时证据（live）还是备用证据（fallback）。

## 彩排记录（2026-07-25）

- 彩排 commit：`8e34fe0`（版本统一后最终候选提交以本分支 HEAD 为准）
- 运行时：全新 `var/demo_v041`；演示数据 SHA-256 `deb9c25f713ae79d…2bb3`
- 路线 A：上传 → 质量校验通过（144/144）→ IDW（power=2/邻域 16）1/1 成功 → 普通克里金（球状自动变异函数）1/1 成功 → 排行榜（公共有效点 144）→ 完整场 1,331 单元 → X/Y/Z 切片真实坐标 → 正式选择（理由落库）→ 导出 ZIP 七文件（1,331 行 grid.csv）→ 返回实验/首页，案例卡持久化
- 路线 B（iServer 在线）：六级证据链全部 `ok=True`（model_succeeded / artifact_exported / iserver_published / service_metadata_verified / browser_loaded=browser_report / manual_visual_checked），iServer 场景 1 图层 + 体元缓存 7,056 格 + 点云/体元/叠加切换
- 降级（iServer 关闭后重新探测）：路线 B 如实显示「iServer 离线」，路线 A 深链实验页照常加载（公共有效点 144 不变）
- 重启恢复：杀进程后以同一 `var/demo_v041` 重启，案例卡、实验、run（succeeded）与候选全部恢复，无误标 interrupted

## 登记

| 文件 | 路由/场景 | 构建 commit | live/fallback | 说明 |
|---|---|---|---|---|
| v041-01-home-live.png | 首页 | 彩排分支 HEAD | live | v0.4.1 徽标与新建案例/演示数据入口 |
| v041-02-wizard-live.png | 数据准备向导 | 同上 | live | 质量校验通过（144/144） |
| v041-03-kriging-board-live.png | 实验详情·排行榜 | 同上 | live | 克里金候选成功，公共有效点 144 |
| v041-04-fullfield-live.png | 成果工作台·完整场 | 同上 | live | 克里金完整场 1,331 单元值域渐变 |
| v041-05-slice-x-live.png | 成果工作台·X 切片 | 同上 | live | X 垂直切片真实坐标标签 |
| v041-06-export-live.png | 成果工作台·导出/选择 | 同上 | live | 正式选择记录 + 七文件导出 + 下载链接 |
| v041-07-home-persisted-live.png | 首页 | 同上 | live | 彩排案例卡持久化 |
| v041-08-route-b-iserver-live.png | 电阻率工作台（iServer 在线） | 同上 | live | 六级证据链全绿、体元 7,056 格 |
| v041-09-route-b-offline-fallback.png | 电阻率工作台（iServer 离线） | 同上 | fallback | 「iServer 离线」如实降级，点云不受影响 |
