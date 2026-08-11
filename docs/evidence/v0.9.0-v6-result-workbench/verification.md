# V6 成果工作台真实浏览器验收

日期：2026-08-11
运行环境：本机 RTX GPU、真实 FastAPI（隔离数据目录 `D:/temp/v6-acceptance-data`）、真实 SuperMap3D SDK（`web/public/SuperMap3D-2026`）、官方电阻率普通克里金成果。
运行命令：

```powershell
cd web
$env:GEOMODELING_DATA_DIR = "D:/temp/v6-acceptance-data"
$env:GEOMODELING_LIVE_PORT = "5279"
$env:PYTHONPATH = "<repo>/src"
npx playwright test -c playwright.live.config.ts result-analysis-live.spec.ts
```

证据目录：`run-20260811T090818Z/`（功能代码 HEAD 见文末提交链；相机常数 2.62/2.3 为该次运行的真实取值）。

## 验收结果（真实 SDK，2 passed）

| 门 | 1920×1080 | 1440×900 |
| --- | --- | --- |
| 页面级滚动/横向溢出 | 0 / 0（四元组全 0） | 0 / 0 |
| 三栏宽度（工具/场景/研判） | 328 / 1494 / 390 px | 328 / ~750 / 390 px（门限 ≥300/520/350） |
| 证据窗首屏完整可见 | 是（底边 ≤ 视口） | 是 |
| 默认渲染状态 | lighting=false、gradientOpacity=false、boundingBox=true（复选框与 INIT 双重断言） | 同左 |
| 体场非背景像素包围盒高度占比 | **0.6958**（合同 0.58–0.72） | 同合同（1920 门内断言） |
| 坐标架几何 | originOutsideBounds=true，轴长比 x/y/z=1.25（合同 1.2–1.3） | 同左 |
| 四证据标签切换 | 综合分析/切片与异常/模型证据/数据溯源全部非空可切 | 是 |
| 规则研判/AI 辅助 | 双标签可切；DeepSeek 未配置显示 DEEPSEEK_NOT_CONFIGURED 类型化状态 | — |
| 组件聚焦/四视角/三模式互斥 | 通过（FOCUS_ANNOTATION、cameraPreset 回执、mode 状态机） | — |
| 未解释网络失败 / console error / pageerror | 0 / 0 / 0（唯一 404 为 AI latest 无记录的预期白名单） | 0 |

## 数据与成果身份

- result_id：`c3f9468a-c571-4062-90cb-7fd4993ce5c4`（官方普通克里金，预置 seed）
- grid_sha256：`079c410f071b8698…`（完整值见 `v6-workbench-1920x1080.json`）
- 分析版本：`result_analysis.v1`；坐标：局部线性 `display_anchor_only`（页面如实显示）

## 截图

- [1920×1080 一屏](run-20260811T090818Z/v6-workbench-1920x1080.png)
- [1440×900 一屏](run-20260811T090818Z/v6-workbench-1440x900.png)

## 人工视觉复核结论（对照 V6 预览稿）

- 层级：顶栏/摘要条/三栏舞台/证据窗四层与 V6 同构；真实体渲染替代静态示意体。
- 字号：工具组标签 12px、正文/控件 12–14px、摘要指标 16px，无小于 12px 正文。
- 对齐：控件按组网格排布；证据图表横向分列；无双重外壳、无大块无意义留白。
- 遮挡：无文字遮挡/裁切；右栏与证据窗内容在内部滚动，页面不滚动。
- 体场占比 0.6958 落在合同区间；XYZ 轴位于包围盒外且清晰可读，深度刻度独立成尺。

## 已知边界

- 坐标架/刻度为显示辅助，非真实地理配准；局部线性坐标口径不变。
- 组件标注 >6 个时颜色循环复用；标注引线高度为取景跨度 4%（非物理语义）。
- 手机/平板档位的成果页沿既有响应式合同（本批 live 门覆盖 1920×1080 与 1440×900 两档桌面验收）。
- AI 未配置路径已验；真实 DeepSeek 调用未验（无密钥，合同与降级由后端/前端单测覆盖）。
