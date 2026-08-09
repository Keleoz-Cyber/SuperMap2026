# v0.8.0 第三批瓦斯预置 live 门证据

本目录收录 `web/e2e-live/gas-preset-live.spec.ts` 的真实运行证据（瓦斯含量
预置官方成果的真实 SDK 渲染与缓存验收：API 身份链 → 首页瓦斯卡 → 统一
工作台 → 成果页 rendered → Volume/X/Y/Z Slice/Contour 五模式像素门 +
光照/渐变透明度/色带/透明度/值域过滤交互门 + 包围盒线框贴体门 + 普通
刷新 + fresh/刷新/服务重启刷新/warm-cache 升级四缓存场景；真实
SuperMap3D SDK + 真实 GPU，不用 mock）。

## 生成方式

- 唯一生成入口：在干净实现提交上运行 live 规格（`npm --prefix web run
  test:e2e:live -- e2e-live/gas-preset-live.spec.ts`），每次运行写入
  `<run-id>/` 子目录（`run-YYYYMMDDTHHMMSSZ-<uuid8>`）。
- 前置条件：
  - `GEOMODELING_DATA_DIR` 指向全新隔离运行库（规格 beforeAll 执行
    `python -m geomodeling.preset_cli seed-gas --data-dir <isolated>`
    建立只读预置链；`--source` 缺省为项目内
    `example_data/瓦斯含量_合格样品.csv` 内置源，**无需任何外部私有源
    或额外环境变量**，因此本门没有也不需要 `GEOMODELING_RHO_SOURCE`
    式跳过门）；
  - `web/dist` 含真实前端产物与 SuperMap3D SDK（真实 GPU，
    `--use-angle=gl`）；
  - 用例 2 的四缓存场景自管 uvicorn：默认端口 5278，可用
    `GEOMODELING_WARM_CACHE_PORT` 覆盖（本机 Windows Hyper-V 保留段
    5141–5240 内 bind 直接 errno 13）。
- `GEOMODELING_DATA_DIR` 缺失时 beforeAll 直接失败（不静默跳过），
  不产生任何证据目录。

## 目录约定

每个 `<run-id>/` 子目录包含：

- `environment.json`：运行身份封套（run_id / git_commit / sdk_sha256 /
  浏览器与 GPU 渲染器 / 视口 / DPR）与 seed 命令形态、warm-cache 端口；
- `identity.json`：seed 链身份（dataset_version_id、官方成果 result_id、
  source_sha256、baseline_sha256）与渲染身份（asset_id、grid/netCDF
  SHA-256、manifest 形状与变量名、值域、协议 RENDER_STATE 身份、SDK
  版本）；
- `scenarios.json`：四缓存场景各自的 Volume/Z 剖面像素判据实测与
  warm-cache 升级场景的版本化 app.js 资源条目（`?v=` 内容版本断言）；
- `network.json` / `console.json`：全部 API 请求与控制台/页面错误记录
  （失败门：任何非白名单 4xx/5xx、pageerror、console error、协议 ERROR
  均为零）；
- `pixel-stats.json`：中央 50% 区域像素判据实测（静帧噪声基线、非背景
  数、覆盖率、颜色标准差、最大连通区占比、逐命令像素差分、剖面两索引
  差分、统计不变性）与判据阈值——黑屏/Logo-only/背景单色/旧 app.js/
  协议超时/空资产标 ready 一律判失败；
- `timings.json`：rendered/刷新/逐命令耗时；
- `slice-exports.json`：剖面分析包 ZIP 导出 manifest（四文件、CSV 真实
  轴坐标、统计一致、哈希一致、无路径/凭据泄漏）；
- `gas-*.png` / `<场景>-page.png` / `<场景>-iframe.png`：证据截图（体积、
  各轴剖面、等值面、四缓存场景整页与 iframe 裁剪）。

## 入库纪律

- 证据只能从干净实现提交上的真实运行产生；结果由主会话运行后单独提交，
  本骨架不含任何运行结果。入库 run 的 `git_commit` 必须是代码提交的祖先
  （或代码提交本身），由 `tests/test_v070_ci_contract.py` 合同强制。
- 提交前必须扫描并确认零命中：本机绝对路径（盘符/UNC）、凭据、`.runtime`、
  源 CSV 内容、SDK 二进制；Playwright trace/失败截图只作 CI 工件，不入库。
