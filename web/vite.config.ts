/// <reference types="vitest/config" />
import { createHash } from 'node:crypto'
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// warm-cache 升级安全：体渲染 iframe 运行时资产（index/app/styles）以内容哈希
// 进入 iframe URL 查询串（?v=），SDK 以钉住的内容哈希进入 ?sdk=；升级即换 URL，
// 旧浏览器缓存中的任何旧版 app.js 永不命中。SDK 在 CI 构建中缺席时降级 'unpinned'
// （CI 不做真实渲染，live 门在本机钉住 SDK）。
function contentVersion(paths: string[]): string {
  const hash = createHash('sha256')
  for (const p of paths) hash.update(readFileSync(p))
  return hash.digest('hex').slice(0, 16)
}

const frameDir = resolve(__dirname, 'public/supermap-volume-frame')
const VOLUME_FRAME_VERSION = contentVersion(
  ['index.html', 'app.js', 'styles.css'].map((name) => resolve(frameDir, name)),
)
const sdkEntry = resolve(__dirname, 'public/SuperMap3D-2026/SuperMap3D.js')
const VOLUME_SDK_VERSION = existsSync(sdkEntry) ? contentVersion([sdkEntry]) : 'unpinned'

// 构建产物由 FastAPI StaticFiles 托管，因此 base 使用相对路径；
// 开发时 /api 代理到本机 FastAPI。
export default defineConfig({
  base: './',
  plugins: [vue()],
  define: {
    __VOLUME_FRAME_VERSION__: JSON.stringify(VOLUME_FRAME_VERSION),
    __VOLUME_SDK_VERSION__: JSON.stringify(VOLUME_SDK_VERSION),
  },
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
