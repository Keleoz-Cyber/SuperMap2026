# v0.5 微震第二案例发布候选验证证据

> 验证日期：2026-07-25。分支 `feat/v0.5-microseismic-second-case`，基线 merge `78aa80b`（v0.4.1）+ 文档提交 `9401eee`。
> 本文分三层记录：便携 CI 证据、本机私有数据回归、真实浏览器彩排。所有数字为当场实测，非预测或照抄。

## 1. 便携 CI 证据（无私有数据）

| 命令 | 退出码 | 实测结果 |
|---|---:|---|
| `python -m pip install -e ".[api,test]"` | 0 | geomodeling-platform 0.5.0 |
| `python -m pytest -q` | 0 | **574 passed**（113s） |
| `python -m pytest -q -m "not local_data"` | 0 | **546 passed**, 28 deselected |
| `npm --prefix web ci` | 0 | 198 packages |
| `npm --prefix web run test:unit` | 0 | **66 passed**（7 文件） |
| `npm --prefix web run type-check` | 0 | vue-tsc 无错误 |
| `npm --prefix web run build` | 0 | built in 6.91s |
| `npm --prefix web run test:e2e`（Mock） | 0 | **3 passed**（v0.4 流程 2 + 微震 1） |
| `npm --prefix web run test:e2e:live`（CI 同款隔离 env） | 0 | **2 passed**（v0.4.1 既有 1 + 微震 1，17.8s），结束后无 uvicorn 残留 |
| `git diff --check origin/main...HEAD` | 0 | 无空白错误 |
| `python -m pytest tests/test_v05_ci_contract.py -q` | 0 | 6 passed（三 job 契约，无第四重复 job） |

Live E2E 微震链路覆盖：创建微震案例 → 上传 22 个**运行时合成** DAT → 核验/派生黄金通过 → 质量门禁 → z_scale=1 的 3D IDW → 公共有效点 44 → 完整场 + X/Y/Z 切片 → 正式选择 → ZIP 10 条目核对（含 `domain_evidence/` 7 件）→ 返回首页。合成包计数 45/44/1/0/44/44，不冒充私有 2,006/1,925 证据；CI 不含私有原始 DAT。

## 2. 本机私有数据回归（`local_data`，相邻只读资料）

- `python -m pytest -q -m "local_data"` → **28 passed**。
- 真实 DAT：22 个 `.dat`，合计 **66,880 bytes**；处理前后 22 文件 SHA-256 逐一对比**全部不变**（原始目录只读）。
- `geomodeling microseismic derive --source-dir <真实DAT目录>`（exit 0）：
  - 分层计数 `source_records=2006 finite=2005 invalid=1 rejected_3sigma=80 accepted_modeling=1925 modeling_nodes=1911`；
  - 分线源记录 L1/L2/L3 = 823/819/364；分线候选 792/783/350；剔除原因 深度 72 / 速度 8；
  - 聚合 `conflict_group_count=13, conflict_row_count=27, collapsed_row_count=14`，组内最大极差 0.913554 km/s；
  - 黄金哈希实测与钉值逐字节一致：
    - accepted = `4f7a0886b54bb1776e9d7ca98299f8f86e67897ba19236fb151c3fc9e2ae1513`
    - rejected = `3752b2f62de4e56121b7af66c205ccf3984270d332636335e559e7e2745872b1`
- `geomodeling microseismic import-case --source-dir <真实DAT目录> --data-dir <全新目录>`（exit 0）：`golden_passed=True status=mapped`；`standardized.parquet` **1,911 行、同坐标重复 0**。
- **浏览器↔CLI parity**：FastAPI TestClient POST 22 个真实 DAT 到 `/api/cases/{case_id}/microseismic-imports`（201，mapped），浏览器侧 `standardized.parquet` SHA-256 = `9f201f2b27d0e81ba6307ef1d3b4d4ec704e72b2dcdff4e3059bd4ca7bd94ba2`，与 CLI import-case 产物**完全一致**。

## 3. 真实浏览器彩排（本机 uvicorn 单进程 + 全新 `GEOMODELING_DATA_DIR`，真实 22 DAT）

截图在 `docs/evidence/v0.5/v05-01..14*.png`（无个人路径出镜）。

1. 首页微震卡 → 创建案例 `7579f5b7` → 四步导入向导（v05-01）。
2. 上传 22 个真实 DAT，服务端核验：文件清单/逐文件 SHA-256/测点/测线/行数，源记录 2006、有限 2005（v05-02）。
3. 派生确认：2,006/2,005/1/80/1,925/1,911 分层计数；测线 823/819/364；聚合 13/27/14/0.913554；黄金九项检查全 ✓（含两个哈希）；只读自动映射 X=X_LOCAL_M/Y=Y_LOCAL_M/Z=Z_LOCAL_M/value=VX_KM_S（v05-03）。
4. 质量门禁：总行 1,911 / 有效 1,911 / 冲突 0；1 条 EXTREME_VALUES 警告（MAD 仅报告），显式确认后放行（v05-04）。
5. 调参实验室：微震预设生效，z_scale 控件与「实验参数，不是已确认地质各向异性」文案可见（v05-05）。
6. **IDW**（power=2, neighbor=16, z_scale=1，5 折，种子 20260723）：succeeded，公共有效点 **1,911**，RMSE **0.250** / MAE 0.192 / R² **0.865** / Bias −0.020 / 覆盖率 100%（v05-06）。
7. **普通 Kriging**（spherical, auto 变异函数仅训练折拟合, neighbor=24, z_scale=1）：succeeded，公共有效点 **1,911**，RMSE **0.278** / MAE 0.223 / R² **0.833** / Bias 0.061 / 覆盖率 100%（v05-07）。
8. 成果工作台完整场点云（11³ 网格，1,331/1,331 单元，三测线几何形态与值域渐变可见）；微震证据图层组：1,911 节点默认开、1,925 候选与 80 剔除默认关（v05-08）。
9. 三层叠加渲染：候选青色、剔除红色描边，开关只影响渲染集合（v05-09）。
10. X/Y/Z 正交切片：坐标标签为真实网格坐标（如 Z = −2062.019 m、Y = 157.5 m），Z 轴 −37.5…−4086.538，有效图元 121（v05-10/11/12）。
11. 正式选择：理由「公共有效点 1911 上 RMSE 0.250 低于 Kriging 0.278，覆盖率 100%」落库（v05-13）。
12. 证据 ZIP（`GET /api/exports/241a972d…/download` 实测）：**14 项** = 标准 7 件 + `domain_evidence/` 7 件；`manifest.json` 每件含 sha256/size_bytes（分层 CSV 另含 rows）；包内 `accepted_modeling_1925.csv` 与 `rejected_3sigma_80.csv` 的 SHA-256 与黄金钉值逐字节一致；`metrics.json` 含按测线/测点 `group_diagnostics`（L1 787 / L2 777 / L3 347 计数，公共掩膜口径）。
13. **50 m 正式网格**（实验自定义网格 bounds −750…960 / −995…1310 / −4086.538…−37.5，resolution 50 m）：运行 succeeded，materialize 实测 `shape=[35,47,82], cell_count=134,890 < 100 万上限`，nodata 0，值域 0.191~3.134 km/s；浏览器完整场抽稀预览 17,712 / 134,890 单元正常渲染（v05-14）。

## 4. v0.4.1 与 v0.3.1 回归

- `geomodeling demo-check`（exit 0，status=warning）：阻断 0；7 项 PASSED；3 项 WARNING 均为 iServer 离线可选检查。
- `geomodeling run-all -o outputs/release_verify_v05`（exit 0）：电阻率 17,549/15,827/1,722；五模型各 1,481 valid / 241 NoData / XY mismatch 0；`baseline_passed=True`；两个 ISO 成果 `failed_empty`（`NATIVE_ISOSURFACE_FAILED`）为既有登记契约，非新回归。
- `geomodeling verify-supermap -o outputs/release_verify_v05`（exit 0）：iServer 离线，仅文件级证据，`dataset_verified=False`；**未将任何离线项报告为已验证**。

## 5. 安全扫描

- `git status --short`：仅新增 `docs/evidence/v0.5/`（截图）与 `.gitignore` 增补 `var/demo_v05/`。
- `git diff --check origin/main...HEAD`：通过。
- `git ls-files` 危险模式（`.dat$|.udbx$|platform.sqlite3$|^var/|^outputs/|^artifacts/|.env$`）：**零命中**；彩排运行时目录已加入 .gitignore，真实派生 CSV 不入库。
- 路径/凭据扫描：文档与代码不含本机绝对路径与凭据；iServer 凭据仍只走环境变量。

## 6. 已知边界（发布门如实登记）

- iServer 全程离线：SuperMap 数据集级验证不可用（契约允许降级），微震建模全流程不依赖 iServer；通用成果发布仍 `manual_required`。
- 微震 XY 为局部工程坐标（非 EPSG），不与电阻率/瓦斯叠加；`WL/2` 深度换算与 3σ 规则为项目确认口径；`z_scale` 为实验参数，不代表已确认地质各向异性。
- 任意斜切、DSI、预测/预警、瓦斯案例、iServer 自动发布：明确不做。
- Live E2E 需要调用方注入隔离 `GEOMODELING_DATA_DIR` 与 `GEOMODELING_MICROSEISMIC_CONFIG`（CI 已内置；裸跑会按设计拒绝并提示）。
