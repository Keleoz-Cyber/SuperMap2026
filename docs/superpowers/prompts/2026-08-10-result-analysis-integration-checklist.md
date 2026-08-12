# 集成负责人检查表

输入：后端 Agent 完整汇报、前端 Agent 完整汇报、两份已提交的交接文件和当前串行分支 HEAD。集成发生在同一个 `feat/v0.9.0-visual-product` worktree，不再合并两个并行分支。

1. 先核对后端汇报中的 HEAD/合同/测试，再核对前端汇报中的基线 HEAD/最终 HEAD/截图/测试；任一与磁盘不一致时以磁盘为准并明确记录。
2. 对比 Pydantic DTO、JSON 合同夹具、TypeScript 类型和 Mock 响应，字段/枚举/空值必须逐项一致。
3. 启动真实 FastAPI，验证前端不依赖 Mock；检查结果切换后的旧状态清理。
4. 用真实电阻率成果验证完整场、切片、A/B/C、四视角相机和双向联动。
5. 分别验证 DeepSeek 未配置、fake 成功/fail、用户提供 Key 的可选 live；不得把 Key 写入命令历史截图或证据包。
6. 检查 1920×1080 首屏、常见笔记本尺寸、字号、对齐、溢出、图表 resize 和 iframe 资源释放。
7. 运行完整后端、Vitest、type-check、build、Mock/Live E2E、secret scan 和 `git diff --check`。
8. 只修复合同桥接和真实验收缺陷；较大功能退回对应 Agent，并附新的提示词与当前完整汇报，不在集成阶段静默重写。
9. 更新证据与 PR 描述，保持 PR OPEN，等待用户决定合并和发布。
