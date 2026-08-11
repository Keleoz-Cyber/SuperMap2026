# 后端到前端交接报告

> 后端 Agent 完成时复制本模板为 `2026-08-11-backend-to-frontend.md`，逐项填写并提交。不得只在聊天中汇报。

## 1. Git 与范围

- 开始 HEAD：`d2347fa` (docs: enforce serial agent handoffs)
- 合同提交 SHA：`495de6c` (feat: freeze result analysis public contracts)
- 最终 HEAD：`7a62603` (feat: add optional DeepSeek assisted result review)
- 分支：`feat/v0.9.0-visual-product`
- 工作区是否干净：是
- 实际完成的 Task：Task 1（合同冻结）、Task 2（网格统计与深度分层）、Task 3（连通区与发现）、Task 4（只读 API）、Task 5（切片共享阈值）、Task 10 后端部分（DeepSeek 适配器、AI 分析服务、API、SQLite v8 迁移）
- 明确未完成的 Task：Task 6-9（前端）、Task 10 前端部分（AIAssistedReview.vue）、Task 11（集成与浏览器验收）

## 2. 公共合同

- DTO/Schema 文件：
  - `src/geomodeling/platform/result_analysis_contracts.py` — `ResultAnalysisSummary` 及全部子 DTO
  - `src/geomodeling/platform/ai_analysis_contracts.py` — `EvidencePacket`、`AIReview`、`AIAnalysisRecord`、`AIAnalysisRequest`
- OpenAPI 路由：
  - `GET /api/results/{result_id}/analysis-summary` — 只读成果分析摘要
  - `POST /api/results/{result_id}/ai-analysis` — 显式生成 AI 辅助研判
  - `GET /api/results/{result_id}/ai-analysis/latest` — 只读最近 AI 记录
- 查询参数与范围：
  - `depth_bins`：默认 8，范围 2–32
  - `component_limit`：默认 8，范围 1–20
  - `min_support_nodes`：默认 2，范围 1–10000
  - POST body：`{mode: "quick"|"review", regenerate: bool}`
- 状态枚举：
  - `DepthProfileStatus`：`applicable` / `not_applicable`
  - `ThresholdSource`：`full_grid_quartile`
  - `FindingKind`：`dominant_depth_interval` / `largest_high_component` / `boundary_contact` / `formal_model` / `uncertainty_availability`
  - `FindingConfidence`：`high` / `medium` / `low`
  - `AIAnalysisStatus`：`succeeded` / `unavailable` / `error`
  - `AIAnalysisMode`：`quick` / `review`
- 错误码：
  - `RESULT_ANALYSIS_NO_VALID_CELLS` — 网格无有效体元
  - `RESULT_NOT_MATERIALIZED` — 成果未物化（404）
  - `AI_ANALYSIS_UNAVAILABLE` — AI 输出无效或不可用
  - `AI_ANALYSIS_NOT_FOUND` — 无 AI 记录（404）
  - `DEEPSEEK_NOT_CONFIGURED` / `DEEPSEEK_TIMEOUT` / `DEEPSEEK_RATE_LIMITED` / `DEEPSEEK_HTTP_ERROR` / `DEEPSEEK_EMPTY_RESPONSE` / `DEEPSEEK_TRUNCATED` / `DEEPSEEK_MALFORMED_JSON`
- JSON 合同夹具路径：
  - `tests/fixtures_result_analysis/3d_normal.json`
  - `tests/fixtures_result_analysis/2d_not_applicable.json`
  - `tests/fixtures_result_analysis/no_uncertainty.json`
  - `tests/fixtures_result_analysis/ai_not_configured.json`
- result/grid/evidence 身份规则：
  - `result_id` + `grid_sha256` + `analysis_version`（`result_analysis.v1`）绑定成果分析
  - `evidence_hash`（SHA-256 of canonical JSON of EvidencePacket）+ `prompt_version`（`ai_review.v1`）+ `provider` + `model` + `mode` 绑定 AI 记录
  - 切换成果后 `grid_sha256` 变化，旧 AI 记录不显示

## 3. 后端功能

- 成果网格统计：有效体元（`is_nodata == false` 且值有限）的 min/max/mean/median/p25/p75；NoData 与 NaN/Inf 排除
- 深度分层：3D 按 Z 轴等距分箱，每节点进入一个层段，最后一箱含上界；2D 返回 `not_applicable`
- 连通区：复用 `extract_anomalies`（六邻接 3D / 四邻接 2D），`value >= p75`，按 support_measure 降序排序，A–Z 标签，不创建 AnomalyExtractionRecord
- 切片扩展：`_statistics()` 增加 `low_count/normal_count/high_count/low_ratio/normal_ratio/high_ratio/thresholds` 字段，使用完整网格 p25/p75 阈值；旧字段 `count/min/max/mean/std/p10/p50/p90` 不变
- 模型/不确定性：从 CandidateResult.metrics_json 读取 RMSE/MAE/R²/coverage/common_valid_count；不确定性层从 `professional_dir` 加载
- DeepSeek quick/review：`quick` 单次结构化分析；`review` 复核模式（prompt 中要求先分析再复核）；相同 evidence_hash + prompt_version + model + mode 默认复用，`regenerate=true` 重新计费
- 无密钥和离线降级：`DeepSeekAdapter.from_env()` 返回 None 时返回 typed `unavailable` 状态；规则分析照常成功
- SQLite 版本与迁移：v7 -> v8，新增 `ai_analysis_records` 表，迁移函数 `_create_v8_tables`，幂等

## 4. 配置与运行

- 新环境变量（不得写真实值）：
  - `DEEPSEEK_API_KEY` — 必填，仅服务端环境变量
  - `DEEPSEEK_BASE_URL` — 默认 `https://api.deepseek.com`
  - `DEEPSEEK_MODEL` — 默认 `deepseek-v4-flash`（官方 V4 Flash 请求 ID）
  - `DEEPSEEK_TIMEOUT_SEC` — 默认 90
  - `DEEPSEEK_MAX_TOKENS` — 默认 4096
- 成果研判固定使用 JSON Output，并显式发送
  `thinking={"type":"disabled"}`、`temperature=0`；V4 默认思考模式不适合该低延迟结构化接口。
- EvidencePacket 会读取候选成果已经登记的公共有效集、RMSE、MAE、R²、覆盖率、
  输入质量与正式选择 ID，确保 AI 研判不与同页规则研判自相矛盾。
- 禁止领域结论按句校验；“不可视为真实地质体积”等明确否定边界允许展示，
  正向或裸领域断言继续 fail-closed。
- 启动命令：`uvicorn geomodeling.api.app:app --host 127.0.0.1 --port 8000`
- Mock/Fake DeepSeek 使用方式：构造 `DeepSeekAdapter(api_key="sk-test", _transport=FakeTransport(response_factory))`，FakeTransport 实现 `post(url, *, json, headers, timeout) -> httpx.Response`
- 真实 Key 可选验证方式：设置 `DEEPSEEK_API_KEY` 环境变量后 POST `/api/results/{result_id}/ai-analysis`

## 5. 验证证据

- 后端测试命令和实数：
  - `python -m pytest tests/test_result_analysis.py tests/test_result_analysis_api.py tests/test_slice_analysis.py tests/test_deepseek_adapter.py tests/test_ai_analysis.py tests/test_schema_v8_migration.py tests/test_anomaly_extraction.py tests/test_platform_results.py tests/test_render_asset_slices.py tests/test_rendering_api.py tests/test_case_lifecycle.py tests/test_case_workspace_api.py tests/test_professional_api.py -q`
  - 231 passed, 0 failed
- API 合同测试：`tests/test_result_analysis.py` 37 passed（合同校验 + JSON 夹具），`tests/test_result_analysis_api.py` 7 passed
- Secret scan：`grep -r "sk-[a-zA-Z0-9]" src/ tests/` 无匹配
- 真实数据验证：未执行（后端 Agent 不执行浏览器验收）
- 未执行及原因：`tests/test_platform.py` 等依赖 `超图杯资料/标准化数据/地下电阻率节点_标准化.csv`，该文件在 worktree 中不存在（预置数据问题，非本次改动引入）

## 6. 前端必须遵守

- 必须使用的字段：
  - `ResultAnalysisSummary.identity.{result_id, grid_sha256, analysis_version, dimension, coordinate_type}`
  - `ResultAnalysisSummary.grid.{valid_count, nodata_count, min, max, mean, median, p25, p75}`
  - `ResultAnalysisSummary.thresholds.{low, high, source, method}`
  - `ResultAnalysisSummary.composition.buckets[].{category, count, ratio}` — 三类：low/normal/high
  - `ResultAnalysisSummary.depth_profile.{status, bins[]}` — 2D 时 status=`not_applicable`，bins=[]
  - `ResultAnalysisSummary.components_preview.{threshold, connectivity_rule, total, returned, rows[]}`
  - `ResultAnalysisSummary.components_preview.rows[].{rank, label, component_id, support_measure, support_unit, bounds, centroid, value_max, touches_grid_boundary}`
  - `ResultAnalysisSummary.findings[].{id, kind, title, statement, evidence[], confidence, limitations[], spatial_target}`
  - `ResultAnalysisSummary.model_evidence.{algorithm, metrics, common_valid_count, formal_selection_id}`
  - 切片统计新增：`statistics.{low_count, normal_count, high_count, low_ratio, normal_ratio, high_ratio, thresholds}` — thresholds 为 null 时表示未提供
  - AI 记录：`AIAnalysisRecord.{status, review, error_code, error_message, provider, model, mode, evidence_hash, prompt_version, created_at}`
  - AI Review：`AIReview.{spatial_pattern, model_reliability, uncertainty_and_risk, review_and_next_checks, consensus}` — 每个视角含 `{summary, evidence_refs[]}`
- 可空/不适用语义：
  - 2D 成果 `depth_profile.status` = `not_applicable`，`bins` = `[]`
  - 无不确定性时 `components_preview.rows[]` 的 `empirical_error_scale_*` / `kriging_std_*` 字段为 `null`
  - `model_evidence.formal_selection_id` / `formal_selection_note` 为 `null` 表示未选择正式模型
  - `findings[].spatial_target` 为 `null` 表示无空间目标
  - AI `status` = `unavailable` 时 `review` = `null`，`error_code` = `DEEPSEEK_NOT_CONFIGURED`
  - AI `status` = `error` 时 `review` = `null`，有 `error_code` 和 `error_message`
  - 切片 `thresholds` = `null` 表示未提供完整网格阈值
- 严禁前端推导的字段：
  - 阈值（low/high）必须来自后端，前端不得自行计算 p25/p75
  - 连通区排序、标签、统计必须来自后端，前端不得重排或重算
  - 发现（findings）文案必须来自后端，前端不得自动生成地质结论
  - AI evidence_refs 必须指向后端 EvidencePacket 中的合法 ID，前端不得创建新引用
  - support_measure 不得换名为"真实体积/面积"
- 组件/层段/切片 evidence ID：
  - 组件：`component-{component_id}`（如 `component-1`、`component-2`）
  - 深度层段：`depth_bin-{index}`（从 0 开始）
  - 全局：`result_grid`、`depth_profile`、`composition`、`model_evidence`、`uncertainty`、`input_quality`、`current_slice`
- 结果切换清理条件：`result_id` 或 `grid_sha256` 变化时立即清空旧分析、旧发现和旧 AI 记录

## 7. 已知问题与风险

- 阻断项：无
- 非阻断项：
  - `tests/test_platform.py` 等测试依赖的预置数据文件在 worktree 中缺失（预置问题，非本次引入）
  - `_try_load_uncertainty_layer` 在 route 中使用硬编码文件名，后续可考虑复用 `_LAYER_ARTIFACTS`
  - AI prompt 构造目前为系统+用户两段，未实现独立复核提示（review 模式仅在 system prompt 中追加要求）
- 建议前端优先验证：
  1. `GET /api/results/{result_id}/analysis-summary` 返回的 DTO 结构与 `ResultAnalysisSummary` 合同一致
  2. 切片统计中 `thresholds` 字段的存在和值
  3. AI `status=unavailable` 时前端正确显示配置说明而非错误
  4. AI `status=succeeded` 时四视角卡片、共识/分歧、决策选项正确渲染
  5. 结果切换时旧分析清空

## 8. 后端 Agent 完整最终汇报

后端 Agent 已完成 Task 1–5 和 Task 10 后端部分。

**合同冻结**（commit `495de6c`）：
- 创建 `result_analysis_contracts.py`（17 个 DTO）和 `ai_analysis_contracts.py`（15 个 DTO）
- 4 个 JSON 合同夹具覆盖 3D 正常、2D 不适用、无不确定性、AI 未配置
- 21 个合同测试验证未知字段拒绝、非有限值 fail-closed

**成果分析**（commit `ec4a5ce`）：
- `result_analysis.py` 实现 `analyze_result_grid()`：统计、深度分层、连通区预览、结构化发现
- 37 个测试覆盖有效值计数、阈值计算、组成比例、深度分箱、2D 不适用、零有效值 fail-closed、两区域分离、A/B 标签、排序、边界接触、发现种类、禁止词扫描

**只读 API**（commit `ddc824b`）：
- `GET /api/results/{result_id}/analysis-summary`，支持 depth_bins/component_limit/min_support_nodes 查询参数
- LRU 缓存（maxsize=32），重复请求字节一致
- 7 个 API 测试覆盖 200/404/422、幂等性、无工件创建、2D 深度不适用

**切片共享阈值**（commit `21f57a9`）：
- `slice_analysis.py` 增加完整网格 p25/p75 阈值的 low/normal/high 计数和比例
- 旧字段不变，5 个新测试覆盖共享阈值、与切片局部分位差异、旧字段不变、无阈值时 null、全 NoData 零计数

**DeepSeek AI 辅助研判**（commit `7a62603`）：
- `integrations/deepseek.py`：OpenAI-compatible 适配器，JSON Output 模式，13 个测试覆盖成功/空/截断/超时/429/非 JSON/API Key 不暴露
- `platform/ai_analysis.py`：EvidencePacket 构建、evidence_hash 计算、prompt 构造、AI 输出校验（证据引用 + 禁止词）、记录复用与 regenerate
- `api/routes/ai_analysis.py`：POST generate + GET latest
- SQLite v8 迁移：`ai_analysis_records` 表，2 个迁移测试
- 15 个 AI 分析测试覆盖未配置降级、成功、复用、regenerate、超时、latest 查询、API Key 不入数据库、证据引用校验、禁止词拒绝

测试总数：231 passed, 0 failed（不含预置数据缺失的跳过文件）。

工作区干净，PR 保持 OPEN，未合并、未发布。
