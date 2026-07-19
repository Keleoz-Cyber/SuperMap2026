# Kimi 3 长程任务：微震 v0.2a 数据审计与标准化底座

> 使用方式：将本文件完整作为 Kimi 3 压缩上下文后的恢复任务说明。
> 项目目录：`D:\study\Contest\Supermap\GeoModelingPlatform`
> 当前开发分支：`feat/microseismic-data-audit-v0.2a`

## 1. 角色与目标

你是 `GeoModelingPlatform` 项目的技术负责人和主开发者。项目已发布电阻率 MVP `v0.1.0`，稳定基线提交为：

`b160405ac10b3eb0b5973481a967a17d9bbf7084`

当前任务是完成微震 `v0.2a` 的“数据审计与标准化底座”。本阶段只解决：

- 原始文件是否完整、可读取和可追溯；
- 源记录、有效数值记录和异常记录的准确数量；
- 测线、测点、点间距及来源冲突；
- 三张微震标准表；
- 数据契约、验证、问题清单、审计日志和报告；
- 可在 CI 运行的便携测试和本地真实数据回归。

本阶段**不做**完整二维/三维坐标重建、SuperMap 三维点导入、三维克里金、DSI-like、体元模型、等值面或与电阻率融合。

## 2. 当前工作区保护

当前已经位于：

`feat/microseismic-data-audit-v0.2a`

工作区中可能已经存在对 `findings.md`、`task_plan.md` 或其他文件的未提交修改。这些修改属于当前任务，必须保留。

开始恢复工作时先执行：

```powershell
git status --short --branch
git diff --check
git diff -- findings.md task_plan.md progress.md
```

不得执行：

- `git reset --hard`
- `git clean -fd`
- `git checkout -- .`
- 强制切换或覆盖当前分支
- 删除不理解的现有修改

先阅读当前改动和已有实现，再继续增量开发，不要从头重建项目。

## 3. 原始资料保护

原始资料目录：

`..\超图杯资料\参考资料\李含淼\2026-李含淼-微震测量与测线数据`

该目录只读。不得移动、重命名、覆盖、修复或清洗其中的 DAT、XLSX、PDF 和图片。

不得把以下内容提交到 Git：

- 原始 DAT；
- `点间距.xlsx`；
- 论文 PDF；
- 测线图片；
- 完整的微震派生观测表；
- UDB/UDBX；
- `outputs/`、`artifacts/`、`logs/`；
- 缓存、虚拟环境和密钥。

完整派生成果写入项目内被 Git 忽略的目录，例如：

`outputs/microseismic_v0.2a/`

Git 只提交代码、配置、数据契约、质量摘要、小型人工测试样例和测试。

## 4. 必须重新阅读的材料

项目内：

- `README.md`
- `KIMI3_MASTER_PROMPT.md`
- 本文件
- `开发交接包/00_项目总览/README.md`
- `开发交接包/00_项目总览/开发交接包设计说明.md`
- `开发交接包/03_数据规范/数据契约.md`
- `docs/architecture.md`
- `docs/acceptance.md`
- `docs/progress.md`
- `config/default.yaml`
- 当前 `src/geomodeling/` 和 `tests/`
- `findings.md`、`task_plan.md`、`progress.md`

只读研究资料：

- `../超图杯资料/参考资料/李含淼/2026-李含淼-基于微震测量数据的地下岩石结构三维重建研究.pdf`
- 微震资料目录中的 22 个 DAT；
- `点间距.xlsx`；
- `三条测线 (压缩).jpg`。

原始大图 `三条测线.jpg` 已按用户要求删除。不得把它当成缺失阻塞，不得恢复或重新生成它，只使用：

`三条测线 (压缩).jpg`

## 5. 已实测确认的 DAT 格式与读取根因

22 个 DAT 总大小只有 `66,880` 字节，平均约 `3 KB`，不是数据量过大。

DAT 是 ASCII 空白分隔文本，表头为：

```text
WL/2(km)          Vx
```

Kimi 的通用 `Read` 工具读取失败，主要原因是每个 DAT 文件末尾含有一个 `NUL` 字节伪行，通用文本读取器可能把文件判断为二进制或非法文本。

必须实现稳定解析器：

1. 以二进制或显式 ASCII 方式读取；
2. 保留文件原始 SHA-256；
3. 识别尾部 `NUL` 字节；
4. 只把尾部 NUL 识别为文件终止伪行，不计入样本；
5. 在质量报告中记录每个文件的 NUL 终止情况；
6. 按空白分隔解析两列；
7. 不得修改原始 DAT。

可以使用 pandas 的空白分隔解析，但必须在业务层明确处理 NUL 和特殊 NaN token，不能依赖默认行为碰巧跳过。

## 6. 已确认的记录数口径

这是本阶段最重要的修正，旧提示词中“2,005 条原始记录”的表述不够准确。

### 6.1 文件解析层

- 22 个 DAT；
- 通用 pandas 初读为 2,028 行；
- 其中 22 行是每个文件末尾的 NUL 伪行；
- 排除 NUL 伪行后有 **2,006 条真实源记录**。

### 6.2 数值有效层

`W8.dat` 文件第 2 行为：

```text
0.050000        1.#QNAN0
```

`1.#QNAN0` 是旧式 Windows/MSVC NaN token，不是有限数值。

因此：

- `source_record_count = 2006`
- `invalid_numeric_count = 1`
- `valid_numeric_count = 2005`

### 6.3 分线统计

源记录统计：

- L1：823，其中 1 条为 W8 的无效数值；
- L2：819；
- L3：364；
- 合计：2,006。

有限有效数值统计：

- L1：822；
- L2：819；
- L3：364；
- 合计：2,005。

论文表格中的 `823/818/364=2005` 与文件事实不同，必须登记为来源冲突，不得把记录从 L1 移到 L2 或反向调整以迎合论文。

## 7. W8 特殊值处理

`W8.dat` 第 2 行必须进入标准化源记录表，并保留：

- 原始 `WL/2(km)` token；
- 原始 `Vx` token：`1.#QNAN0`；
- 原始文件名；
- 源文件行号；
- `is_numeric_valid=false`；
- 对应质量问题代码；
- 标准化数值字段为空；
- 不进入有限数值统计。

禁止：

- 把它改成 0；
- 静默删除；
- 自动插值后覆盖原值；
- 把它算入 2,005 条有限有效记录；
- 将该问题与论文所述“删除 80 条异常值”混为一谈。

建议问题代码：

`SOURCE_SPECIAL_NAN_TOKEN`

## 8. 测线与测点范围

正式测点文件共 22 个：

- L1：`W1.dat`—`W9.dat`，对应 W1—W9；
- L2：`WD12-Vx.dat`—`WD20-Vx.dat`，对应 W12—W20；
- L3：`WD24-Vx.dat`—`WD27-Vx.dat`，对应 W24—W27。

W28 不进入正式 L3 标准集合、累计距离、清洗集合或模型输入。

W28 只作为论文图、点间距资料或来源描述冲突登记。

L3 正式点序为 W24—W27。已有间距证据：

- W24—W25：800 m；
- W25—W26：320 m；
- W26—W27：335 m。

W28 相关的 350 m 只作为冲突信息，不进入正式累计距离。

## 9. 几何边界

v0.2a 只允许建立一维沿测线距离：

`cumulative_s_m`

必须保存：

- 点序；
- 前一测点；
- 与前一点间距；
- 累计距离；
- 点序来源；
- 间距来源；
- 置信状态。

不得在 v0.2a 生成或声称已确认：

- 真实 X/Y；
- 精确局部 X/Y；
- 绝对地理坐标；
- EPSG；
- 精确方位角；
- 由图片像素推导的测线角度；
- 深度到 Z 的未经确认换算。

未确认的 `x_local_m`、`y_local_m`、`derived_depth_m`、`derived_z_m` 必须为空，并带状态字段说明原因，不能填 0。

## 10. 源字段语义边界

DAT 源字段 `WL/2(km)` 必须原样保留。

在获得直接来源证据前：

- 不得静默改名为 `Depth`；
- 不得乘常数后称为深度；
- 不得直接映射为 Z；
- 不得猜测其正负方向。

如需要派生字段，必须独立设置：

- `derived_depth_m`
- `derived_z_m`
- `depth_derivation_status`
- `depth_derivation_source`

当前这些派生字段应保持空值或 `unconfirmed`。

## 11. 论文清洗冲突

论文材料提及删除 80 条异常数据，但当前存在：

- `80/2005 ≈ 3.99%`，不是材料中写的 3.59%；
- “线性插值”与“最近 5 点 IDW”两种处理方法冲突。

v0.2a 不生成正式清洗结果。

允许：

- 登记 80 条和比例冲突；
- 记录两种候选方法；
- 生成带明确 `candidate` 状态的实验性影响报告。

禁止：

- 选择任一候选方法作为正式规则；
- 删除源记录；
- 覆盖原始 Vx；
- 将插补值称为原始测量值；
- 只保留 1,925 行而丢弃源记录。

## 12. 三张标准表

完整本地输出写入：

`outputs/microseismic_v0.2a/`

### 12.1 `survey_lines.csv`

至少包含：

- `line_id`
- `point_start`
- `point_end`
- `formal_point_count`
- `source_record_count`
- `valid_numeric_count`
- `geometry_status`
- `crs_type`
- `origin_status`
- `direction_status`
- `geometry_source`
- `source_confidence`
- `notes`

### 12.2 `survey_points.csv`

至少包含：

- `point_id`
- `original_point_label`
- `source_file_id`
- `line_id`
- `sequence_on_line`
- `previous_point_id`
- `interval_from_previous_m`
- `cumulative_s_m`
- `interval_source`
- `order_source`
- `included_in_formal_set`
- `exclusion_reason`
- `source_record_count`
- `valid_numeric_count`
- `coordinate_status`
- `x_local_m`
- `y_local_m`
- `z_reference_status`
- `source_confidence`
- `notes`

### 12.3 `velocity_samples.csv`

必须保存 **2,006 条真实源记录**，至少包含：

- `sample_id`
- `point_id`
- `line_id`
- `source_file_id`
- `source_file_name`
- `source_line_number`
- `wl_half_km_raw_token`
- `vx_raw_token`
- `wl_half_km_value`
- `vx_value`
- `source_unit`
- `is_numeric_valid`
- `invalid_reason`
- `quality_flags`
- `included_in_raw`
- `included_in_valid_numeric`
- `included_in_clean_candidate`
- `outlier_reason`
- `imputed`
- `imputation_method`
- `cleaning_version`
- `derived_depth_m`
- `derived_z_m`
- `depth_derivation_status`
- `notes`

必须满足：

- 表总行数 2,006；
- 有限有效数值 2,005；
- 无效数值 1；
- W8 特殊行可完整追溯；
- 每行可反查原始文件和源行号；
- 不把 NUL 伪行写入表；
- 不生成伪造 XY/Z。

## 13. 文件清单

生成：

`source_manifest.json`

每个 DAT 至少登记：

- `source_file_id`
- 相对路径；
- 原始文件名；
- 文件大小；
- SHA-256；
- 修改时间；
- 编码；
- 表头原文；
- NUL 终止状态；
- 推断测点；
- 推断测线；
- 源记录数；
- 有效数值数；
- 无效数值数；
- 解析状态；
- 质量问题。

处理前后原始文件 SHA-256 必须一致。

## 14. 数据契约与问题清单

建立 Pydantic 契约和结构化验证报告，至少验证：

- 22 个正式 DAT；
- L1/L2/L3 测点数为 9/9/4；
- 源记录 823/819/364，共 2,006；
- 有效数值 822/819/364，共 2,005；
- 无效数值恰为 1；
- 无效值来自 W8 的 `1.#QNAN0`；
- 22 个 NUL 文件终止符不计入样本；
- 每个正式测点唯一对应一个 DAT；
- source file + source line 唯一；
- sample_id 唯一；
- W28 不进入正式集合；
- 正式累计距离单调且可追溯；
- 未确认坐标和 Z 保持空值；
- 原始 SHA-256 不变。

至少登记以下问题：

- `SOURCE_NUL_TERMINATOR`
- `SOURCE_SPECIAL_NAN_TOKEN`
- `LINE_COUNT_CONFLICT`
- `L3_W28_SOURCE_CONFLICT`
- `L3_W28_INTERVAL_EXCLUDED`
- `WL_HALF_MEANING_UNCONFIRMED`
- `DEPTH_Z_DERIVATION_UNCONFIRMED`
- `ABSOLUTE_COORDINATES_UNAVAILABLE`
- `LINE_AZIMUTH_UNCONFIRMED`
- `CLEANING_RATE_CONFLICT`
- `CLEANING_METHOD_CONFLICT`

每个问题包含：

- severity；
- affected_scope；
- evidence；
- source_a/source_b；
- current_handling；
- blocks_geometry；
- blocks_cleaning；
- blocks_interpolation。

## 15. CLI

优先使用 Typer 子命令组，建议：

```text
geomodeling microseismic inventory
geomodeling microseismic parse
geomodeling microseismic validate
geomodeling microseismic export-reports
geomodeling microseismic run-audit
```

若现有架构不适合子命令组，可以使用一致的平铺命令，但不要把全部微震逻辑堆入 `cli.py`。

完整流程示例：

```powershell
python -m geomodeling.cli microseismic run-audit `
  --config config/microseismic.yaml `
  -o outputs/microseismic_v0.2a_verify
```

`run-audit` 依次完成：

1. 文件发现与 SHA-256；
2. ASCII/NUL 格式探测；
3. 2,006 条源记录解析；
4. 特殊 NaN 识别；
5. 三张标准表；
6. 一维累计距离；
7. 契约验证；
8. 问题清单；
9. JSON/Markdown 报告；
10. 审计日志。

阻断问题应使命令返回非零退出码，但仍应尽量输出诊断报告。

## 16. 报告

至少生成：

- `source_manifest.json`
- `survey_lines.csv`
- `survey_points.csv`
- `velocity_samples.csv`
- `microseismic_validation.json`
- `microseismic_data_quality.md`
- `microseismic_issue_list.json`
- `microseismic_issue_list.md`
- `microseismic_data_dictionary.md`
- `microseismic_audit_summary.md`

报告必须明确解释：

- 2,028 个解析行、22 个 NUL 伪行、2,006 条源记录、2,005 条有效数值之间的关系；
- W8 特殊 NaN；
- 源记录统计与有效数值统计；
- 论文分线统计冲突；
- W28 的处理；
- `WL/2(km)` 含义边界；
- 清洗比例和方法冲突；
- 为什么当前没有 XY/Z；
- 当前能做与不能做的工作。

## 17. 测试

### 17.1 便携测试

使用小型人工 fixture，不复制真实研究数据。至少覆盖：

- ASCII 空白分隔解析；
- 尾部 NUL；
- `1.#QNAN0`；
- 普通 NaN、Infinity 和文本；
- 空文件和缺字段；
- 源 token 与标准化值同时保留；
- NUL 不计入记录；
- 无效数值行保留但不计入有效数值；
- 文件/行追溯；
- W28 排除；
- cumulative_s_m；
- 不生成伪造 XY/Z；
- 数量契约；
- 问题清单；
- 报告和审计日志；
- blocker 返回非零退出码。

### 17.2 本地真实数据回归

使用 `local_data` 标记，至少断言：

- 22 个 DAT；
- 22 个 NUL 终止符；
- 2,006 条源记录；
- 1 条无效数值；
- 2,005 条有限有效数值；
- 源记录 823/819/364；
- 有效数值 822/819/364；
- W8 特殊值可追溯；
- W28 未进入正式集合；
- 三张表生成；
- 原始 SHA-256 不变；
- 没有伪造 XY/Z。

真实资料不存在时明确 skip。GitHub Actions 只运行便携测试。

## 18. v0.1 回归保护

不得破坏电阻率功能。最终重新执行：

```powershell
python -m pip install -e ".[test]"
geomodeling --help
python -m pytest -q
python -m pytest -q -m "not local_data"
python -m pytest -q -m local_data
python -m geomodeling.cli run-all -o outputs/v0.2a_rho_regression
python -m geomodeling.cli verify-supermap -o outputs/v0.2a_rho_regression
git diff --check
```

电阻率关键结果保持：

- 17,549/15,827/1,722；
- 264/29 空间柱，重叠 0；
- 五模型均 1,481 valid、241 NoData、XY mismatch 0；
- `baseline_passed=True`；
- `dataset_verified=False`。

## 19. 明确禁止的范围

v0.2a 不实现：

- 完整二维局部 XY；
- 绝对坐标或 EPSG；
- 未确认的深度/Z 换算；
- SuperMap 三维点导入；
- 三维插值、克里金或 DSI-like；
- 体元栅格或等值面；
- 电阻率融合；
- 瓦斯模块；
- Web 前端；
- iDesktopX 自动点击；
- 自动地质结论。

## 20. Git 与 PR

继续在：

`feat/microseismic-data-audit-v0.2a`

开发。不要重新创建或覆盖分支。

建议提交：

1. `feat: add microseismic source inventory and contracts`
2. `feat: parse and validate raw microseismic samples`
3. `feat: add survey distance and conflict reporting`
4. `test: add portable and local microseismic regression tests`
5. `docs: document v0.2a data quality and v0.2b gates`

提交前检查：

- 原始 DAT、PDF、XLSX 和图片未跟踪；
- 完整派生表未跟踪；
- outputs/artifacts/logs 未跟踪；
- 无缓存和密钥；
- 无不必要的绝对本机路径；
- `git diff --check` 通过；
- 全量测试通过。

推送当前分支并创建 PR：

- base：`main`
- head：`feat/microseismic-data-audit-v0.2a`
- 标题：`feat: add microseismic data audit foundation`
- 不要合并；
- 不删除远程分支；
- 不创建标签或 Release。

## 21. 完成汇报

最终必须报告：

- 分支、提交和 PR 链接；
- 新增命令；
- DAT 文件数与大小；
- NUL 终止符数量；
- 源记录数、有效数值数、无效数值数；
- L1/L2/L3 的源记录和有效数值统计；
- W8 特殊记录处理；
- 三张表行数；
- 原始 SHA-256 保护结果；
- 便携、真实数据和全量测试；
- 电阻率 v0.1 回归；
- blocker/warning；
- 当前能力边界；
- v0.2b 前置确认项；
- PR 仍未合并。

除非出现 GitHub 登录失效、原始文件缺失、无法安全识别 DAT 格式，或必须由用户决定具有科学含义的冲突处理规则，否则请自主持续完成，不要频繁询问小问题。
