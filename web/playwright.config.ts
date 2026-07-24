import { defineConfig } from '@playwright/test'

// 冒烟全程使用 src/mocks/platformDemo.ts 的 mock API，不需要 iServer 与任何凭据。
// 被测页面来自已构建的 dist（preview 静态托管），保证与 FastAPI 托管形态一致。
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  retries: 0,
  use: {
    baseURL: 'http://localhost:5199',
    // 项目组件统一使用 data-test
    testIdAttribute: 'data-test',
  },
  webServer: {
    command: 'npm run preview -- --port 5199 --strictPort',
    url: 'http://localhost:5199',
    reuseExistingServer: false,
    timeout: 30_000,
  },
})
