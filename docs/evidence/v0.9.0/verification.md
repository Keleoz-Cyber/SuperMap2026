# v0.9.0 视觉产品验收记录

> 验收对象：`feat/v0.9.0-visual-product`（基线 `origin/main` = `a7c2689`，v0.8.1）。
> 验收口径：`docs/superpowers/specs/2026-08-10-v0.9.0-visual-product-redesign-design.md` 第 17 节。
> 最终证据 run：`run-20260810T044808Z-45a4500c`，证据 JSON `git_commit=7a66f17`，
> 即最终代码 HEAD（合并前审查修复提交链末端），证据与文档单独提交。

## 1. 自动化测试实数（最终 HEAD fresh 运行）

| 套件 | 结果 | 说明 |
| --- | --- | --- |
| 后端便携 | `1810 passed, 32 deselected` | `python -m pytest -q -m "not local_data"` |
| 后端 local_data | `32 skipped` | 本机无相邻只读参考数据目录（与 main 一致的环境性跳过） |
| 前端 vitest | `449 passed`（53 文件） | `npm run test:unit` |
| 前端 type-check | 通过 | `vue-tsc -b` |
| 前端 build | 通过 | Vite production |
| Mock E2E | `40 passed` | 含 v0.9 指挥舱/自定义数据全链/答辩全屏/四档响应式 |
| 真实 SDK live | `4 passed` | `v090-answer-stage-live.spec.ts`，RTX 4070，Chromium，fail-closed 网络/控制台断言 |
| git diff --check | 通过 | `origin/main...HEAD` |

## 2. 真实浏览器视觉门（live run 证据）

证据目录：`run-20260810T044808Z-45a4500c/`。

| 场景 | 判据 | 结果 |
| --- | --- | --- |
| 指挥舱·电阻率（1440×900） | 协议 rendered + 体积像素门 + Ω·m/gold 联动 | 通过（`home-resistivity-*.png`） |
| 指挥舱·微震速度 | 同上 + km/s/violet 联动 | 通过（`home-builtin-microseismic-vx-1911-*.png`） |
| 指挥舱·煤层瓦斯 | 同上 + ml/g/jade 联动 | 通过（`home-gas-*.png`） |
| 图表→三维联动（瓦斯成果页） | 趋势点击 → 切片坐标标签 + 帧前后像素差异 | 通过（`linkage-gas-page.png`，`pixel_diff=true`） |
| 答辩全屏 | 全局头/导入/回收站隐藏、控制层服务状态保留、电阻率章节渲染像素门、Escape 退出 | 通过（`presentation-resistivity-page.png`） |
| 手机 390×844 | 摘要优先顺序（选择→摘要→发现→证据→全屏入口）+ 零横向溢出 + 全屏三维渲染像素门 + 关闭恢复 | 通过（`phone-summary-first-page.png`、`phone-gas-page.png`） |

## 3. fail-closed 网络/控制台结论（修复项 2）

- `requestfailed` 记录 method、完整 URL、path、errorText、时间戳；每用例结束断言
  未解释网络失败、console error、pageerror 全部为零。
- 唯一白名单：`net::ERR_ABORTED` 且同路径随后真实 200（证明恢复）。
- 本轮实测：仅 1 条 `GET /SuperMap3D-2026/SuperMap3D.js net::ERR_ABORTED`
  （指挥舱切换案例时旧 iframe 拆除中止在途 SDK 请求），同路径随后 6 次 200，
  全部场景通过像素门；无其他网络失败，console error 0，pageerror 0。
- 旧证据中「GET /SuperMap3D-2026/SuperMap3D.js 失败」即此机制，已按上述白名单
  得到解释与证明；不存在按路径的宽泛忽略。

## 4. 合并前审查修复对照

1. 答辩全屏：`/presentation` 路由隐藏 AppHeader（导入数据/答辩模式/回收站等
   入口不可见），控制层保留服务状态/退出/上下节/章节目录；Mock E2E 与 live
   断言危险入口不可见、场景渲染、Escape 退出。
2. live 门 fail-closed：见第 3 节。
3. 手机首页信息顺序：390×844 改为「案例选择条 → 案例摘要（含唯一主动作）→
   关键发现 → 证据带 → 打开全屏三维」；内嵌三维默认不渲染，全屏打开不重建
   iframe（同一面板转为视口覆盖）；桌面三栏与三案例切换不回归（mock + live 门）。
4. 投影可读性：`--s1-text-faint` 由 `#5f7168`（实测 3.25–3.72:1）调整为
   `#87998f`（全表面 ≥ 5.6:1），对比度合同测试锁定 ≥ 4.5:1；发现证据 chips、
   限制说明、案例轨、证据带、证据坞、答辩章节标签等说明文字由 11px 提升为
   12px（token 级有控制修正，全站字号未粗暴放大，四档溢出门保持绿色）。
5. 证据刷新：本轮证据在最终代码 HEAD（`7a66f17`）产出，隔离数据目录
   `D:/temp/v090-live-data`、独立端口 5279，未占用 8000。

## 5. 验收口径对照（设计 §17）

- §17.1 首页与导航：首屏识别平台定位/当前案例/三维/发现/自定义入口；切换整体联动；官方案例无上传步骤；每页唯一主动作。
- §17.2 数据接入：同屏预览/映射/质量/空间检查；未知 CRS 声明局部线性，无伪 EPSG；阻断/警告分级。
- §17.3 调参与模型选择：参数影响摘要、流水线「阶段估计」、2–4 候选兼容比较与不兼容 fail-closed。
- §17.4 成果与分析：五模式渲染保持；图表↔三维双向联动（live 像素 diff）；结论卡带 source/confidence/limitations；环图仅部分-整体口径。
- §17.5 视觉与动效：四档零横向溢出；reduced-motion token；无长期闪烁；投影对比度达标。
- §17.6 真实浏览器门：见第 2 节。

## 6. 已知边界（本版本不回避）

- 三案例均为局部线性米制坐标 + `display_anchor_only` 显示锚点，非真实地理配准。
- 瓦斯 58 点稀疏采样，官方基线 R² 为负：解释性估计，页面不输出安全/危险规范结论。
- 趋势图点击驱动切片只在体渲染成果页可用；XY 区域过滤当前渲染器不支持，显示类型化能力通知。
- 答辩模式章节不自动播放；镜头书签仅元数据，场景未就绪不移镜。
- 首页三维资产未创建时显示显式创建入口（POST 只接受显式变异，合同不变）。
- 手机档内嵌三维默认不渲染但 iframe 仍后台初始化（首次全屏打开即时可见）；
  该取舍已记录，后续版本可评估懒初始化。
- iServer 不参与 v0.9.0 浏览器链路；发布登记保持 `manual_required`。
