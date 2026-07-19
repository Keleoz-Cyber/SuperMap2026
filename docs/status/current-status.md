# 当前开发状态

> 状态入口。数据事实细节见 [../data/resistivity.md](../data/resistivity.md)、[../data/microseismic.md](../data/microseismic.md) 和 [../data/contracts.md](../data/contracts.md)。

## 已发布基线

- **v0.1.0**（标签 + GitHub Release，merge commit `b160405`）：电阻率三维属性模拟 MVP。
- 已验证：17,549 / 15,827 / 1,722 行；空间柱重叠 0；五模型各 1,481 valid / 241 NoData / XY mismatch 0；`baseline_passed=True`；`RHO_KRIG_FINAL_20M_40` 为唯一正式 SuperMap 成果；`dataset_verified=False`。
- 开发阶段历史：资料与环境核验 → 架构与工程初始化 → 数据与指标闭环 → 应用界面与 SuperMap 成果管理 → 验收与交付 → v0.1 验收加固与发布，均已完成。

## 已合并但未发布

- **微震 v0.2a 数据审计底座**（PR #2，merge commit `f623b66`）：已合并到 `main`，**尚未创建新标签或 Release**。
- 交付物：22 个 DAT 清单与 SHA-256、2,006 条源记录标准化（2,005 有限 + 1 无效）、三张标准表、一维累计距离（L1=1,150 / L2=2,305 / L3=1,455 m）、15 项契约检查、11 项标准问题、CLI `geomodeling microseismic` 命令组、便携 + 本地回归测试。
- 修复口径：manifest 使用稳定相对路径；W28 的 `sequence_on_line` 与 `cumulative_s_m` 为空值；审计摘要显式区分 validation blockers 与 downstream gates。

## 当前正式成果

| 成果 | 状态 | 证据 |
|---|---|---|
| `RHO_KRIG_FINAL_20M_40` 体元 | 正式 | 配置登记 + 文件级验证 + 人工证据 |
| 水平薄切片、RHO>=77 过滤 | 可用 | 仅人工证据 |
| 微震三张标准表与审计报告 | 正式（审计层） | 本地可复现 CLI + 测试 |
| `RHO_ISO_77_K40` / `RHO_ISO_HIGH_P95_K40` | 失败/空 | 仅失败证据登记 |

## 当前阻断

微震 downstream gates（审计通过不解除）：

- `geometry_blocked=True`：无可信绝对坐标、原点、方位角、CRS，深度/Z 换算未确认。
- `cleaning_blocked=True`：80 条异常值清单/规则、3.59% vs 3.99% 比例口径、线性插值 vs 邻近 5 点 IDW 方法冲突未解决。
- `interpolation_blocked=True`：以上几何问题 + `WL/2(km)` 含义未确认。

其他显式未决：RHO 物理单位未确认；EPSG 未确认；论文计数 `823/818/364=2,005` 与文件事实冲突保留。

## 下一阶段顺序

1. **微震 v0.2b 数据确认**（下一阶段，不是三维插值开发）：按 [../microseismic_v0.2b_data_confirmation.md](../microseismic_v0.2b_data_confirmation.md) 逐项登记证据，确认 `WL/2(km)` 含义与 Z 换算、测线几何与 CRS、清洗规则、计数冲突；实施计划见 [../superpowers/plans/2026-07-19-microseismic-v0.2b-data-confirmation.md](../superpowers/plans/2026-07-19-microseismic-v0.2b-data-confirmation.md)。
2. 数据确认完成后才评估：正式清洗、二维/三维几何重建、微震插值。
3. 瓦斯条件确认（CRS、轴顺序、孔口高程、深度基准）后做属性统计扩展。
4. 更晚：DSI-like、多源融合和业务评价。

## 明确未实现

- 微震二维/三维坐标、正式清洗、空间插值、SuperMap 三维点导入。
- 煤层瓦斯可信三维叠加；GOCAD SGrid/Voxet/VTU 转换。
- DSI-like 插值内核；不得把 IDW 或普通克里金改名为 DSI。
- SuperMap 垂直切片（未验证）、原生等值面（失败）、数据集级 API 验证（`dataset_api=none`）。
- iDesktopX 自动点击、Web 前端、账户权限、云部署、iServer 发布。
- 自动成矿概率、储量和自动地质结论。
