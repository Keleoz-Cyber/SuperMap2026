import { expect, test, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  analyzeVolumePixels,
  expectVolumeContent,
  installLiveProbe,
  probeMessages,
} from './v070RenderGates'

/**
 * v0.9.0 Task 11：真实电阻率成果的成果级分析与三维标注联动门。
 *
 * 链路：隔离数据目录 → 内置电阻率预置 → 官方普通克里金成果 →
 * analysis-summary → 显式 NetCDF 资产 POST → 真实 SuperMap3D iframe →
 * 组件聚焦/四视角/切片共享阈值/三种互斥模式 → DeepSeek 未配置降级。
 * 本门不调用外部 LLM，也不依赖 Mock API。
 */

const HERE = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(HERE, '../..')
const EVIDENCE_DIR = path.join(REPO_ROOT, 'docs', 'evidence', 'v0.9.0-result-analysis-live')
const VIEWPORT = { width: 1920, height: 1080 }

interface SeedResult {
  official_result: { result_id: string }
}

function isolatedDataDir(): string {
  const dir = process.env.GEOMODELING_DATA_DIR
  if (!dir) throw new Error('Live E2E 要求 GEOMODELING_DATA_DIR 指向隔离目录')
  const normalized = dir.replace(/\\/g, '/')
  if (normalized.endsWith('var/geomodeling') || normalized.endsWith('var/demo_v041')) {
    throw new Error(`Live E2E 不得使用默认/演示数据目录：${dir}`)
  }
  return dir
}

function pathOf(url: string): string {
  try {
    return new URL(url).pathname
  } catch {
    return url
  }
}

async function frameDiag(page: Page): Promise<Record<string, any>> {
  const frame = page.frames().find((item) => item.url().includes('/supermap-volume-frame/'))
  expect(frame, '真实 SuperMap3D 子帧应存在').toBeTruthy()
  return frame!.evaluate(() => (window as any).__GMP_VOLUME_FRAME__)
}

test.use({ launchOptions: { args: ['--use-angle=gl'] } })

test('官方电阻率成果：规则分析、三维组件、切片、相机、AI 降级保持同一身份', async ({
  page,
  request,
}) => {
  test.setTimeout(420_000)
  const dataDir = isolatedDataDir()
  const seededRaw = execFileSync(
    process.env.PYTHON ?? 'python',
    ['-m', 'geomodeling.preset_cli', 'seed-resistivity', '--data-dir', dataDir],
    { cwd: REPO_ROOT, encoding: 'utf8', timeout: 180_000 },
  )
  const seeded = JSON.parse(seededRaw.trim().split('\n').pop()!) as SeedResult
  const resultId = seeded.official_result.result_id

  const networkFailures: string[] = []
  const consoleEntries: Array<{ type: string; text: string; location: string }> = []
  const benignStatuses = new Set([
    `/api/results/${resultId}/render-assets/netcdf`,
    `/api/results/${resultId}/ai-analysis/latest`,
  ])
  page.on('requestfailed', (req) => {
    networkFailures.push(`${req.method()} ${pathOf(req.url())} ${req.failure()?.errorText ?? ''}`)
  })
  page.on('response', (resp) => {
    const pathname = pathOf(resp.url())
    if (resp.status() >= 400 && !benignStatuses.has(pathname)) {
      networkFailures.push(`${resp.status()} ${resp.request().method()} ${pathname}`)
    }
  })
  page.on('console', (message) => {
    consoleEntries.push({
      type: message.type(),
      text: message.text(),
      location: pathOf(message.location()?.url ?? ''),
    })
  })
  page.on('pageerror', (error) =>
    consoleEntries.push({ type: 'pageerror', text: String(error), location: '' }),
  )

  const summaryResponse = await request.get(`/api/results/${resultId}/analysis-summary`)
  expect(summaryResponse.ok()).toBe(true)
  const summary = await summaryResponse.json()
  expect(summary.identity.result_id).toBe(resultId)
  expect(summary.identity.grid_sha256).toMatch(/^[0-9a-f]{64}$/)
  expect(summary.identity.dimension).toBe('3d')
  expect(summary.grid.valid_count).toBeGreaterThan(0)
  expect(summary.components_preview.rows.length).toBeGreaterThan(0)
  expect(
    summary.composition.buckets.reduce((total: number, row: { count: number }) => total + row.count, 0),
  ).toBe(summary.grid.valid_count)

  await installLiveProbe(page)
  await page.setViewportSize(VIEWPORT)
  await page.goto(`/#/results/${resultId}`, { waitUntil: 'load', timeout: 60_000 })
  await expect(page.getByTestId('result-analysis-workbench')).toBeVisible({ timeout: 60_000 })
  await expect(page.getByTestId('result-interpretation')).toBeVisible({ timeout: 60_000 })
  await expect(page.getByTestId('interpretation-components')).toContainText(
    summary.components_preview.rows[0].label,
  )
  await expect(page.getByTestId('ge-scope-badge')).toContainText('成果网格')

  const createAsset = page.getByTestId('create-asset')
  if (await createAsset.isVisible().catch(() => false)) {
    await createAsset.click()
  }
  await expect(page.getByTestId('volume-phase')).toHaveText('已渲染', { timeout: 90_000 })
  const frameShot = await page.getByTestId('volume-frame').screenshot()
  expectVolumeContent(await analyzeVolumePixels(page, frameShot), 'v0.9 成果分析体渲染', {
    minNonBg: 1200,
    minCoverage: 0.08,
  })

  const renderedMessages = await probeMessages(page)
  const rendered = renderedMessages.find((message) => message.type === 'RENDER_STATE' && message.phase === 'rendered')
  expect(rendered?.identity?.sourceId).toBe(resultId)
  expect(rendered?.identity?.gridSha256).toBe(summary.identity.grid_sha256)

  let diag = await frameDiag(page)
  expect(diag.phase).toBe('rendered')
  expect(diag.annotations.total).toBe(summary.components_preview.rows.length)
  expect(diag.annotations.visible).toBe(summary.components_preview.rows.length)

  const firstComponent = summary.components_preview.rows[0]
  await page.getByTestId(`component-${firstComponent.component_id}`).click()
  await expect
    .poll(async () => (await frameDiag(page)).annotations.focusedId)
    .toBe(`component-${firstComponent.component_id}`)

  for (const preset of ['top-xy', 'front-xz', 'front-yz', 'isometric']) {
    await page.getByTestId(`camera-${preset}`).click()
    await expect.poll(async () => (await frameDiag(page)).cameraPreset).toBe(preset)
  }

  await page.getByTestId('mode-slice').click()
  await expect.poll(async () => (await frameDiag(page)).mode).toBe('slice')
  await expect(page.getByTestId('interpretation-slice')).not.toContainText('进入切片模式后')
  await expect(page.getByTestId('interpretation-slice')).toContainText('完整网格 p25/p75')
  await page.getByTestId('mode-contour').click()
  await expect.poll(async () => (await frameDiag(page)).mode).toBe('contour')
  await page.getByTestId('mode-volume').click()
  await expect.poll(async () => (await frameDiag(page)).mode).toBe('volume')

  await page.getByTestId('side-tab-ai').click()
  await expect(page.getByTestId('ai-empty')).toBeVisible()
  await page.getByTestId('ai-generate').click()
  await expect(page.getByTestId('ai-unavailable')).toContainText('DEEPSEEK_NOT_CONFIGURED')
  await page.getByTestId('side-tab-rules').click()
  await expect(page.getByTestId('result-interpretation')).toBeVisible()

  const overflow = await page.evaluate(() => ({
    documentX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    bodyX: document.body.scrollWidth - document.body.clientWidth,
    documentY: document.documentElement.scrollHeight - document.documentElement.clientHeight,
    bodyY: document.body.scrollHeight - document.body.clientHeight,
  }))
  expect(overflow.documentX).toBeLessThanOrEqual(1)
  expect(overflow.bodyX).toBeLessThanOrEqual(1)
  expect(overflow.documentY).toBeLessThanOrEqual(1)
  expect(overflow.bodyY).toBeLessThanOrEqual(1)

  mkdirSync(EVIDENCE_DIR, { recursive: true })
  await page.screenshot({ path: path.join(EVIDENCE_DIR, 'result-analysis-live-1920x1080.png') })
  writeFileSync(
    path.join(EVIDENCE_DIR, 'result-analysis-live.json'),
    `${JSON.stringify({
      result_id: resultId,
      grid_sha256: summary.identity.grid_sha256,
      valid_count: summary.grid.valid_count,
      component_count: summary.components_preview.rows.length,
      ai_status: 'unavailable',
      viewport: VIEWPORT,
      overflow,
      diag: await frameDiag(page),
      network_failures: networkFailures,
      console: consoleEntries,
    }, null, 2)}\n`,
    'utf8',
  )

  const unexplainedConsoleErrors = consoleEntries.filter(
    (entry) =>
      ['error', 'pageerror'].includes(entry.type) &&
      !(
        entry.text.includes('Failed to load resource') &&
        benignStatuses.has(entry.location)
      ),
  )
  expect(networkFailures).toEqual([])
  expect(unexplainedConsoleErrors).toEqual([])
})
