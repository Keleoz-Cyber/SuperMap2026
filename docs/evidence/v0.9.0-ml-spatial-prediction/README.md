# v0.9.0 机器学习空间预测真实证据

本目录收录 `web/e2e-live/ml-spatial-prediction-live.spec.ts` 的真实运行证据。
规格使用内置电阻率与微震源，通过生产 seed CLI 和公开 HTTP 完成实验创建、
空间交叉验证、候选物化、多字段 NetCDF 和真实 SuperMap3D 渲染，不直接插库，
不复制预建 ML 资产。

## 本轮结论

正式证据轮为 `run-20260813T064945Z-f8d30015`，测试代码提交
`11b02acb9674f3f80b6d746649a714ee524cf6a7`，SuperMap3D SDK SHA-256 为
`d69dadab01fc452a79f1fa88a46aced3cf29885df7bf4febbd6f24ce5b578120`。

- 电阻率随机森林：17,549 公共有效点，RMSE 5.546855、MAE 2.464957、
  R2 0.943222、Bias -0.079344；本轮同折普通克里金 RMSE 6.468625。
- 微震随机森林：1,911 公共有效点，RMSE 0.250364、MAE 0.202911、
  R2 0.864338、Bias 0.047494。微震只有 22 个独立 XY 空间组，因此该结果
  仍按产品合同标记为实验性对照，不据此宣称稳定泛化。
- 电阻率克里金残差校正：17,549 公共有效点，RMSE 7.326515、MAE
  3.841685、R2 0.900943、Bias -0.196885；相对同折普通克里金 RMSE 变差
  13.26%，系统如实显示「未优于普通克里金」，不推荐该候选。

以上比较要求验证合同、折分指纹与公共有效集完全一致。开发验收曾发现预置
普通克里金省略默认 `holdout_fraction`、ML 请求显式带出同一默认值时被错误
判为不可比；`52ad1b5` 改为按 `SpatialValidationSpec` 规范化后比较并补回归
测试，没有放宽折分指纹或公共有效集门。

## 视觉与缓存门

残差候选的 prediction、model_dispersion、kriging_baseline、
residual_correction 四个字段均生成独立 RenderAsset/NetCDF 身份，并通过：

- 真实 SuperMap3D Volume 中央内容门：非背景像素、覆盖率、颜色标准差、
  最大连通区占比；
- 每字段一个 Z 切片门：切片位于体盒内，权威切片 API 与协议状态一致；
- prediction/dispersion/baseline 使用顺序色带，correction 使用零中心冷暖
  发散色带；辅助字段不显示仅属于主预测场的异常标注；
- fresh、普通刷新、服务重启刷新、warm-cache 升级四场景均到达已渲染；
- 控制台错误、pageerror 和请求失败均为零。

`pixel-stats.json` 记录各字段实测像素指标，`identity.json` 记录模型指标、折分
与 OOF 指纹、grid/field/NetCDF/asset SHA，`cache-scenarios.json` 记录四缓存
场景，PNG 为整页与 iframe 真实截图。截图已逐张人工核对，不含加载遮罩、
黑屏、Logo-only 或重复字段冒充。

## 复跑

前置条件：`web/dist` 含通过 `scripts/install_supermap3d.py` 安装的本机
SuperMap3D SDK；`GEOMODELING_DATA_DIR` 必须指向全新隔离目录。

```powershell
$env:GEOMODELING_DATA_DIR = Join-Path $env:TEMP ("gmp-v090-ml-" + [guid]::NewGuid())
$env:GMP_CAPTURE_EVIDENCE = "1"
npm --prefix web run test:e2e:live -- --config playwright.live.config.ts ml-spatial-prediction-live.spec.ts
```

证据入库前必须扫描并确认不包含本机绝对路径、凭据、`.runtime`、SQLite、
SDK 二进制或未受控私有 CSV；失败 trace 和临时运行库不入库。
