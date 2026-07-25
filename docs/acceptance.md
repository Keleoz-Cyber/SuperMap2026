# Acceptance Notes

适用对象：当前代码基线（v0.1.0 电阻率基线 + 微震 v0.2a 审计底座 + v0.3.1 iServer 纵向闭环 + v0.4 通用建模平台 + v0.5 微震第二案例建模闭环，后者在 `feat/v0.5-microseismic-second-case` 分支）。

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
npm --prefix web run test:e2e:live   # 需先设置独立 GEOMODELING_DATA_DIR
geomodeling run-all -o outputs/release_verify
geomodeling microseismic run-audit --config config/microseismic.yaml -o outputs/microseismic_verify
geomodeling microseismic derive --source-dir <DAT目录> -o outputs/microseismic_v05_verify   # 需真实 22 DAT
geomodeling microseismic import-case --source-dir <DAT目录> --data-dir var/geomodeling       # 需真实 22 DAT
geomodeling verify-supermap -o outputs/release_verify
```

当前基线（Task 14 后实测，本分支）：后端全量 `564 passed`（便携 537 / `local_data 27` 分层），前端 vitest `66 passed`，Playwright mock 冒烟 `3 passed`，Live E2E `2 passed`。测试数量只允许因真实新增测试而增加，任何减少或失败都必须调查。

v0.4 通用建模验收（不依赖 iServer）：

1. 便携端到端：`tests/test_platform_end_to_end.py` 一次跑通 创建案例 → 上传 3D 夹具 → 映射 → 质量门禁 → IDW + 普通克里金有限搜索 → 公共有效指标 → 正式选择 → Z/X/Y 切片 → ZIP 导出 → 运行时重启后全部资源仍可解析。
2. 浏览器双层验证：Mock API 冒烟（`npm --prefix web run test:e2e`，页面契约与导航恢复）+ Live E2E（`test:e2e:live`，真实 FastAPI + 隔离 SQLite + 真实 Worker，独立 `GEOMODELING_DATA_DIR` 与端口 5201，结束不留监听）。
3. 导航验收：所有主页面与加载失败页都有可见文字的「返回首页」；成果页可「返回实验」；返回首页不取消在途任务。
4. 演示数据验收：`demo/platform_demo_3d.csv` 是唯一权威样例，SHA-256 固定为 `deb9c25f…2bb3`；下载端点内容与哈希一致且不泄露本机路径。
5. 预检验收：`geomodeling demo-check` 区分 `passed/warning/blocked`；阻断项（前端未构建、演示数据哈希不符、数据目录不可写、SQLite 失败、端口被未知占用）退出码 1；iServer/S3M/凭据缺失仅警告，退出码 0。
6. 真实浏览器验收：启动单进程 uvicorn 后按 [v0.4 运行说明](v0.4-generic-modeling-loop.md) §1 操作，截图证据存 `docs/evidence/v0.4/`；答辩执行手册见 [v0.4.1 运行手册](v0.4.1-demo-runbook.md)。

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
