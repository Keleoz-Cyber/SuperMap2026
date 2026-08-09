# v0.8.0 电阻率散点预置 + DSI-like 真实 SDK live 门证据

本目录收录 `web/e2e-live/resistivity-scattered-live.spec.ts` 的真实运行证据
（SuperMap3D 原生 NetCDF 体渲染：Volume / X / Y / Z Slice / Contour 五模式 +
普通刷新场景 + 旧 legacy/S3M 入口 410 退役确认）。

## 生成方式

- 唯一生成入口：在干净实现提交上运行 live 规格（`npm --prefix web run
  test:e2e:live -- e2e-live/resistivity-scattered-live.spec.ts`），每次运行写入
  `<run-id>/` 子目录（`run-YYYYMMDDTHHMMSSZ-<uuid8>`）。
- 前置条件：
  - 电阻率源为项目内 `example_data/地下电阻率节点_标准化.csv`（v0.8.0 第三批
    起字节冻结内置源，`X,Y,Z,RHO`、17,549 行；证据中只登记其 SHA-256，
    无需任何外部私有源或环境变量）；
  - `GEOMODELING_DATA_DIR` 指向全新隔离运行库（规格启动前经
    `python -m geomodeling.preset_cli seed-resistivity --data-dir <isolated>`
    建立只读预置链，`--source` 缺省为内置源）；
  - `web/dist` 含真实 SuperMap3D SDK 与前端产物（真实 GPU，
    `--use-angle=gl`）。
- 本规格无私有源跳过门；仅真实运行时产生证据目录。

## 目录约定

每个 `<run-id>/` 子目录包含：

- `environment.json`：运行身份封套（run_id / git_commit / sdk_sha256 /
  浏览器与 GPU 渲染器 / 视口）与 seed 命令形态；
- `identity.json`：seed 链身份（源/基线 SHA-256、官方成果 ID）、DSI-like 用户
  候选资产身份（asset/grid/NetCDF 哈希）、410 退役逐项确认；
- `network.json` / `console.json`：全部 API 请求与控制台/页面错误记录
  （失败门：任何非白名单 4xx/5xx、协议 ERROR、pageerror 均为零）；
- `pixel-stats.json`：五模式中央区域像素判据实测（非背景数/覆盖率/颜色标准差/
  最大连通区占比）、静帧噪声阈值、剖面两索引像素差、统计不变性；
- `timings.json`：run/资产 POST/rendered/普通刷新 rendered 与逐命令耗时；
- `slice-exports.json`：剖面分析 ZIP 导出 manifest（四文件、CSV 逐格坐标、
  统计一致、PNG 字节 SHA 回链）；
- `rho-*.png`：体积/剖面/等值面证据截图（`volume`、`slice-<axis>-q<idx>`、
  `contour` 等）。

## 入库纪律

- 证据只能从干净实现提交上的真实运行产生；结果由主会话运行后单独提交，
  本骨架不含任何运行结果。
- 提交前必须扫描并确认零命中：本机绝对路径（盘符/UNC）、凭据、`.runtime`、
  私有 CSV 内容、SDK 二进制；Playwright trace/失败截图只作 CI 工件，不入库。
