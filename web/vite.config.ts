/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 构建产物由 FastAPI StaticFiles 托管，因此 base 使用相对路径；
// 开发时 /api 代理到本机 FastAPI。
export default defineConfig({
  base: './',
  plugins: [vue()],
  test: {
    environment: 'jsdom',
    // e2e / e2e-live 为 Playwright 规格，不属于 vitest
    exclude: ['e2e/**', 'e2e-live/**', 'node_modules/**', 'dist/**'],
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
