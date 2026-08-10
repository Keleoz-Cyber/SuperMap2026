# GeoModelingPlatform 成果分析、三维联动与 DeepSeek 辅助研判实施提示词

你接手的是 SuperMap2026 / GeoModelingPlatform 的 v0.9.0 功能分支。不要再做静态视觉稿，也不要只补文档或堆测试；目标是把现有成果页变成由真实成果网格驱动、能在浏览器演示的分析工作台。

## 工作位置与边界

- 只在 `D:\study\Contest\Supermap\.worktrees\v0.9.0-visual-product` 工作。
- 当前分支应为 `feat/v0.9.0-visual-product`；开始前先核对 `git status`、分支和最新提交，不要相信旧汇报。
- 先完整阅读：
  1. `docs/superpowers/specs/2026-08-10-v0.9.0-result-analysis-integration-design.md`
  2. `docs/superpowers/plans/2026-08-10-v0.9.0-result-analysis-integration.md`
  3. `D:\study\Contest\Supermap\AI_CONTEXT_HANDOFF_2026-08-10.md`
- 按计划 Task 1–11 实施，测试先行、每个任务独立提交。
- 不合并 PR #19，不打标签、不建 Release、不删分支、不修改原始资料。
- 不使用独立原型 `geological-analysis-workbench-v6.html` 里的写死数字或写死结论。

## 必须完成的真实产品结果

### 1. 成果网格分析

新增只读成果分析接口，基于已物化 `GridResult` 真实计算：

- 完整场 min/max/mean/median/p25/p75；
- 低/正常/高值节点组成；
- 深度分层趋势；
- p75 高值连通区 A/B/C，复用既有 2D 四邻接/3D 六邻接异常提取；
- 正式模型、公共有效指标、不确定性可用状态；
- 受控发现与限制。

输入样本分析和成果网格分析必须使用不同 DTO、不同标题，不能混称。GET 不得隐式物化或写数据库。

### 2. 三维与切片联动

把真实异常组件接入现有 SuperMap3D iframe v2：

- 组件列表点击后，三维标注高亮并聚焦；
- 三维标注点击后，右侧切换到对应组件；
- 增加 XYZ 轴、Z 深度刻度、等轴/俯视 XY/正视 XZ/正视 YZ 预设；
- 当前 X/Y/Z 切片返回完整场统一阈值下的低/正常/高值比例；
- Volume、Slice、Contour 继续使用现有原生渲染合同，不伪装为同时叠加。

不要做可拖动窗口。优先保证 1920×1080 首屏排版、字号、对齐、无溢出和三维主体面积。

### 3. 成果页信息结构

右侧研判区至少包含：成果概览、异常区域、当前切片、模型与不确定性。底部证据区包含成果组成、深度趋势、连通区比较、切片热力图、模型指标/残差、输入样本、溯源。

不要使用“结论链”“行动链”一类生硬名称。不要写含水性、危险性、储量、成矿、已确认边界等当前证据不支持的结论。

### 4. DeepSeek AI 辅助研判

AI 是可选辅助层，必须建立在确定性分析之后，不能替代数值计算。

- 服务端配置：`DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`、timeout、max tokens；API Key 绝不能进入前端、日志、SQLite、Git 或错误响应。
- 使用标准 OpenAI-compatible `/chat/completions` 和 JSON Output；模型名、base URL 必须可配置，以兼容官方更新或用户中转。
- 显式 `POST /api/results/{result_id}/ai-analysis` 才允许调用外部 API；GET 只读最近一次记录。
- EvidencePacket 只含结构化聚合证据，不发送完整网格、原始点表、本机路径或凭据。
- 输出四个视角：空间格局、模型可靠性、不确定性与风险、复核与下一步检查；另有共识、分歧、复核清单、候选研判路径和限制。候选路径必须写明触发条件、收益、代价和证据引用，不得自动替用户选定。
- 每条主张必须引用当前 EvidencePacket 中的合法 evidence ID；身份必须绑定 `result_id + grid_sha256 + evidence_hash + prompt_version + model`。
- 支持 `quick` 和 `review`；相同身份默认复用，只有 `regenerate=true` 才重新计费。
- DeepSeek 未配置、超时、429、空响应、截断、非 JSON 或合同不合法时，显示类型化降级；规则分析、切片和三维必须继续正常。
- 不显示虚构的 AI 置信度百分比，不保存或展示模型隐藏推理内容。

前端把它放在现有研判区的“规则研判 / AI 辅助”切换中，不要另造一个孤立页面。显示 provider、model、生成时间、prompt 版本和 evidence hash 短码；证据引用应能联动组件或切片。

## 验证要求

- 后端：合成 2D/3D、NoData、分位阈值、深度分层、连通区、只读 API、损坏工件 fail-closed。
- DeepSeek：使用 fake transport 覆盖成功、空内容、截断、超时、429、坏 JSON、未知 evidence ref、身份错配和密钥泄露扫描；无密钥 CI 不访问外网。
- 前端：DTO、空态、结果切换清理、双向联动、AI 四视角/共识/分歧/复核项、离线降级。
- 浏览器：真实电阻率成果、真实组件与切片数据、三种渲染模式、AI mock 联动、1920×1080 无溢出、console/pageerror/未解释网络失败为零。
- 完成前运行计划里的完整矩阵；任何成功结论必须附实际命令与计数。

## 最终汇报

汇报实际实现和浏览器效果，不要只列测试：

1. 真实新增功能及页面入口；
2. 结果网格与输入样本口径如何区分；
3. 三维组件/切片双向联动证据；
4. DeepSeek EvidencePacket、模型配置、降级和密钥保护；
5. 真实测试计数、截图目录、CI 状态；
6. 未解决边界。

完成后保持 PR OPEN，等待用户评审，不要自行合并或发布。
