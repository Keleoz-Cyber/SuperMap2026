import { defineConfig } from '@playwright/test'

// Live E2E：真实 FastAPI + 临时 SQLite + 真实前端，不用 Mock API。
// 调用环境必须提供唯一的 GEOMODELING_DATA_DIR（见 e2e-live 规格中的断言）。
export default defineConfig({
  testDir: './e2e-live',
  timeout: 120_000,
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL: process.env.GEOMODELING_E2E_URL ?? 'http://127.0.0.1:5201',
    testIdAttribute: 'data-test',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command:
      'python -m uvicorn geomodeling.api.app:app --host 127.0.0.1 --port 5201 --workers 1',
    url: 'http://127.0.0.1:5201/api/health',
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
