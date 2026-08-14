# config 配置目录

运行与合同配置的唯一来源，全部随仓库版本化。

| 文件/目录 | 作用 |
|---|---|
| `default.yaml` | 遗留验收链配置（v0.1-v0.3）：数据路径（指向仓库外的只读研究资料目录）、期望行数（17,549/15,827/1,722、公共有效 1,481）、nodata `-9999`、指标容差、五模型定义、SuperMap 成果登记段与视图配置。仅 `validate-data`/`compute-metrics` 等遗留 CLI 使用；平台主链不依赖它。 |
| `microseismic.yaml` | 微震领域合同：3 条测线 22 个 DAT 清单（L1: W1-W9、L2: W12-W20、L3: W24-W27）、点间距、22 点局部坐标、派生规则（depth=WL/2×1000、z=-depth、3σ ddof=1、精确 XYZ 算术平均）、期望计数（2,006 源记录/2,005 有效/1 QNAN/剔除 80/黄金 1,925/节点 1,911）与黄金表 SHA-256。 |
| `presets/` | 三案例声明（`gas.json`/`microseismic.json`/`resistivity.json`：语义字段、单位、坐标种类、推荐搜索网格、默认网格、演示文案、边界声明、内置源冻结哈希）+ 三个官方基线（`*-official-baseline.json`：冻结候选矩阵与 winner 指纹，seed 时 fail-closed 校验）。 |
| `s3m_cache_manifest.json` | 历史 S3M 体元缓存 manifest（严格兼容证据读取用）。 |

## 规则

- 修改 `presets/*.json` 中的任何哈希或期望值都必须伴随对应数据文件的真实变更与测试更新，否则 seed 与合同测试失败。
- 期望计数与黄金哈希是微震派生链的验收锚，不允许"先改配置让测试通过"。
- 本目录不含任何凭据；密钥只允许环境变量或产品内凭据存储。
