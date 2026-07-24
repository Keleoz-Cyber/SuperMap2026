/// <reference types="vitest/config" />
import { createLogger, defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Cesium 以全局脚本方式（public/Cesium，运行时解析）引入是既定架构，
// Vite 对 <script src> 与 public CSS 的两条提示属于预期行为，在此精确过滤以保持构建零警告。
const CESIUM_HTML_NOTES = [
  'Cesium/Cesium.js',
  "doesn't exist at build time",
]
const logger = createLogger()
const rawWarn = logger.warn
const rawWarnOnce = logger.warnOnce
const isCesiumNote = (msg: string) => CESIUM_HTML_NOTES.some((s) => msg.includes(s))
logger.warn = (msg, options) => {
  if (isCesiumNote(msg)) return
  rawWarn(msg, options)
}
logger.warnOnce = (msg, options) => {
  if (isCesiumNote(msg)) return
  rawWarnOnce(msg, options)
}

// 构建产物由 FastAPI StaticFiles 托管，因此 base 使用相对路径；
// 开发时 /api 代理到本机 FastAPI。
export default defineConfig({
  base: './',
  customLogger: logger,
  plugins: [vue()],
  test: {
    environment: 'jsdom',
    // e2e 为 Playwright 规格，不属于 vitest
    exclude: ['e2e/**', 'node_modules/**', 'dist/**'],
  },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
  build: {
    // element-plus 全量引入体积较大，演示工程允许单 chunk 超过默认 500kB 阈值
    chunkSizeWarningLimit: 3000,
    rollupOptions: {
      onwarn(warning, warn) {
        // element-plus 依赖 @vueuse/core 中的 PURE 注释位置导致的良性 Rollup 提示
        if (warning.code === 'INVALID_ANNOTATION') return
        warn(warning)
      },
      output: {
        manualChunks: {
          vendor: ['vue', 'vue-router'],
          element: ['element-plus', '@element-plus/icons-vue'],
        },
      },
    },
  },
})
