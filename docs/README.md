# GeoModelingPlatform 文档中心

本文档目录遵循统一的分类规范与维护纪律：每份文档有明确受众与唯一事实归属，全部文档受合同测试治理。改动任何文档前请先阅读本页规范。

## 文档体系（四层结构）

| 层级 | 位置 | 性质 | 修改规则 |
|---|---|---|---|
| 权威文档 | 根 `README.md`、`CHANGELOG.md` 与本目录五份核心文档 | 当前事实的唯一记载 | 随代码与产品演进更新，改动须跑合同测试 |
| 技术决策记录 | [decisions/](decisions/) | 架构决策的过程与理由（ADR） | 只增不改；决策被推翻时新增 ADR 并标注取代关系 |
| 过程档案 | [superpowers/](superpowers/) | 实施计划与设计快照 | 历史快照，不回改内容；补充说明只允许以加注方式 |
| 验收证据 | [evidence/](evidence/) | 真实浏览器/模型/分析/技术探针证据 | 只增不改；新证据轮次建新目录 |

## 文档索引

| 文档 | 受众 | 唯一归属的事实 |
|---|---|---|
| [../README.md](../README.md) | 评委/新访客 | 项目定位、平台闭环、快速体验、能力总览、边界摘要 |
| [../CHANGELOG.md](../CHANGELOG.md) | 所有人 | 版本演进（每版本的功能与交付事实） |
| [product-guide.md](product-guide.md) | 用户/评委 | 产品功能操作、三个内置案例、AI 配置、指标解释 |
| [architecture.md](architecture.md) | 开发者 | 架构分层、模块边界、数据生命周期、算法与验证、渲染链、术语表 |
| [api-reference.md](api-reference.md) | 开发者/评测 | HTTP API 与 CLI 全参考、环境变量 |
| [operations.md](operations.md) | 维护者 | 免安装包、源码开发、打包发布、测试 CI、故障排查 |
| [contest.md](contest.md) | 团队 | 答辩演示路线、比赛提交结构、特色提炼、边界话术 |

目录级使用合同（目录即合同原则）：[../demo/README.md](../demo/README.md)、[../example_data/README.md](../example_data/README.md)、[../tests/fixtures/README.md](../tests/fixtures/README.md)、[../config/README.md](../config/README.md)、[../scripts/README.md](../scripts/README.md)、[../portable/README.md](../portable/README.md)、[../web/README.md](../web/README.md)。

## 写作与维护规范

1. **单一事实归属**：每个事实（数字、流程、合同、边界）只在一处权威记载，其他文档只链接、不复述。典型归属：版本号->`CHANGELOG.md`；案例指标->`product-guide.md`；模块与算法合同->`architecture.md`；命令用法->`api-reference.md`；发布流程->`operations.md`；演示话术->`contest.md`。禁止双份维护同一数字或同一清单。
2. **文档受测试治理**：文档结构、关键合同关键词、相对链接可达、禁本机路径由 `tests/test_demo_docs.py`、`tests/test_v06_docs.py`、`tests/test_v061_docs.py`、`tests/test_v070_docs.py` 等合同测试锁定。改文档后必须运行：

   ```powershell
   python -m pytest tests/test_demo_docs.py tests/test_v06_docs.py tests/test_v061_docs.py tests/test_v070_docs.py -q
   ```

3. **目录即合同**：凡有非显而易见约定的目录（数据冻结、夹具用途、脚本行为）必须带 README，说明内容物与使用规则。
4. **过程与权威分离**：决策、计划、证据是只增不改的过程档案；当前事实只写在权威文档。过程档案与权威文档冲突时，以权威文档为准。
5. **禁泄密红线**：所有文档禁止出现本机绝对路径（盘符）、API Key、凭据、许可证和未授权私有资料。
6. **过时即改**：发现事实性偏差（文件名、版本号、数值）必须立即修正权威文档并同步合同测试，不允许"下次一起改"。

## 保留证据索引

- [v0.7.0 单轴切片技术探针](evidence/v0.7.0-single-axis-probe/)
- [v0.8.0 电阻率 DSI-like](evidence/v0.8.0-resistivity-dsi-like/)
- [v0.8.0 瓦斯案例](evidence/v0.8.0-batch-3-gas/)
- [v0.8.0 统计分析](evidence/v0.8.0-statistics-analysis/)
- [v0.9.0 三案例与浏览器产品](evidence/v0.9.0/)
- [v0.9.0 机器学习空间预测](evidence/v0.9.0-ml-spatial-prediction/)
- [v0.9.0 成果级分析](evidence/v0.9.0-result-analysis-live/)

证据纪律：`run-*` 目录默认不入库，只有被显式纳入版本的代表性证据例外；生成与验收方式见各目录 README。
