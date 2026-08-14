# API 与 CLI 参考

> 受众：开发者与评测人员。本文是全部 HTTP 端点、CLI 命令与运行环境变量的唯一权威参考。
>
> 更新时间：2026-08-15；适用版本：1.0.0。路径参数用 `{}` 表示；`{dataset_id}`、`{result_id}` 等为对应实体的 UUID。

## 1. 通用约定

- 错误封套：所有非 2xx 响应体为 `{"error":{"code","message","details"}}`；`code` 为类型化错误码（如 `PRESET_NOT_INITIALIZED`、`FOLD_LEAKAGE_DETECTED`、`RENDER_ASSET_CORRUPT`）；消息中的本机路径脱敏。
- 长任务模式：创建类端点返回 202 + 任务身份，客户端轮询状态端点（run / analysis job / render asset）至终态；终态失败可调用对应 retry 产生新任务身份。
- 幂等性：同指纹的诊断、异常提取、渲染资产创建、AI 研判默认复用既有结果（202/200 区分新建与复用）。
- `decimate` 查询参数控制散点抽稀（仅影响预览，不影响计算）；内联数据行数有上限，超限引导改用工件下载。
- 渲染资产下发带 `ETag=sha256` 与 `Cache-Control: immutable`。
- 变异操作全部为显式 POST/DELETE；能力与状态查询一律纯 GET，无隐式副作用。

## 2. HTTP API

### 2.1 健康与基础设施

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 服务状态、版本、UTC 时间 |
| GET | `/api/iserver/status` | iServer 实时探针 |
| POST | `/api/evidence/browser-load` | 登记浏览器加载证据（201） |

### 2.2 案例与回收站

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/cases` | 案例合并列表（内置预置 + 上传），含主打成果直达与主数据版本 |
| POST | `/api/cases` | 创建案例（201） |
| GET | `/api/cases/{case_id}` | 案例详情 |
| GET | `/api/cases/{case_id}/workspace` | 统一工作台 DTO（featured 成果、数据准备状态机、最近实验/成果） |
| GET | `/api/cases/{case_id}/datasets` | 数据版本列表 |
| POST | `/api/cases/{case_id}/datasets/uploads` | multipart 上传（流式哈希、原子落盘；201） |
| DELETE | `/api/cases/{case_id}` | 移入回收站 |
| POST | `/api/cases/{case_id}/restore` | 从回收站恢复 |
| POST | `/api/cases/{case_id}/purge` | 永久删除（请求体 `confirmation_name` 需与案例名完全一致） |
| GET | `/api/cases/{case_id}/formal-selections` | 正式选择历史与可选择性 |
| GET | `/api/trash/cases` | 回收站有界摘要 |

legacy 电阻率兼容端点：`GET /api/cases/resistivity`（遗留详情）、`/publish-status`、`/points?decimate=`；`/voxel-cells` 已类型化退役（410 `LEGACY_RESISTIVITY_RETIRED`）。

### 2.3 数据集

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/datasets/{dataset_id}` | 白名单 DTO |
| GET | `/api/datasets/{dataset_id}/points?decimate=` | 标准化点数据 |
| GET | `/api/datasets/{dataset_id}/inspection?sheet=` | 有界检查（前 20 行、列类型、候选映射） |
| POST | `/api/datasets/{dataset_id}/mapping` | 字段映射 -> 标准化 Parquet |
| POST | `/api/datasets/{dataset_id}/validate` | 质量评估 |
| GET | `/api/datasets/{dataset_id}/quality` | 读取质量报告 |
| POST | `/api/datasets/{dataset_id}/quality/confirm-warnings` | 警告精确集合确认 |
| POST | `/api/datasets/{dataset_id}/abandon` | 放弃未完成数据版本 |

### 2.4 数据级分析（v0.8）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/datasets/{dataset_id}/ml-capability` | 机器学习适用性（supported/experimental/not_recommended） |
| GET | `/api/datasets/{dataset_id}/analysis-summary` | 统计摘要（质量/分布/分位/剖面/分层/异常阈值） |
| GET | `/api/datasets/{dataset_id}/analysis-export?format=json\|csv` | 导出摘要 |

### 2.5 实验与运行

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/experiments` | 创建实验（质量门禁、算法-维度门、ML 适用性校验；201） |
| GET | `/api/experiments/{experiment_id}` | 实验详情 |
| POST | `/api/experiments/{experiment_id}/runs` | 创建运行并入队（同实验并发唯一；201） |
| GET | `/api/experiments/{experiment_id}/candidates` | 最新运行候选 + 公共指标（按 RMSE 排序） |
| GET | `/api/runs/{run_id}` | 运行状态与进度 |
| POST | `/api/runs/{run_id}/cancel` | 取消（排队立即/运行中协作） |
| POST | `/api/runs/{run_id}/retry` | 终态失败重试（新身份；201） |

### 2.6 成果

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/results/{result_id}/materialize` | 幂等物化（全量拟合 + 规则网格落盘；专业候选附不确定性场） |
| GET | `/api/results/{result_id}` | 已物化元数据 + 评估摘要 + 专业能力标记 |
| GET | `/api/results/{result_id}/preview` | 确定性抽稀预览（≤50,000 单元） |
| GET | `/api/results/{result_id}/slices?axis=&index=` | 正交切片（只读持久工件，绝不再插值） |
| POST | `/api/results/{result_id}/select-formal` | 正式成果选择（只读案例 409；201） |
| POST | `/api/results/{result_id}/exports` | 证据 ZIP 导出（201） |
| GET | `/api/exports/{export_id}/download` | ZIP 下载 |
| POST | `/api/results/{result_id}/publications` | 发布请求（固定 `manual_required`；201） |

### 2.7 成果级分析与 AI（v0.9）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/results/{result_id}/analysis-summary` | 已物化网格确定性分析（结构异常组件、基线联动等；LRU 缓存） |
| POST | `/api/results/{result_id}/ai-analysis` | 生成 AI 研判（`mode=quick\|review`；201） |
| GET | `/api/results/{result_id}/ai-analysis/latest?mode=` | 最近 AI 研判（无则 404） |
| GET/POST/DELETE | `/api/settings/ai` | DeepSeek 设置（响应永不含 Key） |
| POST | `/api/settings/ai/test` | 连接测试 |

### 2.8 专业分析（v0.6+）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/datasets/{dataset_id}/professional-diagnostics` | 创建半变异函数诊断（202；同指纹成功幂等 200） |
| GET | `/api/datasets/{dataset_id}/professional-diagnostics` | 诊断列表（最新确认摘要） |
| GET | `/api/professional-diagnostics/{diagnosis_id}` | 诊断状态/指纹/manifest |
| GET | `/api/professional-diagnostics/{diagnosis_id}/variogram?decimate=` | 全向+方向经验半变异函数 bins |
| POST | `/api/professional-diagnostics/{diagnosis_id}/confirm` | 不可变确认快照（note 必填；201） |
| GET | `/api/professional-confirmations/{confirmation_id}` | 确认快照 |
| GET/POST | `/api/analysis-jobs/{job_id}`（/cancel /retry） | 分析任务生命周期（与 run 同合同） |
| GET | `/api/results/{result_id}/professional` | 成果专业证据（能力/参数出处/manifest） |
| GET | `/api/results/{result_id}/folds` | 折分证据（组身份、泄漏检查、逐折指标） |
| GET | `/api/results/{result_id}/residuals?decimate=` | OOF 残差表 |
| GET | `/api/results/{result_id}/uncertainty/{kind}` | 不确定性层预览（`empirical_error` 或 `kriging_std`） |
| POST | `/api/results/{result_id}/anomaly-extractions` | 异常提取（202；同指纹幂等 200） |
| GET | `/api/anomaly-extractions/{extraction_id}` | 状态 + 有界 components |
| POST | `/api/professional-comparisons` | 双候选专业比较（指纹幂等登记；201） |
| GET | `/api/professional-comparisons/{comparison_id}` | 比较结果 |
| GET | `/api/professional-artifacts/{artifact_id}/download` | 白名单工件下载（逐件 SHA-256 校验 fail-closed） |
| GET | `/api/datasets/{dataset_id}/comparison-candidates` | 跨实验候选目录 |
| POST | `/api/candidate-comparisons` | 2-4 候选确定性比较（无持久化） |

### 2.9 渲染（v0.6.1+）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/results/{result_id}/render-capability?field=` | 渲染能力查询（纯只读） |
| POST | `/api/results/{result_id}/render-assets/netcdf?field=` | 物化+创建 NetCDF 渲染资产（201/200/409） |
| GET | `/api/results/{result_id}/render-assets/netcdf?field=` | 资产状态查询 |
| GET | `/api/render-assets/{asset_id}/manifest` | 资产 manifest |
| GET | `/api/render-assets/{asset_id}/volume.nc` | 体数据下发（身份校验 + 当前哈希核验） |
| POST | `/api/render-assets/{asset_id}/slice-exports` | 剖面分析 ZIP（multipart：轴/索引/客户端 PNG） |
| GET | `/api/render-assets/{asset_id}/slice-analysis?axis=&index=` | 权威剖面统计（服务端重算） |

legacy 电阻率渲染三入口（render-capability / render-assets/netcdf / render-sources/import）已类型化 410 退役。

### 2.10 微震（v0.5；v0.7.0 起产品面由预置案例取代，端点保留）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/cases/{case_id}/microseismic-imports` | multipart DAT 包导入（staging + 限额 + 原子建行；201） |
| GET | `/api/datasets/{dataset_id}/derivation` | 派生证据白名单 DTO |
| GET | `/api/datasets/{dataset_id}/derivation/artifacts/{artifact_name}` | 白名单工件下载 |
| GET | `/api/datasets/{dataset_id}/derivation/points?layer=&decimate=` | 诊断点层（accepted/rejected/aggregated） |

### 2.11 演示

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/demo/datasets/platform-demo-3d` | 下载固定演示 CSV（fail-closed） |

## 3. CLI 参考

### 3.1 主 CLI（`geomodeling` = `python -m geomodeling.cli`）

| 命令 | 说明 |
|---|---|
| `validate-data` | 校验标准化/训练/验证 CSV 合同并登记（遗留验收链） |
| `import-predictions` | 导入预测 CSV 并与验证集逐点对齐 |
| `compute-metrics` | 公共指标、分组汇总与基线对比 |
| `register-supermap-results` / `verify-supermap` | SuperMap 成果登记与核验（存在/哈希/行数） |
| `create-model` / `list-models` / `select-models` | 模型任务登记、列表与默认/对照选择 |
| `export-reports` / `run-all` | 验收报告导出 / 顺序执行全部 |
| `demo-check` | 演示前只读预检（阻断项退出码 1；`--json`） |

### 3.2 `geomodeling microseismic`（配置 `config/microseismic.yaml`）

| 命令 | 说明 |
|---|---|
| `inventory` / `parse` / `validate` / `export-reports` / `run-audit` | DAT 清单、解析、合同检查、报告、完整审计 |
| `microseismic derive` | v0.5 派生工作流（审计->局部 XYZ->3σ->黄金门禁->聚合） |
| `microseismic import-case` | DAT 包原子导入为平台案例 |

### 3.3 `geomodeling professional`

| 命令 | 说明 |
|---|---|
| `diagnose` | 创建并同步执行专业诊断 |
| `confirm` | 为成功诊断创建不可变确认快照 |
| `inspect-result` | 输出成果专业证据 |
| `extract-anomalies` | 创建并同步执行异常提取 |
| `compare` | 比较两个成功候选 |

### 3.4 `geomodeling render-grid`

| 命令 | 说明 |
|---|---|
| `import-csv` | 权威规则网格 CSV 原子登记为 legacy 渲染源 |

### 3.5 预置维护（`python -m geomodeling.preset_cli`）

| 命令 | 说明 |
|---|---|
| `analyze-microseismic` / `analyze-resistivity` / `analyze-gas` | 官方候选矩阵分析（27/7/13 候选），产出 canonical JSON 基线报告 |
| `seed-microseismic` / `seed-resistivity` / `seed-gas` | 唯一生产 seed 入口：完整生命周期建案例（幂等；缺源/基线不符 fail-closed） |

## 4. 环境变量

| 变量 | 作用 |
|---|---|
| `GEOMODELING_DATA_DIR` | 运行数据目录（默认 `var/geomodeling/`） |
| `GEOMODELING_CONFIG` | 覆盖默认配置文件路径 |
| `GEOMODELING_FRONTEND_DIST` | 前端静态目录（默认 `web/dist`） |
| `GEOMODELING_METRICS_JSON` / `GEOMODELING_EVIDENCE_DIR` / `GEOMODELING_VOXEL_CACHE_DIR` | 遗留验收链指标/证据/缓存位置 |
| `DEEPSEEK_API_KEY` | DeepSeek 凭据（优先于产品内配置；详见 [product-guide.md](product-guide.md) 第 13 节） |
| `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` / `DEEPSEEK_TIMEOUT_SEC` / `DEEPSEEK_MAX_TOKENS` | DeepSeek 覆盖项 |
