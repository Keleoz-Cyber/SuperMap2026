import { defineConfig } from '@playwright/test'

// Live E2E：真实 FastAPI + 临时 SQLite + 真实前端，不用 Mock API。
// 调用环境必须提供唯一的 GEOMODELING_DATA_DIR（见 e2e-live 规格中的断言）。
// 端口默认 5201，可用 GEOMODELING_LIVE_PORT 覆盖（本机 5201 落入 Windows
// Hyper-V 保留端口段 5141–5240 时必须显式改口；CI 不传即保持 5201）。
const livePort = Number(process.env.GEOMODELING_LIVE_PORT ?? 5201)

export default defineConfig({
  testDir: './e2e-live',
  timeout: 120_000,
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL: process.env.GEOMODELING_E2E_URL ?? `http://127.0.0.1:${livePort}`,
    testIdAttribute: 'data-test',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: `python -m uvicorn geomodeling.api.app:app --host 127.0.0.1 --port ${livePort} --workers 1`,
    url: `http://127.0.0.1:${livePort}/api/health`,
    reuseExistingServer: false,
    timeout: 60_000,
    stdout: 'pipe',
    stderr: 'pipe',
    env: {
      // webServer 以 web/ 为工作目录，前端产物路径按仓库根解析
      GEOMODELING_FRONTEND_DIST: '../web/dist',
    },
  },
})
