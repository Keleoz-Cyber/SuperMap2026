# 前端 Agent 提示词：成果空间、三维联动与 AI 展示

你负责 GeoModelingPlatform v0.9.0 的前端和三维展示。目标是把真实后端合同做成 1920×1080 一屏可演示的成果分析工作台，而不是重新制作一张静态大屏。

## 开始前

- 只在 `D:\study\Contest\Supermap\.worktrees\v0.9.0-visual-product` 和 `feat/v0.9.0-visual-product` 工作；你是串行开发的第二棒，不创建并行分支。
- 用户必须同时提供本提示词和后端 Agent 的完整最终汇报。还要读取 `docs/superpowers/handoffs/2026-08-11-backend-to-frontend.md`。
- 先核对当前 HEAD、工作区、后端路由、夹具和测试是否与汇报一致；不一致时先报告，不得按旧汇报继续。
- 完整阅读设计、实施计划、后端 JSON 合同夹具、总提示词和后端交接文件。
- 负责计划 Task 6–9、Task 10 前端部分及前端 Mock E2E。原则上不修改 Python 后端、SQLite 或迁移；只有连通现有合同所必需的小修允许跨界，且必须补后端测试并写入交接报告。
- 不合并、不发布，不把静态原型业务数字复制进产品。

## 页面目标

以成果空间现有页面为基础完成：

- 左侧：真实 Volume/Slice/Contour、色带、线性/对数、过滤、透明度、光照、渐变透明度、包围盒、组件标注、XYZ/深度辅助和四种视角；
- 中央：真实体渲染，A/B/C 连通区标注，切片、坐标轴、深度刻度和组件聚焦；
- 右侧：规则研判与 AI 辅助切换，包含成果概览、异常区域、当前切片、模型与不确定性；
- 底部：成果组成、深度趋势、组件比较、切片热力图、模型指标/残差、输入样本和溯源。

页面结构参考目标截图，但所有数字和文案来自 API。不要做可拖动窗口，不要使用“结论链/行动链”，不要出现储量、危险等级或已确认边界等无证据表述。

## 三维连通性

- 扩展 iframe v2 typed protocol：annotations、focused ID、四种 camera preset、selection receipt；
- 组件列表点击聚焦三维，三维标注点击反选组件；
- 切片变化使用后端权威统计更新右侧和底部；
- 切换 result/grid identity 时先清空旧组件、旧切片和旧 AI 意见；
- Volume/Slice/Contour 保持互斥，不伪造同时叠加。

## AI 展示

- AI 放在现有研判区，不另建孤岛页面；
- 展示四视角、共识/分歧、候选研判路径、复核清单、限制和 evidence refs；
- evidence ref 点击联动组件、层段或切片；
- 显示 provider/model/时间/prompt 版本/evidence hash 短码；
- 未配置、离线、超时和失败均有真实空态，规则研判始终可用；
- 不显示虚构 AI 置信度百分比，不渲染 reasoning content。

## 视觉与验收

- 1920×1080 首屏展示核心信息，三维是最大视觉主体；
- 最小正文保持可读，标题、指标、辅助说明有清晰层级；
- 左右栏不溢出，底部证据区不出现大片无意义留白；
- 控制台错误、pageerror、未解释网络失败为零；
- 使用后端合同夹具完成 Vitest 和 Mock E2E，不在 mock 中扩展合同外字段。

## 完成汇报

1. 按 `docs/superpowers/handoffs/2026-08-11-frontend-to-integration-template.md` 写出正式交接文件，文件名固定为 `docs/superpowers/handoffs/2026-08-11-frontend-to-integration.md`，与前端代码一起提交。
2. 最终回复完整汇报后端基线 HEAD、最终 HEAD、页面入口、组件/切片/AI 联动、跨界后端修复、测试实数、1920×1080 截图、已知问题和集成注意事项。
3. 确认工作区干净，保持 PR OPEN，不合并、不发布，然后停止。

用户会把“集成检查表 + 后端完整汇报 + 前端完整汇报 + 两份交接文件”一起交给集成负责人。
