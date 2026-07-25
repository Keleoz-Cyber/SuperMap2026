import { expect, test } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// Live E2E：真实 FastAPI + 独立临时 SQLite + 真实建模 Worker。
// 不使用 Mock API、iServer、私有资料或本机绝对路径。

const HERE = path.dirname(fileURLToPath(import.meta.url))
const DEMO_CSV = path.resolve(HERE, '../../demo/platform_demo_3d.csv')

function assertIsolatedDataDir() {
  const dir = process.env.GEOMODELING_DATA_DIR
  if (!dir) {
    throw new Error('Live E2E 要求调用环境提供唯一的 GEOMODELING_DATA_DIR')
  }
  const normalized = dir.replace(/\\/g, '/')
  if (normalized.endsWith('var/geomodeling') || normalized.endsWith('var/demo_v041')) {
    throw new Error(`Live E2E 不得使用默认/演示数据目录：${dir}`)
  }
}

test.beforeAll(() => {
  assertIsolatedDataDir()
})

test('真实链路：上传 → 映射 → 质量 → IDW → 排行榜 → 成果切片 → 选择 → 导出 → 首页', async ({
  page,
  request,
}) => {
  // 1. 真实健康检查（非 Mock）
  const health = await request.get('/api/health')
  expect(health.ok()).toBe(true)
  const healthBody = await health.json()
  expect(healthBody.status).toBe('ok')
  expect(healthBody.version).toMatch(/^\d+\.\d+\.\d+/)

  const caseName = `Live 演示 ${Date.now()}`

  // 2. 首页创建案例
  await page.goto('/')
  await page.getByTestId('create-case-card').click()
  await page.getByTestId('case-name').fill(caseName)
  await page.getByTestId('case-file').setInputFiles(DEMO_CSV)
  await page.getByTestId('case-submit').click()
  await expect(page).toHaveURL(/#\/cases\/[0-9a-f-]+\/datasets\/[0-9a-f-]+\/prepare/)

  // 3. 映射 + 质量门禁
  await expect(page.getByTestId('step-file')).toContainText('platform_demo_3d.csv')
  await page.getByTestId('mapping-value-name').fill('电阻率（演示）')
  await page.getByTestId('mapping-submit').click()
  await expect(page.getByTestId('quality-banner')).toContainText('质量校验通过', {
    timeout: 30_000,
  })
  await page.getByTestId('start-experiment').click()
  await expect(page).toHaveURL(/#\/cases\/[0-9a-f-]+\/experiments\/new/)

  // 4. 手动 IDW 单组（power=2, neighbor_count=16 默认）
  await page.getByTestId('exp-name').fill('Live IDW')
  await page.getByTestId('exp-submit').click()
  await expect(page).toHaveURL(/#\/experiments\/[0-9a-f-]+/)

  // 5. 有界轮询至成功；排行榜出现公共有效数与有限 RMSE
  await expect(page.getByTestId('run-progress')).toContainText('succeeded', { timeout: 60_000 })
  const board = page.getByTestId('leaderboard')
  await expect(board).toContainText('公共有效点 144', { timeout: 30_000 })
  const firstRow = page.getByTestId('candidate-row').first()
  await expect(firstRow).toContainText(/\d+\.\d{3}/)

  // 6. 打开成果：完整场 + X/Y/Z 切片（真实坐标标签为数值）
  await page.getByTestId('open-result').first().click()
  await expect(page).toHaveURL(/#\/results\/[0-9a-f-]+/)
  await expect(page.getByTestId('preview-count')).toContainText(/\d+ \/ \d+/, { timeout: 30_000 })
  await page.getByTestId('tab-slices').click()
  await expect(page.getByTestId('slice-label')).toContainText(/Z = -?\d+(\.\d+)? m/)
  await page.getByTestId('axis-x').click()
  await expect(page.getByTestId('slice-label')).toContainText(/X = -?\d+(\.\d+)? m/)
  await page.getByTestId('axis-y').click()
  await expect(page.getByTestId('slice-label')).toContainText(/Y = -?\d+(\.\d+)? m/)

  // 7. 正式选择（理由必填）并持久化
  const reason = `Live 选择 ${Date.now()}`
  await page.getByTestId('selection-note').fill(reason)
  await page.getByTestId('selection-submit').click()
  await expect(page.getByTestId('formal-selection-panel')).toContainText(reason)
  await page.reload()
  await expect(page.getByTestId('formal-selection-panel')).toContainText(reason, {
    timeout: 30_000,
  })

  // 8. 导出证据 ZIP（下载事件验证真实 ZIP 字节）
  await page.getByTestId('export-button').click()
  const downloadPromise = page.waitForEvent('download', { timeout: 60_000 })
  await page.getByTestId('export-download').click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toMatch(/\.zip$/)
  const zipPath = await download.path()
  const zipBytes = await readFile(zipPath)
  expect(zipBytes.length).toBeGreaterThan(100)
  expect(zipBytes.subarray(0, 2).toString()).toBe('PK')

  // 9. 返回实验 → 返回首页；案例卡持久化可见
  await page.getByTestId('nav-experiment').click()
  await expect(page).toHaveURL(/#\/experiments\/[0-9a-f-]+/)
  await page.getByTestId('nav-home').click()
  await expect(page).toHaveURL(/#\/$/)
  await expect(page.getByText(caseName)).toBeVisible()
})
