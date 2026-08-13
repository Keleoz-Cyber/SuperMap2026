import { expect, test, type APIRequestContext, type BrowserContext, type Page } from '@playwright/test'
import { execFileSync, spawn, type ChildProcess } from 'node:child_process'
import { createHash, randomUUID } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  analyzeVolumePixels,
  expectVolumeContent,
  installLiveProbe,
  probeMessages,
  setSliceIndex,
  waitFrames,
  waitSliceApplied,
} from './v070RenderGates'

/**
 * v0.9.0 ML 空间预测发布门。
 *
 * 全链只走生产 CLI 与公开 HTTP：两个内置数据源 seed → 创建 RF / 克里金残差
 * 实验 → 空间交叉验证 → 候选物化 → 多字段 NetCDF → 产品成果页 → 真实
 * SuperMap3D Volume + Z 切片。不得直接插数据库或复制旧资产。
 */

const HERE = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(HERE, '../..')
const SDK_PATH = path.join(REPO_ROOT, 'web', 'dist', 'SuperMap3D-2026', 'SuperMap3D.js')
const EVIDENCE_ROOT = path.join(REPO_ROOT, 'docs', 'evidence', 'v0.9.0-ml-spatial-prediction')
const VIEWPORT = { width: 1440, height: 900 }
const RUN_TIMEOUT = 1_800_000
const RENDER_TIMEOUT = 90_000
const CACHE_PORT = Number(process.env.GMP_ML_CACHE_PORT ?? 5291)
const CACHE_BASE = `http://127.0.0.1:${CACHE_PORT}`
const MICRO_CASE_ID = 'builtin-microseismic-vx-1911'
const RHO_CASE_ID = 'resistivity'
const CAPTURE = process.env.GMP_CAPTURE_EVIDENCE === '1'

type MLField = 'prediction' | 'model_dispersion' | 'kriging_baseline' | 'residual_correction'

interface ModelResult {
  caseId: string
  datasetId: string
  experimentId: string
  runId: string
  resultId: string
  algorithm: string
  metrics: Record<string, unknown>
  metadata: Record<string, any>
}

interface FieldAsset {
  field: MLField
  id: string
  source_id: string
  grid_sha256: string
  netcdf_sha256: string
  manifest_url: string
}

function dataDir(): string {
  const value = process.env.GEOMODELING_DATA_DIR
  if (!value) throw new Error('ML live 门要求唯一的 GEOMODELING_DATA_DIR')
  const normalized = value.replace(/\\/g, '/')
  if (normalized.endsWith('var/geomodeling') || normalized.includes('/.runtime/')) {
    throw new Error(`ML live 门不得使用默认或演示运行库：${value}`)
  }
  return value
}

function sha256(file: string): string {
  return createHash('sha256').update(readFileSync(file)).digest('hex')
}

function runId(): string {
  const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\..*/, 'Z')
  return `run-${stamp}-${randomUUID().slice(0, 8)}`
}

const evidenceRunId = runId()
const evidenceDir = path.join(EVIDENCE_ROOT, evidenceRunId)
const evidence: Record<string, any> = {
  run_id: evidenceRunId,
  git_commit: '',
  sdk_sha256: '',
  browser: {},
  environment: {},
  models: {},
  fields: {},
  cache_scenarios: [],
  console: [],
  network_failures: [],
}

function writeEvidence(name: string, body: Record<string, unknown>): void {
  if (!CAPTURE) return
  mkdirSync(evidenceDir, { recursive: true })
  writeFileSync(
    path.join(evidenceDir, name),
    `${JSON.stringify({
      run_id: evidenceRunId,
      git_commit: evidence.git_commit,
      sdk_sha256: evidence.sdk_sha256,
      ...body,
    }, null, 2)}\n`,
    'utf8',
  )
}

async function pollRun(request: APIRequestContext, id: string): Promise<Record<string, any>> {
  const started = Date.now()
  for (;;) {
    const response = await request.get(`/api/runs/${id}`)
    expect(response.ok()).toBe(true)
    const run = await response.json()
    if (['succeeded', 'failed', 'canceled', 'interrupted'].includes(run.status)) return run
    if (Date.now() - started > RUN_TIMEOUT) throw new Error(`运行 ${id} 等待超时`)
    await new Promise((resolve) => setTimeout(resolve, 1_000))
  }
}

async function createModel(
  request: APIRequestContext,
  options: {
    caseId: string
    datasetId: string
    name: string
    algorithm: 'random_forest_spatial' | 'kriging_rf_residual'
    parameters: Record<string, unknown>
    grid: Record<string, unknown>
  },
): Promise<ModelResult> {
  const created = await request.post('/api/experiments', {
    data: {
      case_id: options.caseId,
      name: options.name,
      algorithm: options.algorithm,
      dataset_version_id: options.datasetId,
      search_mode: 'manual',
      parameters: options.parameters,
      validation: { method: 'spatial_kfold', folds: 5, seed: 20260723 },
      grid: options.grid,
      ml_experimental_confirmed: true,
    },
  })
  expect(created.status(), await created.text()).toBe(201)
  const experiment = await created.json()
  const queued = await request.post(`/api/experiments/${experiment.id}/runs`, { data: {} })
  expect(queued.status(), await queued.text()).toBe(201)
  const queuedRun = await queued.json()
  const terminal = await pollRun(request, queuedRun.id)
  expect(terminal.status, JSON.stringify(terminal)).toBe('succeeded')

  const candidatesResponse = await request.get(`/api/experiments/${experiment.id}/candidates`)
  expect(candidatesResponse.ok()).toBe(true)
  const candidates = await candidatesResponse.json()
  expect(candidates.candidates).toHaveLength(1)
  const candidate = candidates.candidates[0]
  expect(candidate.status, JSON.stringify(candidate)).toBe('succeeded')
  for (const key of ['rmse', 'mae', 'r2', 'bias']) {
    expect(Number.isFinite(candidate.metrics[key]), `${options.name} ${key}`).toBe(true)
  }
  expect(candidate.metrics.common_valid_count).toBeGreaterThan(0)

  const materialized = await request.post(`/api/results/${candidate.id}/materialize`, { data: {} })
  expect(materialized.ok(), await materialized.text()).toBe(true)
  const metadata = await materialized.json()
  expect(metadata.algorithm).toBe(options.algorithm)
  expect(metadata.grid_sha256).toMatch(/^[0-9a-f]{64}$/)

  return {
    caseId: options.caseId,
    datasetId: options.datasetId,
    experimentId: experiment.id,
    runId: queuedRun.id,
    resultId: candidate.id,
    algorithm: options.algorithm,
    metrics: candidate.metrics,
    metadata,
  }
}

async function createFieldAsset(
  request: APIRequestContext,
  resultId: string,
  field: MLField,
): Promise<FieldAsset> {
  const suffix = field === 'prediction' ? '' : `?field=${field}`
  const response = await request.post(`/api/results/${resultId}/render-assets/netcdf${suffix}`, {
    data: {},
  })
  expect([200, 201], await response.text()).toContain(response.status())
  const asset = await response.json()
  expect(asset.status).toBe('ready')
  expect(asset.source_kind).toBe('candidate_result')
  expect(asset.source_id).toBe(field === 'prediction' ? resultId : `${resultId}::${field}`)
  expect(asset.grid_sha256).toMatch(/^[0-9a-f]{64}$/)
  expect(asset.netcdf_sha256).toMatch(/^[0-9a-f]{64}$/)
  const manifestResponse = await request.get(asset.manifest_url)
  expect(manifestResponse.ok()).toBe(true)
  const manifest = await manifestResponse.json()
  expect(manifest.source_id).toBe(asset.source_id)
  expect(manifest.grid_sha256).toBe(asset.grid_sha256)
  expect(manifest.netcdf_sha256).toBe(asset.netcdf_sha256)
  return { field, ...asset }
}

function watchErrors(page: Page): void {
  const pathOf = (raw: string) => {
    try { return new URL(raw).pathname } catch { return raw }
  }
  page.on('pageerror', (error) => evidence.console.push({ type: 'pageerror', text: String(error) }))
  page.on('console', (message) => {
    if (message.type() === 'error') {
      evidence.console.push({ type: 'error', text: message.text(), path: pathOf(message.location().url) })
    }
  })
  page.on('requestfailed', (request) => {
    evidence.network_failures.push(`${request.method()} ${pathOf(request.url())} ${request.failure()?.errorText}`)
  })
}

async function gateField(
  page: Page,
  request: APIRequestContext,
  asset: FieldAsset,
  tag: string,
): Promise<Record<string, unknown>> {
  await expect(page.getByTestId('volume-phase')).toHaveText('已渲染', { timeout: RENDER_TIMEOUT })
  const frame = page.frames().find((candidate) => candidate.url().includes('/supermap-volume-frame/'))
  expect(frame).toBeTruthy()
  const errors = (await probeMessages(page)).filter((message) => message.type === 'ERROR')
  expect(errors).toEqual([])
  const shot = () => page.getByTestId('volume-frame').screenshot()
  const volumeShot = await shot()
  const volume = await analyzeVolumePixels(page, volumeShot)
  expectVolumeContent(volume, `${tag} Volume`, { minNonBg: 2_000, minCoverage: 0.15 })
  if (CAPTURE) writeFileSync(path.join(evidenceDir, `${tag}-volume.png`), volumeShot)

  const sliceResponse = await request.get(`/api/render-assets/${asset.id}/slice-analysis?axis=z&index=0`)
  expect(sliceResponse.ok()).toBe(true)
  const sliceBody = await sliceResponse.json()
  const zLength = sliceBody.axes.z.length as number
  const zIndex = Math.max(1, Math.floor(zLength * 0.4))
  await page.getByTestId('mode-slice').click()
  await setSliceIndex(page, zIndex)
  await waitSliceApplied(page, request, frame!, asset.id, 'z', zIndex)
  await waitFrames(frame!, 6)
  const sliceShot = await shot()
  const slice = await analyzeVolumePixels(page, sliceShot)
  // Slice 同时保留包围盒、轴标注和异常点，中央裁剪内会形成独立覆盖物；
  // 仍要求主体占至少 75%，并保留覆盖率/颜色变化门，不能用线框或碎屑通过。
  expectVolumeContent(slice, `${tag} Slice`, {
    minNonBg: 500,
    minCoverage: 0.03,
    minComponentRatio: 0.75,
  })
  if (CAPTURE) writeFileSync(path.join(evidenceDir, `${tag}-slice-z.png`), sliceShot)
  await page.getByTestId('mode-volume').click()
  return { volume, slice, z_index: zIndex }
}

function startServer(runtimeDir: string): ChildProcess {
  return spawn(
    process.env.PYTHON ?? 'python',
    ['-m', 'uvicorn', 'geomodeling.api.app:app', '--host', '127.0.0.1', '--port', String(CACHE_PORT), '--workers', '1'],
    {
      cwd: REPO_ROOT,
      env: {
        ...process.env,
        PYTHONPATH: path.join(REPO_ROOT, 'src'),
        GEOMODELING_DATA_DIR: runtimeDir,
        GEOMODELING_FRONTEND_DIST: path.join(REPO_ROOT, 'web', 'dist'),
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    },
  )
}

async function waitHealth(): Promise<void> {
  const started = Date.now()
  for (;;) {
    try {
      if ((await fetch(`${CACHE_BASE}/api/health`)).ok) return
    } catch { /* server not ready */ }
    if (Date.now() - started > 60_000) throw new Error('缓存场景服务健康检查超时')
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
}

async function stopServer(child: ChildProcess): Promise<void> {
  if (child.exitCode !== null) return
  await new Promise<void>((resolve) => {
    child.once('exit', () => resolve())
    child.kill('SIGTERM')
    setTimeout(() => { child.kill('SIGKILL'); resolve() }, 5_000)
  })
}

async function cacheScenario(page: Page, tag: string): Promise<Record<string, unknown>> {
  await expect(page.getByTestId('volume-phase')).toHaveText('已渲染', { timeout: RENDER_TIMEOUT })
  const shot = await page.getByTestId('volume-frame').screenshot()
  const metrics = await analyzeVolumePixels(page, shot)
  expectVolumeContent(metrics, `${tag} Volume`, { minNonBg: 2_000, minCoverage: 0.15 })
  const frame = page.frames().find((candidate) => candidate.url().includes('/supermap-volume-frame/'))
  expect(frame).toBeTruthy()
  expect((await frame!.evaluate(() => (window as any).__GMP_VOLUME_FRAME__)).phase).toBe('rendered')
  if (CAPTURE) {
    await page.screenshot({ path: path.join(evidenceDir, `${tag}-page.png`) })
    writeFileSync(path.join(evidenceDir, `${tag}-iframe.png`), shot)
  }
  return metrics
}

test.use({ launchOptions: { args: ['--use-angle=gl'] } })

test.describe('v0.9.0 ML 空间预测真实数据与 SuperMap3D 发布门', () => {
  test.describe.configure({ mode: 'serial' })
  let rhoRF: ModelResult
  let microRF: ModelResult
  let rhoResidual: ModelResult
  let residualAssets: Record<MLField, FieldAsset>

  test.beforeAll(() => {
    test.setTimeout(1_200_000)
    const runtimeDir = dataDir()
    for (const command of ['seed-resistivity', 'seed-microseismic']) {
      execFileSync(process.env.PYTHON ?? 'python', ['-m', 'geomodeling.preset_cli', command, '--data-dir', runtimeDir], {
        cwd: REPO_ROOT,
        encoding: 'utf8',
        timeout: 900_000,
      })
    }
    evidence.git_commit = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: REPO_ROOT, encoding: 'utf8' }).trim()
    evidence.sdk_sha256 = sha256(SDK_PATH)
    evidence.environment = { platform: `${process.platform}/${process.arch}`, node: process.version }
    if (CAPTURE) mkdirSync(evidenceDir, { recursive: true })
  })

  test('真实电阻率与微震模型：空间验证、诚实指标和多字段物化', async ({ request }) => {
    test.setTimeout(RUN_TIMEOUT)
    const rhoWorkspace = await (await request.get(`/api/cases/${RHO_CASE_ID}/workspace`)).json()
    const microWorkspace = await (await request.get(`/api/cases/${MICRO_CASE_ID}/workspace`)).json()
    const rhoDataset = rhoWorkspace.primary_dataset.id as string
    const microDataset = microWorkspace.primary_dataset.id as string

    const rhoGrid = { bounds: [[-160, -40], [220, 660], [-833.0047143, -19.5999]], resolution: [20, 20, 20], max_cells: 1_000_000 }
    const microGrid = { bounds: [[-750, 960], [-995, 1310], [-4086.538, -37.5]], resolution: [50, 50, 50], max_cells: 1_000_000 }
    const rf = { n_estimators: 80, max_depth: 18, min_samples_leaf: 2, max_features: 0.8, random_state: 20260813 }

    rhoRF = await createModel(request, { caseId: RHO_CASE_ID, datasetId: rhoDataset, name: '电阻率随机森林空间预测', algorithm: 'random_forest_spatial', parameters: rf, grid: rhoGrid })
    microRF = await createModel(request, { caseId: MICRO_CASE_ID, datasetId: microDataset, name: '微震随机森林空间预测', algorithm: 'random_forest_spatial', parameters: rf, grid: microGrid })
    rhoResidual = await createModel(request, {
      caseId: RHO_CASE_ID,
      datasetId: rhoDataset,
      name: '电阻率克里金残差校正',
      algorithm: 'kriging_rf_residual',
      parameters: {
        kriging: { variogram_model: 'exponential', neighbor_count: 24 },
        random_forest: rf,
        inner_folds: 3,
        inner_seed: 20260813,
      },
      grid: rhoGrid,
    })

    expect(rhoRF.metadata.ml_fields).toHaveProperty('model_dispersion')
    expect(microRF.metadata.ml_fields).toHaveProperty('model_dispersion')
    expect(Object.keys(rhoResidual.metadata.ml_fields).sort()).toEqual(['kriging_baseline', 'model_dispersion', 'residual_correction'])

    const summaryResponse = await request.get(`/api/results/${rhoResidual.resultId}/analysis-summary`)
    expect(summaryResponse.ok()).toBe(true)
    const summary = await summaryResponse.json()
    expect(summary.machine_learning.algorithm).toBe('kriging_rf_residual')
    expect(summary.machine_learning.dispersion_semantics).toBe('model_dispersion_reference')
    expect(typeof summary.machine_learning.improved_over_kriging).toBe('boolean')
    expect(summary.machine_learning.baseline.common_valid_count).toBe(rhoResidual.metrics.common_valid_count)

    residualAssets = {} as Record<MLField, FieldAsset>
    for (const field of ['prediction', 'model_dispersion', 'kriging_baseline', 'residual_correction'] as MLField[]) {
      residualAssets[field] = await createFieldAsset(request, rhoResidual.resultId, field)
    }
    evidence.models = { resistivity_rf: rhoRF, microseismic_rf: microRF, resistivity_residual: rhoResidual, residual_evidence: summary.machine_learning, microseismic_group_limit: 22 }
    evidence.fields = residualAssets
  })

  test('真实成果工作台：四字段 Volume 与 Z 切片均有有效内容', async ({ page, request, browser }) => {
    test.setTimeout(900_000)
    await installLiveProbe(page)
    watchErrors(page)
    await page.setViewportSize(VIEWPORT)
    await page.goto(`/#/results/${rhoResidual.resultId}`, { waitUntil: 'load', timeout: 60_000 })
    await expect(page.getByTestId('ml-field-selector')).toBeVisible({ timeout: 60_000 })
    evidence.browser = { name: 'chromium', version: browser.version(), viewport: VIEWPORT, dpr: await page.evaluate(() => devicePixelRatio) }

    const reports: Record<string, unknown> = {}
    for (const field of ['prediction', 'model_dispersion', 'kriging_baseline', 'residual_correction'] as MLField[]) {
      if (field !== 'prediction') {
        await page.getByTestId(`ml-field-${field}`).click()
      }
      const label = {
        prediction: '预测结果',
        model_dispersion: '模型离散度',
        kriging_baseline: '克里金基线',
        residual_correction: '残差校正',
      }[field]
      if (field === 'prediction') {
        await expect(page.getByTestId('ml-field-selector')).toContainText(label)
        await expect(page.getByTestId('active-ml-field-note')).toHaveCount(0)
      } else {
        await expect(page.getByTestId('active-ml-field-note')).toContainText(label)
      }
      reports[field] = await gateField(page, request, residualAssets[field], `rho-${field.replaceAll('_', '-')}`)
    }
    expect(evidence.console).toEqual([])
    expect(evidence.network_failures).toEqual([])
    evidence.field_pixel_gates = reports
  })

  test('ML 资产 fresh、刷新、服务重启与 warm-cache 升级均可恢复', async ({ playwright }) => {
    test.setTimeout(600_000)
    let server: ChildProcess | null = startServer(dataDir())
    let context: BrowserContext | null = null
    try {
      await waitHealth()
      context = await playwright.chromium.launchPersistentContext(path.join(dataDir(), 'ml-cache-profile'), {
        headless: true,
        args: ['--use-angle=gl'],
        viewport: VIEWPORT,
      })
      const page = await context.newPage()
      await page.goto(`${CACHE_BASE}/#/results/${rhoResidual.resultId}`, { waitUntil: 'load' })
      evidence.cache_scenarios.push({ scenario: 'fresh', metrics: await cacheScenario(page, 'cache-1-fresh') })

      await page.reload({ waitUntil: 'load' })
      evidence.cache_scenarios.push({ scenario: 'reload', metrics: await cacheScenario(page, 'cache-2-reload') })

      await stopServer(server)
      server = startServer(dataDir())
      await waitHealth()
      await page.reload({ waitUntil: 'load' })
      evidence.cache_scenarios.push({ scenario: 'server-restart', metrics: await cacheScenario(page, 'cache-3-server-restart') })

      await page.route('**/supermap-volume-frame/app.js', (route) => route.fulfill({
        status: 200,
        contentType: 'application/javascript',
        headers: { 'Cache-Control': 'public, max-age=86400' },
        body: `window.parent.postMessage({protocol:'gmp-supermap-volume/v1',type:'FRAME_READY'},window.location.origin)`,
      }))
      await page.route('**/ml-cache-planter.html', (route) => route.fulfill({
        status: 200,
        contentType: 'text/html',
        body: '<script src="/supermap-volume-frame/app.js"></script>',
      }))
      await page.goto(`${CACHE_BASE}/ml-cache-planter.html`, { waitUntil: 'load' })
      await page.unroute('**/supermap-volume-frame/app.js')
      await page.unroute('**/ml-cache-planter.html')
      await page.goto(`${CACHE_BASE}/#/results/${rhoResidual.resultId}`, { waitUntil: 'load' })
      const metrics = await cacheScenario(page, 'cache-4-warm-upgrade')
      const frame = page.frames().find((candidate) => candidate.url().includes('/supermap-volume-frame/'))!
      const entry = await frame.evaluate(() => performance.getEntriesByType('resource').find((item) => item.name.includes('app.js'))?.name ?? '')
      expect(new URL(entry).searchParams.get('v')).toMatch(/^[0-9a-f]{16}$/)
      evidence.cache_scenarios.push({ scenario: 'warm-cache-upgrade', app_js: entry, metrics })
    } finally {
      if (context) await context.close()
      if (server) await stopServer(server)
    }
  })

  test.afterAll(() => {
    writeEvidence('identity.json', { models: evidence.models, fields: evidence.fields })
    writeEvidence('pixel-stats.json', { field_pixel_gates: evidence.field_pixel_gates })
    writeEvidence('cache-scenarios.json', { scenarios: evidence.cache_scenarios })
    writeEvidence('environment.json', { browser: evidence.browser, environment: evidence.environment })
    writeEvidence('console-network.json', { console: evidence.console, network_failures: evidence.network_failures })
  })
})
