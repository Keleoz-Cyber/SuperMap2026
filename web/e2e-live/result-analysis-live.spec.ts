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
// v0.9.0 V6 Task 7：证据按运行时间分目录（同一 commit 的验收运行可复核）
const RUN_ID = `run-${new Date().toISOString().replace(/[-:]/g, '').replace(/\..*/, '').replace('T', 'T')}Z`
const EVIDENCE_DIR = path.join(REPO_ROOT, 'docs', 'evidence', 'v0.9.0-v6-result-workbench', RUN_ID)
const VIEWPORT = { width: 1920, height: 1080 }
const VIEWPORT_1440 = { width: 1440, height: 900 }

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

// 体场主体非背景像素包围盒占比。调用前必须关闭组件标注、XYZ 轴与深度刻度，
// 防止覆盖物把“体场很小”误判为通过；中央裁剪排除 Logo/罗盘。
async function contentBoundingRatios(page: Page, shot: Buffer): Promise<{ width: number; height: number }> {
  const dataUrl = 'data:image/png;base64,' + shot.toString('base64')
  return page.evaluate(async (src: string) => {
    const img = new Image()
    await new Promise((res, rej) => {
      img.onload = res
      img.onerror = rej
      img.src = src
    })
    const c = document.createElement('canvas')
    c.width = img.width
    c.height = img.height
    const ctx = c.getContext('2d')!
    ctx.drawImage(img, 0, 0)
    const x0 = Math.floor(img.width * 0.32)
    const x1 = Math.floor(img.width * 0.68)
    // 跳过元素边框带（.volume-frame 有 1px 边框，边框色高于背景阈值）
    const yStart = 3
    const yEnd = img.height - 3
    let top = -1
    let bottom = -1
    let left = x1
    let right = x0
    for (let y = yStart; y < yEnd; y += 1) {
      const d = ctx.getImageData(x0, y, x1 - x0, 1).data
      let rowNonBg = 0
      for (let i = 0; i < d.length; i += 4) {
        if (d[i] > 12 || d[i + 1] > 12 || d[i + 2] > 12) {
          rowNonBg += 1
          const x = x0 + i / 4
          left = Math.min(left, x)
          right = Math.max(right, x)
        }
      }
      if (rowNonBg > 4) {
        if (top < 0) top = y
        bottom = y
      }
    }
    return top >= 0
      ? {
          // 宽度按完整 iframe 计，不能用中央裁剪带作分母放大结果。
          width: (right - left + 1) / img.width,
          height: (bottom - top + 1) / (yEnd - yStart),
        }
      : { width: 0, height: 0 }
  }, dataUrl)
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
  // 资产不存在的 404 是正常探测；按钮由异步能力检查后出现，不能在首帧立即判定不存在。
  await createAsset.waitFor({ state: 'visible', timeout: 15_000 }).catch(() => undefined)
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
  const expectedSceneAnnotations = summary.components_preview.rows.length
  expect(diag.annotations.total).toBe(expectedSceneAnnotations)
  expect(diag.annotations.visible).toBe(expectedSceneAnnotations)

  // v0.9.0 V6 Task 5：坐标架几何合同——原点在包围盒外，轴长比 1.2–1.3
  expect(diag.sceneAidsGeometry?.originOutsideBounds).toBe(true)
  for (const ratio of Object.values(
    diag.sceneAidsGeometry.axisLengthRatios as Record<string, number>,
  )) {
    expect(ratio).toBeGreaterThanOrEqual(1.2)
    expect(ratio).toBeLessThanOrEqual(1.3)
  }

  // v0.9.0 V6 Task 2/5：默认渲染状态——光照/渐变透明度关闭，包围盒开启
  await expect(page.getByTestId('lighting-toggle').locator('input')).not.toBeChecked()
  await expect(page.getByTestId('gradient-opacity-toggle').locator('input')).not.toBeChecked()
  await expect(page.getByTestId('bounding-box-toggle').locator('input')).toBeChecked()

  // v0.9.0 V6 补强：测量体场本体前关闭覆盖物，避免坐标轴/标签造成视觉假绿。
  for (const id of ['annotations-toggle', 'axes-toggle', 'depth-ticks-toggle']) {
    const input = page.getByTestId(id).locator('input')
    if (await input.isChecked()) await page.getByTestId(id).click()
  }
  const bodyShot = await page.getByTestId('volume-frame').screenshot()
  const volumeRatios = await contentBoundingRatios(page, bodyShot)
  const initialCameraGeometry = (await frameDiag(page)).geometry
  expect(volumeRatios.height).toBeGreaterThanOrEqual(0.58)
  expect(
    volumeRatios.height,
    `initial camera geometry: ${JSON.stringify(initialCameraGeometry)}`,
  ).toBeLessThanOrEqual(0.76)
  expect(volumeRatios.width).toBeGreaterThanOrEqual(0.24)
  for (const id of ['annotations-toggle', 'axes-toggle', 'depth-ticks-toggle']) {
    await page.getByTestId(id).click()
  }

  // v0.9.0 V6 Task 7：一屏布局测量——顶栏/摘要条/三栏舞台/证据窗
  await expect(page.getByTestId('app-global-header')).toBeVisible()
  await expect(page.getByTestId('v6-result-summary')).toBeVisible()
  expect(page.getByTestId('page-navigation')).toHaveCount(0)
  expect(page.getByTestId('asset-identity')).toHaveCount(0)
  const columns = await page.evaluate(() => {
    const rail = document.querySelector('[data-test="tools-rail"]')?.getBoundingClientRect()
    const scene = document.querySelector('[data-test="result-scene"]')?.getBoundingClientRect()
    const side = document.querySelector('[data-test="result-analysis-side"]')?.getBoundingClientRect()
    return { rail: rail?.width ?? 0, scene: scene?.width ?? 0, side: side?.width ?? 0 }
  })
  expect(columns.rail).toBeGreaterThanOrEqual(300)
  expect(columns.scene).toBeGreaterThanOrEqual(560)
  expect(columns.side).toBeGreaterThanOrEqual(350)
  // 证据窗首屏完整可见（底边不超过视口）
  const dockBox = await page.getByTestId('result-evidence-dock').boundingBox()
  expect(dockBox).toBeTruthy()
  expect(dockBox!.y + dockBox!.height).toBeLessThanOrEqual(VIEWPORT.height + 1)

  const firstComponent = summary.components_preview.rows[0]
  await page.getByTestId(`component-${firstComponent.component_id}`).click()
  await expect
    .poll(async () => (await frameDiag(page)).annotations.focusedId)
    .toBe(`component-${firstComponent.component_id}`)

  for (const preset of ['top-xy', 'front-xz', 'front-yz', 'isometric']) {
    await page.getByTestId(`camera-${preset}`).click()
    await expect.poll(async () => (await frameDiag(page)).cameraPreset).toBe(preset)
  }

  // 成果尺度相关的相机安全区：滚轮单步约 8%，SDK 导航条与滚轮共享上下限。
  const frame = page.frames().find((item) => item.url().includes('/supermap-volume-frame/'))!
  const cameraBefore = (await frameDiag(page)).geometry
  expect(cameraBefore.cameraRangeMetres).toBeGreaterThanOrEqual(cameraBefore.cameraRangeBoundsMetres[0])
  expect(cameraBefore.cameraRangeMetres).toBeLessThanOrEqual(cameraBefore.cameraRangeBoundsMetres[1])
  await frame.locator('canvas').hover()
  await page.mouse.wheel(0, 120)
  await expect
    .poll(async () => (await frameDiag(page)).geometry.cameraRangeMetres)
    .not.toBe(cameraBefore.cameraRangeMetres)
  const cameraAfterWheel = (await frameDiag(page)).geometry
  const wheelRatio = cameraAfterWheel.cameraRangeMetres / cameraBefore.cameraRangeMetres
  expect(wheelRatio).toBeGreaterThanOrEqual(1.06)
  expect(wheelRatio).toBeLessThanOrEqual(1.1)

  const zoomBar = frame.locator('.sm-zoombar')
  const zoomTrack = frame.locator('.sm-zoom')
  const barBox = await zoomBar.boundingBox()
  const trackBox = await zoomTrack.boundingBox()
  expect(barBox).toBeTruthy()
  expect(trackBox).toBeTruthy()
  await page.mouse.move(barBox!.x + barBox!.width / 2, barBox!.y + barBox!.height / 2)
  await page.mouse.down()
  await page.mouse.move(barBox!.x + barBox!.width / 2, trackBox!.y + trackBox!.height - 4, {
    steps: 12,
  })
  await page.mouse.up()
  await page.waitForTimeout(800)
  const cameraAfterBar = (await frameDiag(page)).geometry
  expect(cameraAfterBar.cameraRangeMetres).toBeGreaterThanOrEqual(cameraAfterBar.cameraRangeBoundsMetres[0])
  expect(cameraAfterBar.cameraRangeMetres).toBeLessThanOrEqual(cameraAfterBar.cameraRangeBoundsMetres[1])
  expect(cameraAfterBar.cameraTargetAlignment).toBeGreaterThanOrEqual(0.999)
  const cameraShot = await page.getByTestId('volume-frame').screenshot()
  expectVolumeContent(
    await analyzeVolumePixels(page, cameraShot),
    `导航缩放后的体渲染 ${JSON.stringify(cameraAfterBar)}`,
    {
    minNonBg: 1200,
    minCoverage: 0.03,
    },
  )
  await page.getByTestId('reset-view').click()

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

  // v0.9.0 V6 Task 7：四个证据标签全部可切换且内容非空；资产身份只在数据溯源
  for (const tab of ['overview', 'slices', 'model'] as const) {
    await page.getByTestId(`ge-tab-${tab}`).click()
    const pane = page.getByTestId(`ge-pane-${tab}`)
    await expect(pane).toBeVisible()
    expect((await pane.innerText()).trim().length).toBeGreaterThan(0)
  }
  await page.getByTestId('ge-tab-provenance').click()
  await expect(page.getByTestId('ge-pane-provenance')).toBeVisible()
  await expect(page.getByTestId('ge-asset-identity')).toContainText('supermap_voxelgrid_netcdf')

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
  await page.getByTestId('ge-tab-overview').click()
  await page.screenshot({ path: path.join(EVIDENCE_DIR, 'v6-workbench-1920x1080.png') })
  writeFileSync(
    path.join(EVIDENCE_DIR, 'v6-workbench-1920x1080.json'),
    `${JSON.stringify({
      result_id: resultId,
      grid_sha256: summary.identity.grid_sha256,
      valid_count: summary.grid.valid_count,
      component_count: summary.components_preview.rows.length,
      ai_status: 'unavailable',
      viewport: VIEWPORT,
      overflow,
      columns,
      volume_height_ratio: volumeRatios.height,
      volume_width_ratio: volumeRatios.width,
      scene_aids_geometry: diag.sceneAidsGeometry,
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

// v0.9.0 V6 Task 7：1440×900 一屏验收（布局不溢出、不裁切、证据窗完整）
test('V6 成果工作台 1440×900：一屏无溢出，工具/研判/证据可用', async ({ page }) => {
  test.setTimeout(420_000)
  const dataDir = isolatedDataDir()
  const seededRaw = execFileSync(
    process.env.PYTHON ?? 'python',
    ['-m', 'geomodeling.preset_cli', 'seed-resistivity', '--data-dir', dataDir],
    { cwd: REPO_ROOT, encoding: 'utf8', timeout: 180_000 },
  )
  const seeded = JSON.parse(seededRaw.trim().split('\n').pop()!) as SeedResult
  const resultId = seeded.official_result.result_id

  const consoleEntries: Array<{ type: string; text: string; location: string }> = []
  page.on('console', (message) => consoleEntries.push({
    type: message.type(),
    text: message.text(),
    location: pathOf(message.location()?.url ?? ''),
  }))
  page.on('pageerror', (error) => consoleEntries.push({
    type: 'pageerror',
    text: String(error),
    location: '',
  }))

  await installLiveProbe(page)
  await page.setViewportSize(VIEWPORT_1440)
  await page.goto(`/#/results/${resultId}`, { waitUntil: 'load', timeout: 60_000 })
  await expect(page.getByTestId('app-global-header')).toBeVisible({ timeout: 60_000 })
  await expect(page.getByTestId('v6-result-summary')).toBeVisible()

  const createAsset = page.getByTestId('create-asset')
  await createAsset.waitFor({ state: 'visible', timeout: 15_000 }).catch(() => undefined)
  if (await createAsset.isVisible().catch(() => false)) {
    await createAsset.click()
  }
  await expect(page.getByTestId('volume-phase')).toHaveText('已渲染', { timeout: 90_000 })

  // 无页面级横/纵溢出
  const overflow = await page.evaluate(() => ({
    documentX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    documentY: document.documentElement.scrollHeight - document.documentElement.clientHeight,
  }))
  expect(overflow.documentX).toBeLessThanOrEqual(1)
  expect(overflow.documentY).toBeLessThanOrEqual(1)

  // 三栏与证据窗仍在视口内（1440 下限：工具 328 / 研判 390 / 中央 ≥560）
  const columns = await page.evaluate(() => {
    const rail = document.querySelector('[data-test="tools-rail"]')?.getBoundingClientRect()
    const scene = document.querySelector('[data-test="result-scene"]')?.getBoundingClientRect()
    const side = document.querySelector('[data-test="result-analysis-side"]')?.getBoundingClientRect()
    return { rail: rail?.width ?? 0, scene: scene?.width ?? 0, side: side?.width ?? 0 }
  })
  expect(columns.rail).toBeGreaterThanOrEqual(300)
  expect(columns.scene).toBeGreaterThanOrEqual(520)
  expect(columns.side).toBeGreaterThanOrEqual(350)
  const dockBox = await page.getByTestId('result-evidence-dock').boundingBox()
  expect(dockBox).toBeTruthy()
  expect(dockBox!.y + dockBox!.height).toBeLessThanOrEqual(VIEWPORT_1440.height + 1)

  mkdirSync(EVIDENCE_DIR, { recursive: true })
  await page.screenshot({ path: path.join(EVIDENCE_DIR, 'v6-workbench-1440x900.png') })

  const benignStatuses = new Set([
    `/api/results/${resultId}/render-assets/netcdf`,
    `/api/results/${resultId}/ai-analysis/latest`,
  ])
  const consoleErrors = consoleEntries.filter(
    (entry) =>
      ['error', 'pageerror'].includes(entry.type) &&
      !(entry.text.includes('Failed to load resource') && benignStatuses.has(entry.location)),
  )
  expect(consoleErrors).toEqual([])
})
