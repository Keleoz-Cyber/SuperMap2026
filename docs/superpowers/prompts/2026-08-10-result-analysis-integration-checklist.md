# 集成负责人检查表

输入：后端分支 HEAD、后端合同检查点 SHA、前端分支 HEAD。集成发生在 `feat/v0.9.0-visual-product`，不在两个开发 worktree 中直接互相复制文件。

1. 先集成后端，再集成从合同检查点派生的前端；保留可审计提交历史。
2. 对比 Pydantic DTO、JSON 合同夹具、TypeScript 类型和 Mock 响应，字段/枚举/空值必须逐项一致。
3. 启动真实 FastAPI，验证前端不依赖 Mock；检查结果切换后的旧状态清理。
4. 用真实电阻率成果验证完整场、切片、A/B/C、四视角相机和双向联动。
5. 分别验证 DeepSeek 未配置、fake 成功/fail、用户提供 Key 的可选 live；不得把 Key 写入命令历史截图或证据包。
6. 检查 1920×1080 首屏、常见笔记本尺寸、字号、对齐、溢出、图表 resize 和 iframe 资源释放。
7. 运行完整后端、Vitest、type-check、build、Mock/Live E2E、secret scan 和 `git diff --check`。
8. 只修复合同桥接和真实验收缺陷；较大功能退回对应 Agent，不在集成阶段重新设计。
9. 更新证据与 PR 描述，保持 PR OPEN，等待用户决定合并和发布。
