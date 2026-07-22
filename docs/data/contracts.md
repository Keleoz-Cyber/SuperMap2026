# 数据契约

> 当前版本适用于：电阻率 v0.1.0 已发布基线 + 已合并的微震 v0.2a 数据审计底座。
> 字段含义、单位、坐标或 Z 方向没有直接来源证据时必须标记为未确认，禁止猜测。

## 1. 总原则

1. 原始观测只读，任何清洗、拆分、插值和可视化都生成新数据，绝不覆盖上游。
2. 字段名、字段别名和显示标题分开管理；SQL、程序和交换文件只使用真实字段名，禁止把显示别名拼入 SQL。
3. 实测值、预测值和 NoData 分开表达；不得用数值 0 替代空值。
4. 每个数据集和模型成果必须有版本、来源、生成方法和输入哈希。
5. 代码中的数据路径、模型名称、阈值和参数必须配置化，不硬编码在业务逻辑中。
6. 任务成功必须同时满足状态、文件/对象存在、记录或对象数合理、内容可读取；空数据集和失败任务不得登记为正式成果。

## 2. 原始资料与派生数据分层

原始资料保存在相邻的只读目录 `../超图杯资料`；代码项目内的派生成果写入被 Git 忽略的 `outputs/`、`artifacts/`、`logs/`。

| 层级 | 类型标识 | 说明 | 是否可覆盖 |
|---|---|---|---|
| L0 | `raw_observation` | 论文配套 DOC、DAT、NODE、XLSX 等原始记录 | 否 |
| L1 | `standardized_observation` | 字段与数值类型统一、保留来源标识的观测数据 | 否 |
| L2 | `train_validation_split` | 可复现划分的训练集、验证集及划分摘要 | 否 |
| L3 | `model_result` | 插值预测、规则网格、体元、模型元数据和质量指标 | 仅允许新版本 |
| L4 | `visual_derivative` | 切片、截图、图例、布局、等值面和演示场景 | 允许重建，不得反写 L0—L3 |

任何派生步骤都不得覆盖上一步数据。

## 3. 来源清单与 SHA-256

1. 所有数据集至少登记：`dataset_id`、`dataset_type`、`version`、`source_path`、`sha256`（64 位小写十六进制）、`row_count`、`created_at`、`created_by`、`source_reference`、`quality_status`（`unreviewed/passed/warning/failed`）。
2. `dataset_id` 必须稳定唯一，不能使用易变绝对路径。
3. 微震 `source_manifest.json` 的 `relative_path` 使用相对于项目根目录（或配置 `source.data_dir`）的稳定相对路径，禁止输出带盘符的绝对本机路径。
4. 处理前后原始文件的 SHA-256 必须一致；微震审计将源文件哈希不变性作为契约检查项。
5. 原始 DAT、PDF、XLSX、图片、UDB/UDBX、完整派生观测表、`outputs/`、`artifacts/`、`logs/`、缓存、虚拟环境和密钥均不得提交到 Git。

## 4. 电阻率标准表与预测表

### 4.1 权威标准文件

路径相对于代码项目根目录，数据实际保存在相邻只读资料目录：

| 数据集 | 相对路径 | 预期记录数 |
|---|---|---:|
| 标准化源数据 | `../超图杯资料/标准化数据/地下电阻率节点_标准化.csv` | 17,549 |
| 训练集 | `../超图杯资料/标准化数据/地下电阻率节点_训练集90.csv` | 15,827 |
| 验证集 | `../超图杯资料/标准化数据/地下电阻率节点_验证集10.csv` | 1,722 |

训练集与验证集按完整 `(X,Y)` 空间柱划分，空间柱交叉数必须为 0（训练 264 柱、验证 29 柱）。划分种子为 `supermap-rho-block-cv-v1`。

### 4.2 CSV 结构

编码 UTF-8，逗号分隔，首行字段名 `X,Y,Z,RHO`：

| 字段 | 类型 | 单位/方向 | 校验规则 |
|---|---|---|---|
| `X` | float64 | 米；局部平面 X | 有限数值 |
| `Y` | float64 | 米；局部平面 Y | 有限数值 |
| `Z` | float64 | 米；当前文件使用负高程/向下为负 | 有限数值；不得在导入时再次取负 |
| `RHO` | float64 | 电阻率；单位待来源确认 | 有限且大于 0；不允许 `-9999` |

当前坐标为局部平面坐标：`crs.type = local_engineering`、`crs.epsg = null`、水平/垂直单位 m、`z_positive = up`。不附加未经证实的 EPSG。

校验顺序：UTF-8 与必填字段 → 有限数值 → 记录数 → `RHO > 0` → 重复 `(X,Y,Z)` → 范围统计 → 训练/验证空间柱无交叉 → 生成校验报告；不修改输入文件。

### 4.3 验证点预测表

至少包含 `point_id`、`x,y,z`、`rho_true`、`rho_pred`（NoData 为 null）、`is_nodata`、`error`、`abs_error`、`relative_error`、`depth_band`、`column_id`（格式如 `X-160_Y360`）、`model_id`。

规则：

- SuperMap 导出中的 `Attribute=-9999` 代表 NoData，只能在导入适配层识别；内部统一使用 null 加 `is_nodata=true`。
- 指标只能在 `is_nodata=false` 的公共有效点上计算。
- 当前五个模型的公共有效点为 1,481，公共 NoData 为 241，覆盖率约 86.0%。

### 4.4 SuperMap 原始预测导出契约

SuperMap 导出的验证点预测 CSV 必须包含三个必填字段：

| 字段 | 类型 | 规则 |
|---|---|---|
| `SmUserID` | 整数 | 源导出标识，按原样保留 |
| `Attribute` | float64 | 预测值；`-9999` 表示 NoData |
| `Geometry` | WKT 文本 | 形如 `POINT(x y)`，解析为平面坐标 |

导入规则：

1. 用 `POINT(x y)` 解析 `Geometry` 得到 X/Y；
2. 按验证表行序与验证集真值对齐，对齐后必须检查 XY 错位（`xy_mismatch_count` 必须为 0）；
3. `Attribute=-9999` 只能在导入适配层识别，转换为 `rho_pred=null` 且 `is_nodata=true`；其他值按 float64 解析；
4. 不修改原始导出文件；导入质量（行数、有效数、NoData 数、XY 错位数）逐模型登记。

### 4.5 三维规则节点交换表

外部算法与 SuperMap 之间使用：

```text
x,y,z,value,i,j,k,is_observed,is_valid,source_point_id,method,model_id
```

`method` 枚举为 `IDW/KRIGING_ORDINARY/GOCAD_DSI/PYTHON_DSI_LIKE`；同一 `i,j,k` 组合唯一，坐标与原点、间距计算结果在浮点容差内一致。普通克里金和 IDW 不得改名为 DSI；DSI 结果进入 SuperMap 时不得再次使用 IDW 或克里金改变其数值场。

## 5. 微震三张标准表

微震标准化拆为三张表（完整本地输出写入被忽略的 `outputs/microseismic_v0.2a/`，不提交 Git）：

1. `survey_lines.csv`：测线、起止测点、正式测点数、源记录数、有效数值数、几何状态、来源与置信状态。
2. `survey_points.csv`：测点、所属测线、点序、前一点、点间距、一维累计距离 `cumulative_s_m`、来源、是否进入正式集合、坐标状态。
3. `velocity_samples.csv`：每条真实源记录一行，保留原始 token、标准化值、源文件名、源行号、有效性与质量标记。

规则：

- DAT源字段`WL/2(km)`必须原样保留。微震案例已确认派生规则`depth_m = WL_half_km × 1000`（向下为正）；三维显示可另生成`z_local_m = -depth_m`（向上为正）。原字段、派生字段、单位、符号和规则版本必须同时保存，禁止覆盖原token。当前v0.2a代码尚未实现该规则，升级时必须同步schema、config、报告和测试。
- 每个 DAT 末尾的 NUL 伪行只识别为文件终止，不计入样本，并在质量报告中登记。
- 无效原始 token（如 W8 的 `1.#QNAN0`）保留原文、源文件和源行号，不改成 0、不静默删除、不自动插值覆盖、不计入有限数值统计。
- 未知或不适用的 `sequence_on_line`、`cumulative_s_m`、`x_local_m`、`y_local_m` 保持空值，不得写成 0。
- W28 只作冲突登记，不进入正式 L3、累计距离、样本、清洗集合或模型。

微震局部三维和3σ派生契约尚未由当前代码实现，但已经确认如下：

- 2,005条有限记录逐条保留`sample_id/point_id/line_id/source_file/source_line/raw_token`，并派生`x_local_m/y_local_m/depth_m/z_local_m/vx_km_s`和规则版本；
- `depth_m = wl_half_km × 1000`且向下为正，`z_local_m = -depth_m`且向上为正；
- 对深度和Vx分别计算标准分数，任一绝对值大于3的记录进入剔除表；当前固定回归口径为剔除80条（深度72、速度8）、保留1,925条；
- 剔除表必须包含`depth_zscore/vx_zscore/filter_status/filter_reason`，候选表不得覆盖2,006条源记录标准表；
- 论文3.59%只作冲突来源，程序以实际输入分母和记录数计算比例。

## 6. 无效值、NoData 与空值语义

- **无效值**：无法解析为有限数值的内容（如 `1.#QNAN0`、文本、Infinity）。保留原 token 和溯源信息，不计入有限统计。
- **NoData**：明确的无值标记。电阻率预测导出中的 `-9999` 是唯一承认的 NoData 表示，只在导入适配层转换；它不是真实电阻率，不得进入误差统计、着色或再次插值。
- **空值（null）**：表示未确认、不适用或缺失。未知坐标、未确认派生深度、不适用序号一律使用空值，禁止用 0 表达。

## 7. 坐标、Z 和单位确认规则

1. 坐标系、单位或 Z 方向没有证据时必须明确标记未知，禁止猜测。
2. 不把示意图像素直接当成绝对测量坐标。微震案例允许按照已确认的测线拓扑、Excel点间距和局部原点约定生成局部工程坐标，但必须标记`local_engineering`和规则版本。
3. 电阻率使用 `local_engineering` 局部坐标，EPSG 未确认。
4. 微震绝对坐标、EPSG和绝对方位角仍未知；独立案例使用W16为原点的局部XY、确认的深度换算和Vx进行建模，不得与其他案例空间叠加。
5. RHO物理单位在界面中显示为“电阻率（单位待来源确认）”；微震Vx单位为`km/s`。
6. 煤层瓦斯当前工作约定为西安1980、6°分带、第20带、中央经线117°，带号坐标按EPSG:2334处理；现有DEM派生表提供`SURF_Z`，样本Z按`SURF_Z-(END_DEPTH-THICKNESS/2)`生成。该规则近似竖直孔，只允许独立实验案例，不得描述成已核实钻孔轨迹或与其他案例融合。当前58条合格样本、28个位置的具体契约见[gas.md](gas.md)。

## 8. 模型任务与成果登记

- `model_id` 使用安全字符契约：`^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$`。
- 任务状态固定为 `created/running/succeeded/failed/invalidated`；工具报错、对象为空或输出不可用必须为 `failed`。
- 模型元数据至少包含 `model_id`、`property`、`property_unit`、`method`、`input_dataset_id`、`input_sha256`、`crs`、`axis`、`grid`、`parameters`、`supermap`、`status`、`generated_at`。
- SuperMap 证据等级：`declared`、`file_verified`、`dataset_verified`、`manual_evidence`（见 `docs/decisions/0002-supermap-evidence-levels.md`）。当前 `dataset_api=none`，不得声称数据集级程序化验证。
- 成果清单区分正式、验证、预览和失败/空成果；失败/空结果只作证据登记。
- 数据契约发生坐标系/单位/Z 方向、字段含义、NoData 规则、记录集合、训练/验证划分或交换表必填字段变化时提升版本，受影响模型进入 `invalidated` 审核。

## 9. 质量指标定义

所有模型比较必须使用同一公共有效点集合（`is_nodata=false` 的交集），并同时报告 `n_total`、`n_valid` 和 `n_nodata`。当前公共有效点为 1,481、公共 NoData 为 241。

| 指标 | 定义/公式 | 比较方向 |
|---|---|---|
| MAE | `mean(abs(pred-truth))` | 越低越好 |
| RMSE | `sqrt(mean((pred-truth)^2))` | 越低越好 |
| R² | `1 - SSE/SST` | 越高越好；分组样本小时谨慎解释 |
| Median AE | 绝对误差中位数 | 越低越好 |
| Mean ARE | `mean(abs(pred-truth)/truth)` | 越低越好 |
| Median ARE | `median(abs(pred-truth)/truth)`，绝对相对误差中位数 | 越低越好 |
| log10 RMSE | 正值 truth/pred 的 log10 空间 RMSE | 越低越好 |
| Bias | `mean(pred-truth)` | 越接近 0 越好 |
| P90 AE | 绝对误差第 90 百分位 | 越低越好 |
| Coverage | 有效预测点数 / 全部验证点数 | 越高越好 |

复算结果必须与 `插值精度对比_总体指标.csv` 在配置容差（`metric_tolerance`）内一致。

## 10. 版本、追溯和禁止事项

追溯要求：

- 任一模型可反查输入文件、参数、软件版本、验证文件和问题清单。
- 每条微震源记录可反查原始 DAT 文件和源行号；所有派生值保留来源、方法、版本和包含标记。
- 审计日志记录命令、操作者、UTC 时间、输入哈希、参数、状态、输出和错误原文；敏感参数键脱敏。

禁止事项：

- 不修改、移动、重命名或覆盖 `../超图杯资料` 中的原始文件。
- 不用派生数据覆盖标准化源数据。
- 不把 `-9999` 当作真实电阻率参与统计、着色或插值。
- 不把相对测线坐标描述为真实绝对地理坐标。
- 不把瓦斯DEM候选高程、竖直孔近似或体元生成成功描述成已核实地质三维成果。
- 不将失败任务、空数据集或未验证推断登记为正式成果。
- 不把按钮点击或文件生成视为任务成功。

## 11. 通用浏览器上传契约（目标设计）

该契约属于[产品蓝图](../product-blueprint.md)，当前代码尚未实现。

- 首批文件类型为CSV和XLSX；XLSX必须显式选择工作表，不能默认合并多个工作表。
- 二维数据映射为`x/y/value`，三维数据映射为`x/y/z/value`；原字段名和映射关系必须保留。
- 每个数据集必须声明`property_name`、`property_unit`、`coordinate_type`、`xy_unit`、`z_semantics`和`z_positive_direction`；未知单位允许登记为`unknown`，但界面必须提示。
- 坐标类型至少区分`absolute_crs`和`local_engineering`。绝对坐标要求CRS标识；局部坐标要求原点、轴方向和单位说明。
- 上传校验至少包括：文件哈希、行数、数值可解析性、有限值、空值、特殊token、重复坐标、范围、二维/三维字段完整性和坐标声明。
- 上传文件保持只读；规范化结果生成新的版本化数据集，禁止覆盖源文件。

## 12. 调参实验契约（目标设计）

- 每个候选实验保存`experiment_id`、数据集ID/哈希、算法、完整参数、验证划分、随机种子、软件版本、状态、运行时间、指标、覆盖率、NoData和输出指纹。
- 第一阶段算法为IDW和普通Kriging；第一阶段自动调参为网格搜索，同时允许单组手动参数实验。
- 二维散点使用空间网格分块验证；三维柱状数据按完整XY空间柱留出；测线数据按测点或测线区段留出。不得默认逐行随机拆分造成空间泄漏。
- 所有候选模型在同一公共有效验证集合上比较，并同时报告精度、覆盖率和运行时间。
- 系统推荐必须包含可读理由；用户可以选择非综合第一名作为正式模型，但必须记录选择理由。
- 插值成功、成果导出成功、iServer发布成功和浏览器加载成功是四个独立状态，后一步失败不能篡改前一步证据。
