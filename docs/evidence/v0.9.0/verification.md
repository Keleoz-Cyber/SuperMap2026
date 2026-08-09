# v0.9.0 视觉产品验收记录

> 验收对象：`feat/v0.9.0-visual-product`（基线 `origin/main` = `a7c2689`，v0.8.1）。
> 验收口径：`docs/superpowers/specs/2026-08-10-v0.9.0-visual-product-redesign-design.md` 第 17 节。
> 证据 run：`run-20260809T202443Z-6df61448`（`git_commit=028a2cf`，即最终测试代码提交；其后仅文档改动，不影响渲染链）。

## 1. 自动化测试实数（本分支 fresh 运行）

| 套件 | 结果 | 说明 |
| --- | --- | --- |
| 后端便携 | `1810 passed, 32 deselected` | `python -m pytest -q -m "not local_data"` |
| 后端 local_data | `32 skipped` | 本机无相邻只读参考数据目录（与 main 一致的环境性跳过） |
| 前端 vitest | `447 passed`（52 文件） | `npm run test:unit` |
| 前端 type-check | 通过 | `vue-tsc -b` |
| 前端 build | 通过 | Vite production |
| Mock E2E | `40 passed` | 含 v0.9 指挥舱/自定义数据全链/答辩模式/四档响应式 |
| 真实 SDK live | `4 passed` | `v090-answer-stage-live.spec.ts`，RTX 4070，Chromium |
| git diff --check | 通过 | `origin/main...HEAD` |

## 2. 真实浏览器视觉门（live run 证据）

证据目录：`run-20260809T202443Z-6df61448/`，JSON 身份与逐场景像素统计见
`v090-live-evidence.json`。

| 场景 | 判据 | 结果 |
| --- | --- | --- |
| 指挥舱·电阻率（1440×900） | 协议 rendered + 体积像素门（非背景体素>2000、中央覆盖≥0.15、色方差、连通区）+ Ω·m/gold 联动 | 通过（`home-resistivity-*.png`） |
| 指挥舱·微震速度 | 同上 + km/s/violet 联动 | 通过（`home-builtin-microseismic-vx-1911-*.png`） |
| 指挥舱·煤层瓦斯 | 同上 + ml/g/jade 联动 | 通过（`home-gas-*.png`） |
| 图表→三维联动（瓦斯成果页） | 趋势剖面点击 → 正交切片坐标标签出现 + 帧前后像素差异真实存在 | 通过（`linkage-gas-page.png`，`pixel_diff=true`） |
| 答辩模式 | 六章节导航 + 电阻率章节真实渲染像素门 + Escape 退出 | 通过（`presentation-resistivity-page.png`） |
| 手机 390×844 | 零横向溢出 + 主动作可见 + 瓦斯切换渲染像素门 | 通过（`phone-gas-page.png`） |

控制台错误 0；网络失败仅 iframe/SDK 首次加载的重复中止请求（重试后成功，像素门为证）。

## 3. 验收口径对照（设计 §17）

- §17.1 首页与导航：首屏无需滚动即可见平台定位、当前案例、三维成果、关键发现、自定义数据入口（截图证据）；三案例切换变量/单位/色彩/三维/发现/图表整体一致更新（live 门）；官方案例无上传步骤（mock 门）；每页唯一主动作（合同测试）。
- §17.2 数据接入：同屏预览/映射/质量/空间检查（v090-custom-data-flow mock 门）；未知 CRS 声明局部线性，无伪 EPSG（组件测试）；阻断/警告分级（质量摘要合同测试）。
- §17.3 调参与模型选择：参数影响摘要、流水线「阶段估计」、2–4 候选兼容比较与不兼容 fail-closed（vitest + mock 门）。
- §17.4 成果与分析：五模式渲染能力保持（既有 live 门不回归）；图表↔三维双向联动（live 像素 diff）；结论卡带 source/confidence/limitations（findings 合同测试）；环图仅部分-整体口径（dock 合同测试）。
- §17.5 视觉与动效：四档视口零横向溢出；reduced-motion token；无长期闪烁。
- §17.6 真实浏览器门：见第 2 节。

## 4. 已知边界（本版本不回避）

- 三案例均为局部线性米制坐标 + `display_anchor_only` 显示锚点，非真实地理配准。
- 瓦斯 58 点稀疏采样，官方基线 R² 为负：解释性估计，页面不输出安全/危险规范结论。
- 趋势图点击驱动切片只在体渲染成果页可用；XY 区域过滤当前渲染器不支持，显示类型化能力通知。
- 答辩模式章节不自动播放；镜头书签仅元数据，场景未就绪不移镜。
- 首页三维资产未创建时显示显式创建入口（POST 只接受显式变异，合同不变）。
- iServer 不参与 v0.9.0 浏览器链路；发布登记保持 `manual_required`。
