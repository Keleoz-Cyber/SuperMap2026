# 当前开发状态

> 状态入口。数据事实细节见 [../data/resistivity.md](../data/resistivity.md)、[../data/microseismic.md](../data/microseismic.md) 和 [../data/contracts.md](../data/contracts.md)。

目标产品和分期见 [../product-blueprint.md](../product-blueprint.md)。本文严格区分“当前代码已实现”与“已经确认、等待实现的设计”。

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

## 已确认、等待实现

- 产品形态：上传数据后完成校验、插值调参、空间验证和展示的独立浏览器建模平台。
- 架构：Python/FastAPI建模核心 + SuperMap iServer发布 + SuperMap浏览器展示。
- 插值调参：手动参数调整 + 网格搜索；通过空间隔离验证比较候选模型。
- 案例关系：电阻率、微震、瓦斯及后续数据是独立案例，共用平台但不跨坐标叠加。
- 微震局部坐标：W16为原点，X沿L3指向W24，Y沿L2指向W20；W5为L1/L2交点且坐标为`(0,220)`；各测点距离按Excel计算。
- 微震深度与单位：`depth_m = WL_half_km × 1000`，Vx为km/s；只排除W8的`1.#QNAN0`，其余2,005条有限值进入候选建模集合；W28不建模。

这些决策尚未进入当前`config/microseismic.yaml`、geometry代码和测试，因此当前CLI仍会输出旧的downstream gates；不能只修改状态输出来冒充功能完成。

## 仍然未知但不阻塞平台主干

- 电阻率RHO物理单位和绝对EPSG；电阻率只按局部三维案例处理。
- 微震绝对方位角、绝对控制点和EPSG；微震只按局部三维案例处理。
- 瓦斯西安80的准确带号/EPSG、正式属性字段和同孔多深度聚合规则；实现瓦斯案例前确认。
- 老师后续属性数据的字段、维度和单位；通过通用字段映射接入。
- SuperMap垂直切片、原生等值面和数据集级API验证；作为增强项逐项验证。
- DSI-like真实后端；不作为MVP前置条件。

## 下一阶段顺序

1. 验证本机iServer 2026启动、许可、REST管理端、可用服务和发布链路；不得仅凭目录存在判断可用。
2. 把微震已确认规则写入schema/config/geometry并完成真实数据回归，生成2,005条局部三维建模样本。
3. 建立FastAPI通用数据集与实验任务接口，支持CSV/XLSX字段映射。
4. 实现二维/三维IDW、普通Kriging、手动调参、网格搜索和空间验证。
5. 开发浏览器上传、调参、模型对比和成果场景，优先打通电阻率和微震。
6. 打通iServer发布与SuperMap Web展示；随后接入瓦斯和老师新增数据。

## 明确未实现

- 微震局部二维/三维坐标代码、空间插值、SuperMap三维点导入。
- 煤层瓦斯可信三维叠加；GOCAD SGrid/Voxet/VTU 转换。
- DSI-like 插值内核；不得把 IDW 或普通克里金改名为 DSI。
- SuperMap 垂直切片（未验证）、原生等值面（失败）、数据集级 API 验证（`dataset_api=none`）。
- iDesktopX自动点击、Web前端、FastAPI服务、通用上传、调参执行和iServer发布。
- 自动成矿概率、储量和自动地质结论。
