# AI 服务设置设计

## 目标

让 Windows 免安装版用户在浏览器内配置自己的 DeepSeek API Key，并在不配置 AI 时继续使用全部确定性建模能力。

## 方案

- 全局顶栏提供“AI 服务设置”，AI 未配置状态也可直接打开同一弹窗。
- API Key 只提交到本机 FastAPI；前端不持久化、不回显、不写入日志或成果包。
- 正式存储使用当前 Windows 用户的 Generic Credential；项目目录、SQLite、Git 和便携包均不保存密钥。
- `DEEPSEEK_API_KEY` 环境变量保持最高优先级，供开发、CI 和管理员临时覆盖；环境变量来源在界面中只读。
- 配置状态接口只返回是否配置、来源和非敏感参数。保存、连接测试和清除均为显式操作。
- 连接测试调用 DeepSeek `/models`，只验证网络与鉴权，不生成对话内容。

## 接口

- `GET /api/settings/ai`：读取脱敏状态。
- `POST /api/settings/ai`：保存 Windows 凭据配置，Key 使用 `SecretStr`。
- `POST /api/settings/ai/test`：使用输入配置或现有配置验证连接。
- `DELETE /api/settings/ai`：清除 Windows 凭据；环境变量配置不可通过网页删除。

## 错误与安全

- 不支持 Windows 凭据管理器时返回类型化错误，不退回明文文件。
- 鉴权失败、余额不足、限流、超时和网络异常使用稳定诊断码，响应不包含 Key 或上游响应体。
- DeepSeek 失败不阻断规则分析、插值、成果展示和导出。

## 验收

- 浏览器可查看配置状态、测试、保存和清除；Key 永不回传。
- 保存后无需重启即可生成 AI 研判。
- 环境变量优先级保持兼容。
- 便携构建包含更新后的使用说明，说明 UI 为主流程、命令行为备用流程。
