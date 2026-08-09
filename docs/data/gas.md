# 瓦斯含量数据与内置预置案例

> 更新时间：2026-08-09（v0.8.0 第三批）。本文记录当前仓库采用的瓦斯数据合同、坐标/单位口径、官方基线、分析边界与历史外部证据。当前实现状态以 [当前状态](../status/current-status.md) 为准。

## 1. 内置数据合同（当前唯一权威源）

- 文件：`example_data/瓦斯含量_合格样品.csv`，仓库内置、字节级冻结；`.gitattributes` 对 `example_data/*.csv` 关闭文本规范化，任意平台检出字节一致。
- SHA-256（CRLF + UTF-8 BOM 原始字节）：`f7d6f03d280dd0d6db45e5e6a09b47747cc4831669e4163a63b791f913a4f09d`。
- 表头与行数：`X,Y,Z,CH4_content`，58 行数据，58 个唯一 XYZ，全部数值有限。
- 采样结构：28 个 XY 采样位置（整柱多层）；Z ∈ [121.0375, 175.656]；CH4_content ∈ [0.05, 34.3]。
- 坐标：局部线性米制（`coordinate_kind=local_linear`、`coordinate_unit=m`），未声明 EPSG，不做地理配准，不得与其他案例空间叠加。
- 属性单位：`ml/g`（已确认），不做静默换算；profile、工作台 DTO、分析摘要、NetCDF manifest、图表轴与导出溯源中的单位必须一致。
- 合同校验 fail-closed：存在性、SHA-256、行数、表头、唯一 XYZ、数值有限性任一不符即拒绝 seed，不返回伪成果。

## 2. 预置案例与官方基线

- 案例身份：`builtin_preset` 只读预置（`config/presets/gas.json`，preset_version `gas-ch4-58/v1`，案例 ID `gas`）；seed 唯一生产入口 `python -m geomodeling.preset_cli seed-gas`，默认源即内置 example_data，无需任何外部私有源；经统一 `Case → DatasetVersion → Experiment → Run → CandidateResult → materialize → FormalSelection` 链登记官方成果（确定性身份、幂等复用、并发唯一、失败补偿不留半成品）；源指纹或基线不符即拒绝，绝不覆盖既有成果。
- 官方基线 `config/presets/gas-official-baseline.json`（2026-08-09 真实内置源复算冻结）：13 个候选（IDW 9 + 普通克里金 4），spatial_kfold 5 折（seed=20260723，28 根整 XY 柱分组，逐折验证行数 [12, 11, 11, 13, 11]，公共有效集 58）；按 rmse→mae→r2→规范化参数选择，winner 为 `ordinary_kriging` spherical / neighbor_count=24——RMSE=8.298439、MAE=6.552100、R²=−0.109659、Bias=−0.068618。
- 解释性口径：58 点稀疏采样下 R² 为负。插值与网格成果一律为稀疏采样下的解释性估计，交叉验证误差必须随成果明示，不得描述为精确煤层几何模型或规范判定。
- 规则网格：151×333×12 @[20,20,5] m（603,396 节点，bounds 来自瓦斯数据），值全有限、零 NoData；官方成果经 NetCDF 原生体渲染资产链物化，资产身份可追溯到 candidate。
- DSI-like：默认参数条件评估四道门全过（交叉验证公共有效 46/58、coverage 0.793103、指标有限，官方网格物化全有限、包围盒外恒 NoData）；其指标口径为 46 点有效子集，且 winner ∈ {idw, ordinary_kriging} 合同已锁——DSI-like 仅作对照候选，绝不参与官方选择。

## 3. 差异化分析（gas_content profile）

- `gas_content` profile 正式启用：`value_name=CH4_content` + 3D 判定，单位 `ml/g`。
- 模块：含量分布/分位数与有效样本质量、Z 向分层统计、XY 高/低含量区域、空间梯度与采样覆盖、候选模型有限指标对比。
- 高/低含量区域阈值一律为非空单元均值 p25/p75 的探索性分位口径并明示来源；结论只使用「高值区域/低值区域/样本稀疏/交叉验证误差」等可计算表述，不输出「瓦斯危险/安全」等安全规范结论。

## 4. 历史外部证据（v0.8.0 第三批之前，仅来源追溯）

以下事实属于仓库外人工派生与 iDesktopX 实验，与第 1 节的内置合同是两套来源，不得混用：

- 外部派生表 `煤层瓦斯三维插值点_合格58.csv`：58 条、28 个位置，X 范围 20,292,238.02—20,322,167.88，Y 范围 3,768,497.16—3,834,887.31，Z 范围 −1,756.56—−1,210.375 m；SHA-256 `FAB47D99926554255995BFB2D5FA299A389C14934D13B3F2D3BDB6E16EF5FC8F`。
- 当时工作坐标约定：西安1980、6° 高斯—克吕格第 20 带、中央经线 117°E、带号东坐标按 EPSG:2334；Z 规则 `Z = SURF_Z − (END_DEPTH − THICKNESS/2)`（垂直钻孔近似，DEM 派生地表高程）。该约定未经代码验证，且**不适用于**当前内置合同（内置源为局部线性米制、正 Z）。
- 原始标准化记录层面：原始来源为 `2025-刘昌佳-煤层瓦斯分析成果表（表4-13）.doc`，标准化总记录 76 条、29 组坐标，其中 58 条登记为「合格」；漏气、漏水和不合格记录不参与插值。`BH001`—`BH029` 为标准化位置 ID，非原始孔号。
- iDesktopX 2026 实验：三维点 `GAS_CH4_POINTS_3D_58` 可正常显示；IDW 体元 `GAS_CH4_IDW_R1000_N12_P1` 加入三维场景触发原生崩溃（崩溃栈 `Layer3DNative.jni_SetSliceCoordinate` / `Layer3DSettingVolume.setSliceCoordinate`）。该失败不能反推插值数值错误，也不构成对当前内置案例 NetCDF 浏览器渲染链的约束。

## 5. 边界汇总

- 不做真实 CRS 配准、不做跨案例空间叠加、不做多源融合表述；
- 不输出安全/危险规范结论，不把分位统计阈值描述成权威限值；
- 不接入 AI 预测、iServer 机器学习 REST 或 S3M 自动发布；
- v0.9 分析中心视觉重构与结论看板不在本批范围；
- 任何瓦斯正式成果必须同时记录源 SHA-256、字段/单位、坐标口径、插值参数、折分指纹与渲染证据。
