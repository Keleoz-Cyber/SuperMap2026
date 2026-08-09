# v0.8.0 第二批统计与空间分析中心 live 门证据

本目录收录 `web/e2e-live/analysis-center-live.spec.ts` 的真实运行证据
（真实微震 + 电阻率双预置数据的统计与空间分析中心：analysis-summary API
合同门 + 1440×900 桌面视觉门 + 390×844 移动视口门 + 空间分箱 / 剖面轴 /
模型对比交互门；真实 ECharts 渲染，不用 mock）。

## 生成方式

- 唯一生成入口：在干净实现提交上运行 live 规格（`npm --prefix web run
  test:e2e:live -- e2e-live/analysis-center-live.spec.ts`），每次运行写入
  `<run-id>/` 子目录（`run-YYYYMMDDTHHMMSSZ-<uuid8>`）。
- 前置条件：
  - 电阻率源为项目内 `example_data/地下电阻率节点_标准化.csv`（v0.8.0 第三批
    起字节冻结内置源，`X,Y,Z,RHO`、17,549 行；证据中只登记其 SHA-256，
    无需任何外部私有源或环境变量）；
  - `GEOMODELING_DATA_DIR` 指向全新隔离运行库（规格 beforeAll 依次执行
    `python -m geomodeling.preset_cli seed-microseismic --data-dir <isolated>`
    与 `python -m geomodeling.preset_cli seed-resistivity --data-dir <isolated>`
    建立只读预置链，`--source` 缺省为内置源）；
  - `web/dist` 含真实前端产物与 SuperMap3D SDK（真实 GPU，`--use-angle=gl`）。
- 本规格无私有源跳过门；仅真实运行时产生证据目录。

## 目录约定

每个 `<run-id>/` 子目录包含：

- `environment.json`：运行身份封套（run_id / git_commit / sdk_sha256 /
  浏览器与 GPU 渲染器 / 桌面与移动视口 / DPR）与双 seed 命令形态；
- `identity.json`：两个案例的 seed 链身份（dataset_version_id、官方成果
  result_id、source_sha256）与分析身份（analysis_profile、
  calculation_version、数据版本、行数）；
- `api-summary.json`：两个 analysis-summary 的合同裁剪（profile、质量与
  有限统计、逐模块 status/method/source_fields/thresholds、模型对比候选、
  provenance）——断言通过的载荷形态，不含 32×32 分箱明细；
- `network.json` / `console.json`：全部 API 请求与控制台/页面错误记录
  （失败门：任何非白名单 4xx/5xx、pageerror、console error 均为零）；
- `pixel-stats.json`：各图表中央 50% 区域像素判据实测（canvas 绘制抽样、
  非背景数、颜色标准差；黑屏/近单色/空图判失败）与判据阈值；
- `interactions.json`：交互证据——XY 分箱选择的成果页查询参数
  （axis/x_range/y_range/dataset）、剖面轴 X→Y→Z 截图差分（超
  max(200, noise*3+50) 噪声阈值）、模型对比候选点击；
- `timings.json`：摘要 API 与页面就绪耗时；
- `rho-*.png` / `micro-*.png`：证据截图（桌面分析页、空间异常图、成果页
  联动、剖面 X/Y/Z 三轴、分布图、390×844 移动全页）。

## 入库纪律

- 证据只能从干净实现提交上的真实运行产生；结果由主会话运行后单独提交，
  本骨架不含任何运行结果。入库 run 的 `git_commit` 必须是代码提交的祖先
  （或代码提交本身），由 `tests/test_v070_ci_contract.py` 合同强制。
- 提交前必须扫描并确认零命中：本机绝对路径（盘符/UNC）、凭据、`.runtime`、
  私有 CSV 内容、SDK 二进制；Playwright trace/失败截图只作 CI 工件，不入库。
