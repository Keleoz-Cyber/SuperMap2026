# 后端 Agent 提示词：成果真值分析与 DeepSeek 服务

你负责 GeoModelingPlatform v0.9.0 的后端主线。目标不是写演示假数据，而是建立前端可稳定消费的成果网格分析与 AI 辅助研判 API。

## 开始前

- 只在 `D:\study\Contest\Supermap\.worktrees\v0.9.0-visual-product` 和 `feat/v0.9.0-visual-product` 工作；开始时必须核对实际 HEAD 和工作区，不创建并行分支。
- 你是串行开发的第一棒；前端 Agent 尚未开始。
- 完整阅读：
  - `docs/superpowers/specs/2026-08-10-v0.9.0-result-analysis-integration-design.md`
  - `docs/superpowers/plans/2026-08-10-v0.9.0-result-analysis-integration.md`
- 只负责计划 Task 1–5 和 Task 10 的后端部分。不要修改 `web/src/**` 或 iframe。
- 测试先行；不合并、不发布、不写入真实 DeepSeek Key。

## 先冻结前后端合同

最先完成并单独提交：

1. `ResultAnalysisSummary`、切片扩展、`EvidencePacket`、`AIReview` 严格 DTO；
2. 公开路由、查询参数、错误码、状态枚举；
3. 一套确定性 JSON 合同夹具，至少包含 3D 正常、2D 不适用、无不确定性、AI 未配置四种状态；
4. OpenAPI/DTO 测试，保证未知字段和非有限数值 fail-closed。

提交信息建议：`feat: freeze result analysis public contracts`。继续完成全部后端任务；前端 Agent 必须等你的最终汇报和干净 HEAD，不能在检查点提前启动。

## 后端实施范围

- 已物化 GridResult 的统计、p25/p75、低/正常/高值组成、深度分层；
- 复用既有异常算法生成 A/B/C 高值连通区预览，不隐式保存专业异常工件；
- 结构化规则发现、正式模型指标和不确定性可用状态；
- 只读 `GET /api/results/{result_id}/analysis-summary`，不得隐式物化或写数据库；
- 切片统计使用完整成果统一阈值；
- DeepSeek EvidencePacket、evidence hash、quick/review、记录复用和显式 regenerate；
- 服务端 DeepSeek 适配器、SQLite 迁移、POST generate 与 GET latest；
- API Key、路径、请求头、隐藏推理内容不得持久化或进入公共错误。

## 连通性要求

- 所有公共响应必须能被合同夹具完全表示；不要让前端解析内部 ORM 或 metadata 原始字典。
- 每个组件、层段、切片和 AI 证据均带稳定 ID，供三维联动使用。
- AI 引用只能指向当前 EvidencePacket 的合法 ID。
- DeepSeek 未配置/超时/429/坏 JSON 时返回类型化状态，确定性分析照常成功。
- 模型名和 base URL 可配置，支持用户中转；CI 只能使用 fake transport。

## 完成汇报

1. 按 `docs/superpowers/handoffs/2026-08-11-backend-to-frontend-template.md` 写出正式交接文件，文件名固定为 `docs/superpowers/handoffs/2026-08-11-backend-to-frontend.md`，与后端代码一起提交。
2. 最终回复必须完整汇报合同提交 SHA、最终 HEAD、路由清单、JSON 夹具路径、数据库迁移、测试实数、无密钥降级结果、已知问题和前端必须遵守的字段口径。
3. 确认工作区干净，保持 PR OPEN，不合并、不发布，然后停止。

用户会把“前端 Agent 提示词 + 你的完整最终汇报 + 交接文件路径”一起交给下一位 Agent。
