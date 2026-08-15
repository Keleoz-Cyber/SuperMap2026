# AI Service Settings Implementation Plan


**Goal:** 为 Windows 免安装版增加安全、可视化的 DeepSeek 配置闭环。

**Architecture:** `deepseek_credentials.py` 隔离 Windows Credential API 与配置解析；独立 FastAPI 路由只公开脱敏 DTO；Vue 全局设置弹窗由 AppShell 提供，顶栏和 AI 未配置状态复用。环境变量优先于凭据存储。

**Tech Stack:** Python 3.12、ctypes WinCred、FastAPI/Pydantic、httpx、Vue 3、Element Plus、Vitest、pytest。

---

### Task 1: 凭据与解析服务

**Files:**
- Create: `src/geomodeling/integrations/deepseek_credentials.py`
- Modify: `src/geomodeling/integrations/deepseek.py`
- Test: `tests/test_ai_settings.py`

- [ ] 先写内存后端测试，覆盖环境变量优先、凭据保存/读取/清除、脱敏状态和非法配置。
- [ ] 运行 `python -m pytest tests/test_ai_settings.py -q`，确认因实现缺失而失败。
- [ ] 实现 Windows Generic Credential 后端、配置解析器和适配器接入。
- [ ] 重跑目标测试，确认通过且响应/`repr` 不含 Key。

### Task 2: 配置 API

**Files:**
- Create: `src/geomodeling/api/routes/ai_settings.py`
- Modify: `src/geomodeling/api/app.py`
- Test: `tests/test_ai_settings_api.py`

- [ ] 先写 API 测试，覆盖 GET 脱敏、POST 保存、连接测试诊断、DELETE 和环境变量只读。
- [ ] 运行目标测试并确认红灯原因是路由缺失。
- [ ] 实现四个接口及可替换服务依赖，统一使用平台错误封套。
- [ ] 重跑目标测试并确认通过。

### Task 3: 前端设置入口

**Files:**
- Create: `web/src/components/settings/AIServiceSettingsDialog.vue`
- Create: `web/src/components/settings/aiSettingsContext.ts`
- Create: `web/src/components/settings/__tests__/AIServiceSettingsDialog.spec.ts`
- Modify: `web/src/api/client.ts`
- Modify: `web/src/api/types.ts`
- Modify: `web/src/components/shell/AppHeader.vue`
- Modify: `web/src/components/shell/AppShell.vue`
- Modify: `web/src/components/results/AIAssistedReview.vue`

- [ ] 先写组件与客户端测试，覆盖状态加载、Key 不回显、测试、保存、清除及未配置入口。
- [ ] 运行 `npm --prefix web run test:unit -- AIServiceSettingsDialog`，确认红灯。
- [ ] 实现弹窗、全局上下文和 API 客户端；桌面/移动顶栏与 AI 未配置卡片均可打开。
- [ ] 重跑单测、类型检查和构建。

### Task 4: 便携说明与回归

**Files:**
- Modify: `scripts/build_portable.py`
- Modify: `docs/项目特色与技术全景.md`
- Test: `tests/test_portable_build.py`

- [ ] 先更新便携说明契约测试，要求 UI 配置为主流程且不得包含真实 Key。
- [ ] 更新生成说明与项目技术说明，保留环境变量作为备用方法。
- [ ] 运行 AI/便携相关后端测试、前端全量单测、类型检查、构建及 `git diff --check`。
