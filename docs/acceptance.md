# 验收标准

本文定义当前 0.9.0 源码的发布门。历史测试数量不作为固定合同；是否通过以当前命令退出码、失败数和证据内容为准。

## 1. 便携质量门

在 **PowerShell** 中依次运行：

```powershell
python -m pytest -q -m "not local_data"
npm --prefix web run test:unit
npm --prefix web run type-check
npm --prefix web run build
npm --prefix web run test:e2e
git diff --check
```

要求全部退出码为 0。GitHub Actions 的 `portable-tests` 和 `browser-smoke` 必须成功。

`local_data` 测试只在相邻只读研究资料存在时运行：

```powershell
python -m pytest -q -m local_data
```

运行前后应核对原始资料 SHA-256 不变。

## 2. Live E2E

```powershell
npm --prefix web run test:e2e:live -- e2e-live/platform-live.spec.ts
```

要求使用隔离 `GEOMODELING_DATA_DIR`，真实启动 FastAPI、SQLite 和 Worker，结束后无残留进程。CI 的 `browser-live` 必须成功。

需要 SuperMap SDK/GPU 的规格属于本机发布门，不得在缺少运行时的 CI 中用 Mock 替代：

```powershell
npm --prefix web run test:e2e:live -- e2e-live/v090-answer-stage-live.spec.ts
npm --prefix web run test:e2e:live -- e2e-live/result-analysis-live.spec.ts
```

## 3. 数据接入

- CSV/Excel 文件可上传并预览；不支持格式返回结构化错误。
- 坐标、属性、单位、NoData 和维度映射明确。
- 数值字段不能因导入推断为文本后继续建模。
- 无效值、重复点、空间柱和有效样本数有报告。
- 原始文件哈希登记；公开响应不暴露本机路径。
- 数据质量未通过时，不允许创建正式建模实验。

## 4. 插值与预测

- IDW、普通克里金和 DSI-like 使用统一实验/任务/候选生命周期。
- 普通克里金自动拟合只能使用训练折，不能读取验证行。
- 手动变异函数参数必须满足 nugget、sill、range 的合同。
- 空间折分保持同一 XY 柱/空间组不跨训练与验证。
- 指标只在公共有效集上比较。
- ML 适用性门必须按有效样本和独立 XY 组阻断不适用案例。
- 克里金残差随机森林只能使用内部折外残差训练。
- 模型离散度必须标注为树模型分歧参考，不表示概率意义上的可信范围。

### v0.6 专业建模 CLI 回归

```powershell
geomodeling professional diagnose --help
geomodeling professional confirm --help
geomodeling professional inspect-result --help
geomodeling professional extract-anomalies --help
geomodeling professional compare --help
```

## 5. 候选比较与正式成果

- 候选检查可以展示任意成果；严格排名只接受折分和公共有效集兼容的成果。
- 不兼容时显示具体差异和行动建议，不返回伪排名。
- OOF、折分和成果文件读取前重新验证大小和 SHA-256。
- 正式选择要求 Run 和 CandidateResult 均为 `succeeded`。
- 排名、选择理由和参数快照持久化。
- 若机器学习未优于普通克里金，界面必须如实显示。

## 6. 三维、切片与分析

### v0.6.1 原生体渲染发布门

```powershell
python -m pytest tests/test_v061_docs.py -q
npm --prefix web run test:e2e:live -- e2e-live/supermap-native-volume-live.spec.ts
```

- RenderAsset 身份必须包含成果 ID 和规则网格哈希。
- NetCDF 维度、坐标、变量、单位、值域和 NoData 与登记一致。
- Volume、Contour、X/Y/Z Slice 使用同一成果。
- 权威切片响应包含 axis、index、coordinate、relativePosition 和统计。
- `valid + nodata = total`；统计口径与导出一致。
- 图表选择能够定位同一三维成果或切片。
- 渲染失败显示诊断，不回退为可能误导的点云或线框。

## 7. 三个内置案例

### 电阻率

- 17,549 行内置源哈希与冻结合同一致。
- RHO 对外单位统一为 Ω·m。
- IDW、普通克里金、DSI-like 和两种机器学习可建立候选。
- DSI-like 明确标注“不等同 GOCAD DSI”。

### 微震

- 22 DAT 只读；唯一非法 token `1.#QNAN0` 不改 0。
- 一次全局 3σ：2,005 个有限样本剔除 80，得到 1,925 个黄金候选。
- 完全相同局部坐标聚合为 1,911 个唯一节点，溯源不丢失。
- 只有 22 个独立 XY 组，因此随机森林必须标记“实验性”。

### 瓦斯

- 58 个合格样品、28 个 XY 位置和字段单位与冻结合同一致。
- 负 R² 不能隐藏或改写。
- 机器学习适用性门必须拒绝该数据集。

## 8. 导出与发布

- 导出 ZIP 中每个工件都有 SHA-256 清单。
- 微震领域证据和专业证据哈希不符时返回 409，且不登记可下载导出。
- 导出失败时临时目录被清理，清理异常不覆盖原业务异常。
- 通用成果发布保持 `manual_required`，除非获得实时 iServer 对象级验证。
- 浏览器加载证据只接受身份精确匹配、成功且有效数量大于 0 的服务器接收回执。

## 9. 演示验收

- `python -m geomodeling.cli demo-check` 无阻断项。
- 首页、案例工作台、调参、比较、成果和回收站均有返回路径。
- 1920×1080 和 1440×900 无关键内容截断；390×844 无横向溢出。
- iServer 在线时服务与场景身份匹配；离线时明确显示降级，不影响通用建模。
- 控制台、页面和网络不得出现未解释错误。
- 截图、视频与提交源码来自同一版本。

## 10. 文档与仓库卫生

- README、当前状态、产品蓝图、架构、数据和 SuperMap 文档相互一致。
- Markdown 相对链接全部存在。
- 不跟踪过程计划、Agent 提示词、交接副本和重复历史截图。
- 不提交密钥、`.env`、本机绝对路径、运行数据库、日志、缓存或私有原始资料。
- 测试代码保留在源码仓库；部署运行包按[比赛提交说明](contest-submission.md)排除测试和开发文件。
