# Acceptance Notes

适用对象：当前代码基线（v0.1.0 电阻率基线 + 微震 v0.2a 审计底座 + v0.3.1 iServer 纵向闭环 + v0.4 通用建模平台 + v0.5 微震第二案例建模闭环（已随 v0.5.0 发布）+ v0.6 专业建模增强（`feat/v0.6-professional-modeling` 分支）+ v0.6.1 NetCDF 原生体渲染（`feat/v0.6.1-netcdf-native-rendering` 分支））。

## 验收命令

```powershell
python -m pip install -e ".[api,test]"
python -m pytest -q
python -m pytest -q -m "not local_data"
python -m pytest -q -m local_data
npm --prefix web ci
npm --prefix web run test:unit
npm --prefix web run type-check
npm --prefix web run build
npm --prefix web run test:e2e
geomodeling demo-check --json
npm --prefix web run test:e2e:live   # 需先设置独立 GEOMODELING_DATA_DIR 与 GEOMODELING_MICROSEISMIC_CONFIG
geomodeling run-all -o outputs/release_verify
geomodeling microseismic run-audit --config config/microseismic.yaml -o outputs/microseismic_verify
geomodeling microseismic derive --source-dir <DAT目录> -o outputs/microseismic_v05_verify   # 需真实 22 DAT
geomodeling microseismic import-case --source-dir <DAT目录> --data-dir var/geomodeling       # 需真实 22 DAT
geomodeling professional diagnose --data-dir var/geomodeling --dataset-id <数据版本id>
geomodeling professional confirm --data-dir var/geomodeling --diagnosis-id <诊断id> --note "确认说明"
geomodeling professional inspect-result --data-dir var/geomodeling --result-id <候选成果id>
geomodeling professional extract-anomalies --data-dir var/geomodeling --result-id <候选成果id> --config-json '{"direction":"high","threshold":1.0}'
geomodeling professional compare --data-dir var/geomodeling --first <候选A> --second <候选B>
geomodeling verify-supermap -o outputs/release_verify
```

当前基线（Task 23 后实测，本分支）：后端全量 `1153 passed`（便携 1124 / `local_data 29` 分层），前端 vitest `97 passed`，Playwright mock 冒烟 `4 passed`，Live E2E `3 passed`。测试数量只允许因真实新增测试而增加，任何减少或失败都必须调查。

v0.6.1 当前基线（Task 14 后实测，`feat/v0.6.1-netcdf-native-rendering` 分支）：后端便携 `1274 passed`，前端 vitest `157 passed`，Mock E2E `5 passed`，Live E2E 真实 SDK 32^3/64^3 各 `1 passed` + 既有 `3 passed`。

v0.6.1 NetCDF 原生体渲染验收（不依赖 iServer；live SDK 门为本地发布门）：

1. 聚焦后端测试：

```powershell
python -m pytest tests/test_render_coordinates.py tests/test_schema_v6_migration.py tests/test_render_asset_repository.py tests/test_render_source_resolution.py tests/test_legacy_render_sources.py tests/test_netcdf_volume.py tests/test_render_asset_publication.py tests/test_rendering_api.py tests/test_v061_rendering_contract.py tests/test_v061_docs.py -q
```

2. 版本与文档合同：`python -m pytest tests/test_v061_docs.py tests/test_version_consistency.py -q`（全部版本面 = 0.6.1、运行手册必需命令、状态文档措辞防护）。
3. 渲染防护契约：`tests/test_v061_rendering_contract.py` 保证旧全局 Cesium、`Field3D`/`RhoScene3D`、自研光线步进 POC 与 three/cesium 依赖不复活。
4. 前端：`npm --prefix web run test:unit`、`type-check`、`build`、`test:e2e` 按上表基线通过。
5. live 真实 SDK 门（本地发布门，隔离 `GEOMODELING_DATA_DIR`，需先按 [v0.6.1 运行手册](v0.6.1-netcdf-native-rendering-runbook.md) §2/§8 完成 SDK 预检与前端构建）：

```powershell
$env:GEOMODELING_DATA_DIR = "$PWD/var/geomodeling-e2e-live"
npm --prefix web run test:e2e:live -- e2e-live/supermap-volume-frame-live.spec.ts e2e-live/supermap-native-volume-live.spec.ts
Remove-Item Env:GEOMODELING_DATA_DIR
```

   判定：32^3 与 64^3 各自 rendered 30s 门内（参考机实测 <2s）、64^3 交互 5s 门内像素稳定（实测 <0.5s）、filter/opacity/Slice/Contour 像素响应超静帧噪声、证据元数据来自同一运行。
6. 操作语义验收：POST 是唯一资产创建路径（首个成功 201 / ready 幂等 200 / creating 409 / failed-interrupted 须 `retry_failed=true` 显式重试）；所有 GET 纯查询；manifest/grid/NetCDF 哈希双向核验，损坏资产原子隔离不自动删除；重启后 `creating` 原子转 `interrupted`。
7. legacy 边界验收：未登记权威网格时内置电阻率返回 `LEGACY_RENDER_SOURCE_NOT_REGISTERED` 且页面只显示 auxiliary points 辅助层；登记只走 `python -m geomodeling.render_cli import-csv`。
8. 历史回归：v0.6 专业建模、v0.5 微震黄金哈希、v0.4.1 固定演示路径、v0.3.1 电阻率只读回归全部保持既有口径。

v0.4 通用建模验收（不依赖 iServer）：

1. 便携端到端：`tests/test_platform_end_to_end.py` 一次跑通 创建案例 → 上传 3D 夹具 → 映射 → 质量门禁 → IDW + 普通克里金有限搜索 → 公共有效指标 → 正式选择 → Z/X/Y 切片 → ZIP 导出 → 运行时重启后全部资源仍可解析。
2. 浏览器双层验证：Mock API 冒烟（`npm --prefix web run test:e2e`，页面契约与导航恢复）+ Live E2E（`test:e2e:live`，真实 FastAPI + 隔离 SQLite + 真实 Worker，独立 `GEOMODELING_DATA_DIR` 与端口 5201，结束不留监听）。
3. 导航验收：所有主页面与加载失败页都有可见文字的「返回首页」；成果页可「返回实验」；返回首页不取消在途任务。
4. 演示数据验收：`demo/platform_demo_3d.csv` 是唯一权威样例，SHA-256 固定为 `deb9c25f…2bb3`；下载端点内容与哈希一致且不泄露本机路径。
5. 预检验收：`geomodeling demo-check` 区分 `passed/warning/blocked`；阻断项（前端未构建、演示数据哈希不符、数据目录不可写、SQLite 失败、端口被未知占用）退出码 1；iServer/S3M/凭据缺失仅警告，退出码 0。
6. 真实浏览器验收：启动单进程 uvicorn 后按 [v0.4 运行说明](v0.4-generic-modeling-loop.md) §1 操作，截图证据存 `docs/evidence/v0.4/`；答辩执行手册见 [v0.4.1 运行手册](v0.4.1-demo-runbook.md)。

v0.6 专业建模验收（不依赖 iServer；便携测试不依赖真实数据）：

1. 便携测试：`tests/test_pair_sampling.py`、`tests/test_directional_variogram.py`、`tests/test_anisotropy_*.py`、`tests/test_neighborhood_selection.py`、`tests/test_kriging_variance.py`、`tests/test_empirical_uncertainty.py`、`tests/test_anomaly_*.py`、`tests/test_professional_*.py`、`tests/test_analysis_jobs.py` 等全量通过（数学单元、合成结构、平台合同、迁移与状态机、导出 fail-closed、legacy 只读兼容）。
2. 版本与文档合同：`python -m pytest tests/test_version_consistency.py tests/test_demo_docs.py tests/test_v06_docs.py -q`（全部版本源一致、v0.5.0 已发布事实、运行手册两层不确定性与禁止表述扫描）。
3. CLI 真实链路：任一已通过质量门禁的数据集依次执行 `geomodeling professional diagnose`（输出 `status=succeeded` 与采样披露）→ `confirm`（不可变快照指纹）→ 运行专业实验并物化 → `inspect-result`（能力/参数来源/manifest 摘要）→ `extract-anomalies`（component 计数）→ `compare`（compatible 结论与比较指纹）；JSON 输出不含绝对路径。
4. 前端与端到端：vitest、Mock E2E（v0.6 专业建模流程 mock 链路）、Live E2E（v0.6 真实链路：上传合成 CSV → 质量门禁 → 诊断 → 确认 → 专业 Kriging 实验 → 折分/不确定性/异常/比较 → 导出 `professional/` 证据）按上表基线通过。
5. 浏览器真实流程：按 [v0.6 运行手册](v0.6-professional-modeling-loop.md) 执行 诊断 → 人工确认 → 专业实验 → 专业分析台 → 异常保存 → 双候选比较 → 导出（ZIP 含 `professional/` 目录，manifest 哈希一致）。
6. 历史回归：v0.5 微震黄金哈希与 1,925/1,911 口径不变、v0.4.1 固定演示路径通过、v0.3.1 电阻率只读回归通过；iServer 离线只按现有契约警告。

v0.5 微震第二案例验收（不依赖 iServer，需真实 22 DAT 完成真实回归；便携测试不依赖真实数据）：

1. 便携测试：`tests/test_microseismic_*.py` 全量通过（派生坐标/深度符号/单位、3σ 精确统计、canonical 字节稳定、黄金门禁 fail-closed、聚合溯源、导入补偿、API 路由）。
2. 真实数据回归：`python -m pytest -q -m local_data` 中微震用例对真实 22 DAT 复算 2,006/2,005/80/1,925/1,911 全链条与两张黄金表 SHA-256。
3. CLI 真实回归：`geomodeling microseismic derive --source-dir <DAT目录> -o <输出>` 输出 `golden_passed=True`、`downstream_gates` 全部解除、六层派生工件齐备；`import-case` 创建案例与数据集且 `validation_passed=True`。
4. 前端与端到端：vitest、Mock E2E（微震导入向导与成果工作台三层诊断图层契约）、Live E2E 按上表基线通过。
5. 浏览器真实流程：按 [v0.5 运行手册](v0.5-microseismic-loop.md) 执行 导入 DAT → 派生确认 → 质量门禁 → 调参 → 成果 → 导出（ZIP 含 `domain_evidence/` 七文件）。

v0.3 浏览器闭环验收（需本机 iServer 已启动且 `WorkSpace.smwu` 已发布，见 [v0.3 运行说明](v0.3-iserver-loop.md)）：

```powershell
python scripts/fetch_iclient3d.py
cd web; npm install; npm run build; npm run type-check; cd ..
python -m uvicorn geomodeling.api.app:app --host 127.0.0.1 --port 8000
# GET /api/health → {"status":"ok","version":"0.3.x"}
# GET /api/cases/resistivity/publish-status → evidence_chain 中
#   model_succeeded/artifact_exported/iserver_published/service_metadata_verified=True，
#   浏览器打开 http://127.0.0.1:8000/ 完成一次场景渲染后 browser_loaded 亦转 True
```

## 电阻率验收口径

- 标准化/训练/验证行数：17,549 / 15,827 / 1,722。
- 训练空间柱 264、验证空间柱 29，重叠 0。
- 五份预测导出各 1,722 行，1,481 valid、241 NoData、XY mismatch 0。
- 复算指标与 `插值精度对比_总体指标.csv` 在配置容差内一致（`baseline_passed=True`）。
- SuperMap 配置成果 3 个，正式成果 1 个（`RHO_KRIG_FINAL_20M_40`）；本机存在 `../Project/expore1.udbx` 时 `udbx_exists=True`、`udbx_file_verified=True`。

## 微震验收口径

- 22 个 DAT（66,880 字节）、22 个 NUL 终止伪行。
- 2,006 条源记录（L1/L2/L3 = 823/819/364）、2,005 条有限数值（822/819/364）、1 条无效数值（W8 `1.#QNAN0`）。
- 三张标准表：3 / 23 / 2,006 行；W28 不在正式集合且序号与累计距离为空。
- 15 项契约检查通过，源文件 SHA-256 处理前后不变，无伪造 XY/Z，`validation_passed=True`。
- v0.5 派生口径：一次全局 3σ（样本标准差 `ddof=1`）剔除 80 条（深度 72、速度 8）、保留 1,925 条候选（792/783/350）；accepted/rejected 两张 canonical CSV（UTF-8 BOM + CRLF）SHA-256 与黄金表一致；13 个冲突组 / 27 条组内记录 / 坍缩 14 条，聚合输出 1,911 个唯一建模节点；`golden_passed=True` 时 `geometry/cleaning/interpolation` 三个 downstream gate 全部解除，否则导入阻断。
- 退出码语义：只有契约检查或黄金门禁失败（`validation_passed=False`）时 CLI 返回 1，且仍尽量输出诊断报告；`validation_passed=True` 时返回 0。

## 证据边界（必须保持显式）

- v0.5 起微震 downstream gates 由派生流程真实输出驱动：审计契约与黄金门禁全部通过才解除 `geometry/cleaning/interpolation_blocked`；任一失败保持阻断并使导入失败。2026-07-20 确认的局部坐标、深度、单位和有效值规则已随 v0.5 完成 schema、config、geometry、报告和回归测试升级；详见[data/microseismic.md](data/microseismic.md)。
- `dataset_verified=False`：没有受支持的 SuperMap 数据集 API 适配器，只声明文件级验证。
- 完整体元和水平切片为人工 iDesktopX 证据；垂直切片 `unverified`；原生等值面 `failed`，空数据集不进入正式成果。
- `RHO >= 77` 仅为演示阈值；RHO 物理单位和 EPSG 未确认。
- 微震`z_scale`只是距离计算实验参数（`0 < z_scale ≤ 20`），由空间验证比较，不代表已确认的地质各向异性。

## 仓库外派生与人工验收证据

- 微震：2,005条有限记录经3σ规则剔除80条（深度72、速度8），保留1,925条（L1/L2/L3 = 792/783/350）；候选表SHA-256为`4F7A0886B54BB1776E9D7CA98299F8F86E67897BA19236FB151C3FC9E2AE1513`，已在iDesktopX人工复现。**v0.5 起该对人工表作为黄金回归来源**：仓库代码从原始 DAT 重新生成并逐字节锁定两张表哈希，门禁不过即阻断。
- 瓦斯：外部派生表含58条合格三维候选样本、28个位置，SHA-256为`FAB47D99926554255995BFB2D5FA299A389C14934D13B3F2D3BDB6E16EF5FC8F`；点图层能够显示，但`GAS_CH4_IDW_R1000_N12_P1`体元加入三维场景会触发iDesktopX原生崩溃。
- 瓦斯证据只证明文件和人工试验存在，不证明当前仓库能够生成、验证、发布或在浏览器显示这些成果。

## 未实现（当前 main）

- 微震绝对地理配准与跨案例空间叠加（需共同控制点证据）；iServer 自动发布（`manual_required` 保持）。
- 煤层瓦斯体元稳定显示、程序化数据契约和正式模型验收。
- DSI-like 插值内核与 GOCAD 工程转换。
- iDesktopX 控件自动化、账户体系、云部署。

下一阶段浏览器建模平台的目标验收标准见[product-blueprint.md](product-blueprint.md#11-mvp验收标准)。该蓝图是未来验收目标，不得与本页当前代码基线混报。
