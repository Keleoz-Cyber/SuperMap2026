# 地下电阻率数据与成果

> 数据契约通用规则见 [contracts.md](contracts.md)。本文件记录电阻率案例当前的散点预置、DSI-like、机器学习预测和 NetCDF 体渲染事实，以及旧 S3M/legacy 链的历史边界。

## 1. 当前结论（0.9.0）

- 电阻率案例已从只读 `builtin_legacy` 入口迁移为统一的 `builtin_preset` 散点预置案例，案例 ID 保持 `resistivity`（既有深链可解析）；不提供 CSV 上传步骤，数据版本只读。
- 官方成果为普通克里金基线（winner `exponential / neighbor=24`，RMSE=6.454476），经 `Experiment → Run → CandidateResult → materialize → FormalSelection` 链登记，用户实验不得改写官方正式选择。
- 算法选项为 IDW、普通 Kriging、**DSI-like 离散平滑插值**、随机森林空间回归和克里金残差随机森林；DSI-like 是工程近似方法，**不等同于 GOCAD DSI**（免责声明见 §5）。机器学习必须通过样本/空间组适用性门，并与相同折分指纹的普通克里金比较。
- 体渲染走统一候选 NetCDF 链（§6）；旧 S3M/legacy 渲染入口已类型化退役（§7）。
- 官方验证合同为生产 `spatial_kfold` 5 折、seed=20260723；遗留训练/验证分区（15,827/1,722）只作源溯源事实记录（§3）。

## 2. 散点源合同

电阻率源内置在仓库 `example_data/地下电阻率节点_标准化.csv`（v0.8.0 第三批起；此前为项目外部私有文件）。**字节级 SHA-256 冻结合同**（`example_data/*.csv` 关闭 EOL 归一化，任意平台检出字节一致）；运行时只登记其 SHA-256 指纹，CI 使用脱敏夹具，不依赖本机数据。

| 项目 | 合同 |
|---|---|
| 字段 | `X,Y,Z,RHO` |
| 行数 | 17,549 |
| 源 SHA-256 | `04c5914d…c167`（完整值见 `config/presets/resistivity-official-baseline.json`） |
| 坐标 | 局部工程坐标，未声明 EPSG；Z 向下为负 |
| 坐标唯一性 | `(X,Y,Z)` 无重复 |
| 数值 | 坐标和值全部有限 |
| RHO 范围 | 约 1.032113 至 149.984 Ω·m（单位已确认，界面如实标注） |
| 空间结构 | 293 个 `(X,Y)` 空间柱，每柱 42 至 60 个节点 |

预置 seed（唯一生产入口 `python -m geomodeling.preset_cli seed-resistivity`）校验源身份、字段、行数、有限性、坐标唯一性与空间柱结构后，建立只读预置数据版本；预置源不能被用户上传、覆盖或正式选择改写。数据版本 profile 写入字段映射（X/Y/Z/RHO、值名 RHO、`local_linear` 坐标、单位 Ω·m）、行数与分区溯源（§3），并参与数据版本指纹。

## 3. 训练/验证分区溯源事实

标准化源的遗留训练/验证分区作为**源溯源事实**写入数据版本 profile：

| 项目 | 数值 |
|---|---:|
| 训练行数 | 15,827 |
| 验证行数 | 1,722 |
| 训练空间柱 | 264 |
| 验证空间柱 | 29 |
| 空间柱重叠 | 0 |

profile 只登记计数与验证柱身份指纹（64 位 SHA-256），坐标清单绝不落库。注意区分：**官方候选验证合同**为生产 `spatial_kfold` 5 折、seed=20260723（逐折只用训练点重建场，验证点绝不进入硬约束集合）；上表遗留分区仅作来源溯源，不是官方指标的计算口径。

## 4. 官方基线身份

官方基线冻结于 `config/presets/resistivity-official-baseline.json`（schema `v0.8.0-resistivity-official-baseline/v1`，预置版本 `resistivity-rho-17549/v1`），选择不可复算或指纹不符即 fail-closed（`PRESET_BASELINE_INVALID`），绝不覆盖既有成果。

| 项目 | 值 |
|---|---|
| winner 算法 | `ordinary_kriging` |
| winner 参数 | `variogram_model=exponential`、`neighbor_count=24` |
| RMSE | 6.454476 |
| MAE | 3.251899 |
| R² | 0.923093 |
| Bias | -0.095026 |
| 覆盖率 | 1.0 |
| 公共有效集 | 17,547 |
| 网格 | 7×23×42 = 6,762 单元，20 m 分辨率 |
| 网格边界 | X [-160, -40]，Y [220, 660]，Z [-833.0047143, -19.5999]（局部工程坐标） |
| 候选报告指纹 | `00aebfd7…ab71`（完整值见基线文件） |

选择规则：`rmse → mae → r2 → 规范化参数序`，官方 winner 限定在 ordinary_kriging 候选中选出（次优 `spherical/neighbor=24`，RMSE=6.483775）。最小官方候选矩阵（1 IDW + 4 普通克里金 + 2 DSI-like）全量保留于候选报告供追溯；IDW（RMSE=6.360991）与 DSI-like（6 邻接 RMSE=6.467770，26 邻接 RMSE=6.506906）候选**不参与官方选择**。

## 5. DSI-like 合同与免责声明

产品名固定为“DSI-like 离散平滑插值”。它是基于 IDW 初始场和离散邻域平滑的 Python **工程近似**方法：规则网格趋势层由 SciPy LGMRES 求解稀疏图拉普拉斯系统，原始观测坐标再叠加 IDW 残差精确化层，因而硬约束针对原始散点而不是吸附后的最近网格节点；仅在观测点三维包围范围内更新，范围外保持 NoData。最大节点变化低于收敛容差才算成功，耗尽外迭代预算仍未收敛则类型化失败。

- **免责声明**：DSI-like 不宣称等同 GOCAD DSI，也不宣称给出唯一真实地质结构；页面选项旁如实展示该说明。
- 参数：`init_power`（默认 2.0）、`neighbor_connectivity`（默认 6）、`smoothing_strength`（默认 0.5，用于把离散方程残差换算为节点变化收敛门）、`max_iterations`（默认 25，稀疏求解外迭代预算）、`convergence_tolerance` 固定 1e-4、`hard_constraints` 固定 true；算法无随机种子，相同输入必须产生相同预测与网格字节。
- 失败语义：非有限值、重复坐标、公共有效集为空、未过收敛/覆盖率门一律类型化失败，候选 `failed` 绝不物化；不可用时绝不回退为“看起来成功”的 IDW 或点云渲染。

## 6. NetCDF 身份链

所有候选（IDW / 普通 Kriging / DSI-like，含官方成果）统一走 `CandidateResult → materialize → NetCDF → RenderAsset` 链：

- `POST /api/results/{id}/render-assets/netcdf` 是唯一创建入口（首个成功 201、幂等 200、creating 409）；所有 GET 纯查询。
- NetCDF manifest 必须包含源 SHA、数据版本指纹、算法、参数、网格规格和 provenance；manifest/grid/NetCDF 哈希双向核验，损坏资产原子隔离（`RENDER_ASSET_CORRUPT`）。
- 坐标合同为 `wgs84_display_anchor_v1` 显示锚点（`display_anchor_only`），页面必须如实展示“非真实地理配准”。
- 成果页、Volume、X/Y/Z Slice、Contour、剖面分析与导出全部复用统一组件，无电阻率专用渲染器，无回退渲染器。

## 7. 旧 S3M/legacy 退役（v0.8.0）

- 旧 legacy 渲染端点一律返回 **410 `LEGACY_RESISTIVITY_RETIRED`** 类型化响应，绝不返回旧 S3M 数值：`GET /api/cases/resistivity/render-capability`、`POST|GET /api/cases/resistivity/render-assets/netcdf`、`POST /api/cases/resistivity/render-sources/import`、`GET /api/cases/resistivity/voxel-cells`。
- 旧 legacy 电阻率卡与旧三维工作台页已从产品路径移除（首页、工作台、路由、前端客户端函数）；未 seed 的运行库显示预置描述卡（能力全 false）。
- 旧 S3M 文件、旧数据库记录与旧证据**只读保留**，由单独的清理任务处置；旧资产不得作为新候选或默认 featured result。

## 8. 历史事实（v0.1 基线，旧链已退役）

以下事实记录旧 S3M/legacy 链的历史验证状态，仅作证据档案保留；当前产品路径以 §1–§7 为准。

- v0.1.0 发布基线曾验证：标准化登记、契约校验、训练/验证隔离、五模型预测导入、公共有效点指标复算、SuperMap 成果登记与报告导出可复现；`RHO_KRIG_FINAL_20M_40` 是当时唯一正式 SuperMap 成果，`dataset_verified=False`。
- 旧五模型在 1,722 条验证记录上的公共有效点为 1,481、公共 NoData 241、XY mismatch 0；`-9999` 为 NoData 标记，只在导入适配层识别，不进入误差统计、着色或再次插值。
- 旧 S3M 证据边界：完整体元、水平薄切片和 `RHO >= 77` 高值过滤只有人工证据；垂直切片未验证；原生等值面失败并留下空数据集（失败推断：高值区接触体元边界且 X 向仅 7 个单元——推断，不是已确认的 SuperMap 内部规则）。
- 历史遗留限制保持如实声明：EPSG 未确认；GOCAD `.sg`/Voxet/VTU 与论文所述 DSI 输出资料缺失，无法验证真实 GOCAD 到 SuperMap 的端到端转换——这正是 v0.8.0 采用“DSI-like 工程近似 + 显式免责声明”的原因。RHO 物理单位旧链时代未确认，v0.8.0 第三批起经用户权威确认为 **Ω·m**（§2）。

## 9. 复现命令

```powershell
python -m pip install -e ".[api,test]"
# 预置 seed（默认读项目内 example_data/ 内置源；基线默认读 config/presets/resistivity-official-baseline.json）
python -m geomodeling.preset_cli seed-resistivity
python -m pytest -q -m "not local_data"
```

预期：seed 输出只含逻辑身份（案例/数据版本/实验/运行/官方成果 ID 与指纹），首页电阻率卡为“标准化散点 · 17,549 个节点”的 `builtin_preset` 预置卡，便携测试不依赖外部源（脱敏夹具承载合同；`--source` 仅在测试/审计时显式覆盖默认内置源）。
