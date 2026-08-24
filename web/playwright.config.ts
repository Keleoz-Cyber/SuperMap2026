import { defineConfig } from '@playwright/test'

// 冒烟全程使用 src/mocks/platformDemo.ts 的 mock API，不需要 iServer 与任何凭据。
// 被测页面来自已构建的 dist（preview 静态托管），保证与 FastAPI 托管形态一致。
// 3000 在部分 Windows/Hyper-V 环境属于系统保留端口；默认使用 Vite preview
// 常用的 4173，并允许本机或 CI 显式覆盖。
const mockPort = Number(process.env.GEOMODELING_MOCK_PORT ?? 4173)

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  retries: 0,
  use: {
    baseURL: `http://127.0.0.1:${mockPort}`,
    // 项目组件统一使用 data-test
    testIdAttribute: 'data-test',
  },
  webServer: {
    command: `npm run preview -- --port ${mockPort} --strictPort --host 127.0.0.1`,
    url: `http://127.0.0.1:${mockPort}`,
    reuseExistingServer: false,
    timeout: 30_000,
  },
})
