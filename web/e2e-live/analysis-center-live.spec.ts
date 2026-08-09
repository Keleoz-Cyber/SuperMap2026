import { expect, test, type Locator, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { createHash, randomUUID } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { analyzeVolumePixels, countDiff, type VolumePixelMetrics } from './v070RenderGates'

/**
 * v0.8.0 第二批 Task 9：统计与空间分析中心真实数据 live 门（设计 §9 真实
 * 视觉验收；微震 + 电阻率双预置，全程不用 mock——真实 FastAPI + 真实前端
 * 产物 + 真实 ECharts 渲染）。
 *
 * 真实链路：全新隔离 GEOMODELING_DATA_DIR → preset_cli 双 seed（微震只读
 * CSV 预置 seed-microseismic；电阻率 seed-resistivity——v0.8.0 第三批起
 * --source 缺省为项目内 example_data/地下电阻率节点_标准化.csv 字节冻结
 * 内置源，无外部私有源依赖，无需任何环境变量）→
 * workspace API 取两个案例的 primary_dataset.id 与官方成果 result_id →
 * GET analysis-summary 合同门（analysis_profile / quality.row_count /
 * 统计全部有限 / 专属模块 status=ok 且载荷带计算方法与阈值来源 /
 * provenance.source_sha256 与真实源 SHA 一致 / 绝无绝对路径字样）→
 * 产品页 1440×900 分析中心视觉门（profile 徽标 / 质量徽标 / 空间异常图
 * canvas 非空且非近单色——中央 50% 区域像素判据与 v070RenderGates 的
 * analyzeVolumePixels 同口径，但不要求体渲染；黑屏 / 近单色 / 空图一律
 * 判失败）→ 交互门（点击 XY 分箱 → 官方成果页，URL 含 /results/ 且带
 * axis/x_range/y_range/dataset 查询参数；剖面统计轴 X→Y→Z 切换的截图
 * 差分超 max(200, noise*3+50) 噪声阈值；模型对比点击候选 → 成果页）→
 * 390×844 移动视口无页面级横向溢出且图表非空 → 网络/控制台错误门。
 *
 * GEOMODELING_DATA_DIR 缺失时 beforeAll 直接失败，不静默跳过。
 *
 * 证据写入 docs/evidence/v0.8.0-statistics-analysis/<run-id>/（仅真实运行
 * 时创建；提交前按目录 README 扫描绝对路径/凭据/私有源内容）。本门不加载
 * SDK 体渲染帧，SDK 身份以 web/dist 包 SHA-256 承载。
 */

const HERE = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(HERE, '../..')
const SDK_DIST_PATH = path.join(REPO_ROOT, 'web', 'dist', 'SuperMap3D-2026', 'SuperMap3D.js')
const EVIDENCE_ROOT = path.join(REPO_ROOT, 'docs', 'evidence', 'v0.8.0-statistics-analysis')
const VIEWPORT = { width: 1440, height: 900 }
const MOBILE_VIEWPORT = { width: 390, height: 844 }
const MICRO_CASE_ID = 'builtin-microseismic-vx-1911'
const RHO_CASE_ID = 'resistivity'
// 入库公开事实：电阻率标准化散点 17,549 行（与 resistivity-scattered-live 同一
// 合同）；微震预置 1,911 行（config/presets/microseismic-official-baseline.json）
const RHO_ROW_COUNT = 17_549
const MICRO_ROW_COUNT = 1_911
// 成果页纯查询 404 白名单：渲染资产未显式创建前的既有产品语义
const BENIGN_4XX = [/^\/api\/results\/[^/]+\/render-assets\/netcdf$/]

function assertIsolatedDataDir(): string {
  const dir = process.env.GEOMODELING_DATA_DIR
  if (!dir) {
    throw new Error('Live E2E 要求调用环境提供唯一的 GEOMODELING_DATA_DIR')
  }
  const normalized = dir.replace(/\\/g, '/')
  if (normalized.endsWith('var/geomodeling') || normalized.endsWith('var/demo_v041')) {
    throw new Error(`Live E2E 不得使用默认/演示数据目录：${dir}`)
  }
  return dir
}

function sha256File(file: string): string {
  return createHash('sha256').update(readFileSync(file)).digest('hex')
}

function isoRunId(): string {
  const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\..*/, 'Z')
  return `run-${stamp}-${randomUUID().slice(0, 8)}`
}

/** 预置 CLI（唯一生产入口；幂等；PYTHONPATH 钉住仓库 src） */
function runPresetCli(args: string[]): any {
  const stdout = execFileSync(
    process.env.PYTHON ?? 'python',
    ['-m', 'geomodeling.preset_cli', ...args],
    {
      cwd: REPO_ROOT,
      encoding: 'utf8',
      env: { ...process.env, PYTHONPATH: path.join(REPO_ROOT, 'src') },
      timeout: 600_000,
    },
  )
  return JSON.parse(stdout.trim().split('\n').pop()!)
}

// ---------------------------------------------------------------------------
// 证据聚合
// ---------------------------------------------------------------------------

const runId = isoRunId()
const evidenceDir = path.join(EVIDENCE_ROOT, runId)
let gitCommit = ''
let sdkSha256 = ''
let browserVersion = ''
let gpuRenderer: string | null = null
let dpr: number | null = null

interface CaseEvidence {
  seed: Record<string, unknown>
  identity: Record<string, unknown>
  api: Record<string, unknown>
  pixelStats: Record<string, unknown>
  interactions: Record<string, unknown>
  timings: Record<string, unknown>
  network: { method: string; path: string; status: number }[]
  networkFailures: string[]
  console: { type: string; text: string; location: string }[]
}

function emptyCaseEvidence(): CaseEvidence {
  return {
    seed: {},
    identity: {},
    api: {},
    pixelStats: {},
    interactions: {},
    timings: {},
    network: [],
    networkFailures: [],
    console: [],
  }
}

const cases: Record<'resistivity' | 'microseismic', CaseEvidence> = {
  resistivity: emptyCaseEvidence(),
  microseismic: emptyCaseEvidence(),
}

function evidencePath(name: string): string {
  return path.join(evidenceDir, name)
}

function commonEnvelope() {
  return {
    run_id: runId,
    git_commit: gitCommit,
    sdk_sha256: sdkSha256,
    sdk_version: null, // 本门不加载 SDK 体渲染帧；SDK 身份由 dist 包 SHA-256 承载
    browser: { name: 'chromium', version: browserVersion },
    gpu_renderer: gpuRenderer,
    viewport: VIEWPORT,
    mobile_viewport: MOBILE_VIEWPORT,
    device_pixel_ratio: dpr,
    results: {
      resistivity: {
        case_id: RHO_CASE_ID,
        dataset_version_id: cases.resistivity.identity['dataset_version_id'] ?? null,
        official_result_id: cases.resistivity.identity['official_result_id'] ?? null,
        source_sha256: cases.resistivity.identity['source_sha256'] ?? null,
        analysis_profile: cases.resistivity.identity['analysis_profile'] ?? null,
      },
      microseismic: {
        case_id: MICRO_CASE_ID,
        dataset_version_id: cases.microseismic.identity['dataset_version_id'] ?? null,
        official_result_id: cases.microseismic.identity['official_result_id'] ?? null,
        source_sha256: cases.microseismic.identity['source_sha256'] ?? null,
        analysis_profile: cases.microseismic.identity['analysis_profile'] ?? null,
      },
    },
  }
}

function writeEvidenceJson(name: string, body: Record<string, unknown>) {
  // 失败运行同样落证据：写入前确保目录存在（beforeAll 失败时目录可能尚未建）
  mkdirSync(evidenceDir, { recursive: true })
  writeFileSync(
    evidencePath(name),
    `${JSON.stringify({ ...commonEnvelope(), ...body }, null, 2)}\n`,
    'utf8',
  )
}

// ---------------------------------------------------------------------------
// API 合同断言辅助
// ---------------------------------------------------------------------------

interface AnalysisModuleLike {
  module_id: string
  status: string
  payload: any
  message?: string | null
}

function moduleOf(summary: any, moduleId: string): AnalysisModuleLike {
  const mod = (summary.modules ?? []).find((m: any) => m.module_id === moduleId)
  expect(mod, `缺少分析模块 ${moduleId}`).toBeTruthy()
  return mod as AnalysisModuleLike
}

/** 基础统计与分位数全部有限（NumericSummary/QuantileSummary 逐字段） */
function expectFiniteStatistics(statistics: any, what: string): void {
  expect(statistics, `${what}：statistics 必须存在`).toBeTruthy()
  for (const key of ['count', 'min', 'max', 'mean', 'median', 'std'] as const) {
    expect(
      Number.isFinite(statistics?.[key]),
      `${what}：statistics.${key} 必须为有限数`,
    ).toBe(true)
  }
  for (const key of ['p05', 'p25', 'p50', 'p75', 'p95'] as const) {
    expect(
      Number.isFinite(statistics?.quantiles?.[key]),
      `${what}：quantiles.${key} 必须为有限数`,
    ).toBe(true)
  }
}

/** 分位阈值来源（source/method）必须随载荷出站 */
function expectThresholdSource(payload: any, what: string): void {
  expect(
    typeof payload?.thresholds?.source === 'string' && payload.thresholds.source.length > 0,
    `${what}：阈值来源 thresholds.source 缺失`,
  ).toBe(true)
  expect(
    typeof payload?.thresholds?.method === 'string' && payload.thresholds.method.length > 0,
    `${what}：阈值口径 thresholds.method 缺失`,
  ).toBe(true)
}

/** 响应序列化绝无本机绝对路径与内部存储键字样 */
function expectNoAbsolutePath(payload: any, what: string): void {
  const serialized = JSON.stringify(payload)
  expect(serialized, `${what}：响应不得含本机绝对路径`).not.toMatch(/[A-Za-z]:[\\/]/)
  expect(serialized, `${what}：响应不得泄露 standardized_path`).not.toContain(
    'standardized_path',
  )
}

/** 证据裁剪：合同相关字段（不含 32×32 分箱明细） */
function trimSummary(summary: any): Record<string, unknown> {
  const comparison = (summary.modules ?? []).find(
    (m: any) => m.module_id === 'model_comparison',
  )
  const candidates = Array.isArray(comparison?.payload?.candidates)
    ? comparison.payload.candidates.map((c: any) => ({
        result_id: c.result_id,
        algorithm: c.algorithm,
        metrics: c.metrics,
        materialized: c.materialized,
        formal_selection: c.formal_selection,
      }))
    : []
  return {
    dataset_id: summary.dataset_id,
    case_id: summary.case_id,
    analysis_profile: summary.analysis_profile,
    profile_version: summary.profile_version,
    variable: summary.variable,
    quality: summary.quality,
    statistics: summary.statistics,
    modules: (summary.modules ?? []).map((m: any) => ({
      module_id: m.module_id,
      status: m.status,
      method: m.payload?.method ?? null,
      source_fields: m.payload?.source_fields ?? null,
      thresholds: m.payload?.thresholds ?? null,
      message: m.message ?? null,
    })),
    candidates,
    provenance: summary.provenance,
  }
}

// ---------------------------------------------------------------------------
// 页面观察与视觉判据辅助
// ---------------------------------------------------------------------------

/** 网络/控制台观察（证据 + 健康门数据源） */
function installObservers(page: Page, ev: CaseEvidence): void {
  const pathOf = (url: string) => {
    try {
      return new URL(url).pathname
    } catch {
      return url
    }
  }
  page.on('console', (m) =>
    ev.console.push({
      type: m.type(),
      text: m.text().slice(0, 400),
      location: pathOf(m.location()?.url ?? ''),
    }),
  )
  page.on('pageerror', (e) =>
    ev.console.push({ type: 'pageerror', text: String(e).slice(0, 400), location: '' }),
  )
  page.on('requestfailed', (r) => {
    // 导航式下载（location.assign → attachment）被浏览器以 ERR_ABORTED 中止属正常下载语义
    const p = pathOf(r.url())
    if (p.startsWith('/api/exports/') && r.failure()?.errorText === 'net::ERR_ABORTED') return
    ev.networkFailures.push(`${r.method()} ${p} ${r.failure()?.errorText}`)
  })
  page.on('response', (r) => {
    const p = pathOf(r.url())
    ev.network.push({ method: r.request().method(), path: p, status: r.status() })
    if (r.status() >= 400 && !BENIGN_4XX.some((re) => re.test(p))) {
      ev.networkFailures.push(`${r.status()} ${r.request().method()} ${p}`)
    }
  })
}

/** 全局健康门：任何非白名单 4xx/5xx、pageerror、console error 均为零 */
function expectHealthy(ev: CaseEvidence, what: string): void {
  expect(ev.networkFailures, `${what}：存在非白名单网络失败`).toEqual([])
  const consoleErrors = ev.console.filter(
    (c) =>
      ['pageerror', 'error'].includes(c.type) &&
      !(c.text.includes('Failed to load resource') && BENIGN_4XX.some((re) => re.test(c.location))),
  )
  expect(consoleErrors, `${what}：存在控制台/页面错误`).toEqual([])
}

/** canvas 抽样像素 alpha 非零计数（ECharts 真实绘制判据，与 Mock E2E 同思路） */
async function sampleCanvasPainted(host: Locator): Promise<number> {
  const canvas = host.locator('canvas').first()
  return canvas.evaluate((node) => {
    const c = node as HTMLCanvasElement
    const ctx = c.getContext('2d')
    if (!ctx || c.width === 0 || c.height === 0) return 0
    const data = ctx.getImageData(0, 0, c.width, c.height).data
    let painted = 0
    for (let i = 3; i < data.length; i += 400) {
      if (data[i] !== 0) painted += 1
    }
    return painted
  })
}

async function expectCanvasPainted(host: Locator): Promise<void> {
  await expect(host.locator('canvas').first()).toBeVisible()
  await expect.poll(() => sampleCanvasPainted(host)).toBeGreaterThan(5)
}

/**
 * 图表截图内容判据：中央 50% 区域（analyzeVolumePixels 同口径）非空且非近
 * 单色。黑屏（非背景数枯竭）与近单色/空图（颜色标准差 < 5）一律判失败。
 */
async function expectChartContent(
  page: Page,
  shot: Buffer,
  what: string,
): Promise<VolumePixelMetrics> {
  const metrics = await analyzeVolumePixels(page, shot)
  expect(metrics.nonBg, `${what}：中央区域接近全黑（黑屏/空图）`).toBeGreaterThan(1000)
  expect(
    metrics.colorStd,
    `${what}：中央区域近单色（颜色标准差不足）`,
  ).toBeGreaterThanOrEqual(5)
  return metrics
}

/** 从案例工作台经统一入口进入分析中心并等待摘要就绪 */
async function enterAnalysisCenter(
  page: Page,
  caseId: string,
  datasetId: string,
  headerText: string,
): Promise<void> {
  await page.goto(`/#/cases/${caseId}`, { waitUntil: 'load', timeout: 60_000 })
  await expect(page.getByTestId('case-workspace-header')).toContainText(headerText, {
    timeout: 60_000,
  })
  await page.getByTestId('analysis-center-entry').click()
  await expect(page).toHaveURL(new RegExp(`#\\/datasets\\/${datasetId}\\/analysis`))
  await expect(page.getByTestId('analysis-profile-badge')).toBeVisible({ timeout: 60_000 })
}

// ---------------------------------------------------------------------------
// 测试
// ---------------------------------------------------------------------------

// 与 v0.6.1/v0.7.0 各 live 门一致：真实 GPU（--use-angle=gl），SwiftShader 下时序不可靠。
test.use({ launchOptions: { args: ['--use-angle=gl'] } })

test.describe('v0.8.0 第二批：统计与空间分析中心真实数据 live 门', () => {
  test.describe.configure({ mode: 'serial' })

  test.beforeAll(async ({ request }) => {
    const dataDir = assertIsolatedDataDir()
    // 双预置 seed（唯一生产入口；幂等；电阻率 --source 缺省为项目内
    // example_data 内置源；微震为只读受控 CSV 预置）
    const microSeed = runPresetCli(['seed-microseismic', '--data-dir', dataDir])
    const rhoSeed = runPresetCli(['seed-resistivity', '--data-dir', dataDir])
    cases.microseismic.seed = {
      case_id: microSeed.case_id,
      workspace_kind: microSeed.workspace_kind ?? null,
      dataset_version_id: microSeed.dataset_version_id,
      experiment_id: microSeed.experiment_id,
      run_id: microSeed.run_id,
      official_result_id: microSeed.official_result?.result_id,
      official_url: microSeed.official_result?.url ?? null,
      materialized: microSeed.official_result?.materialized ?? null,
      source_sha256: microSeed.source_sha256,
      baseline_sha256: microSeed.baseline_sha256 ?? null,
    }
    cases.resistivity.seed = {
      case_id: rhoSeed.case_id,
      workspace_kind: rhoSeed.workspace_kind ?? null,
      dataset_version_id: rhoSeed.dataset_version_id,
      experiment_id: rhoSeed.experiment_id,
      run_id: rhoSeed.run_id,
      official_result_id: rhoSeed.official_result?.result_id,
      official_url: rhoSeed.official_result?.url ?? null,
      materialized: rhoSeed.official_result?.materialized ?? null,
      source_sha256: rhoSeed.source_sha256,
      baseline_sha256: rhoSeed.baseline_sha256 ?? null,
    }
    gitCommit = execFileSync('git', ['rev-parse', 'HEAD'], {
      cwd: REPO_ROOT,
      encoding: 'utf8',
    }).trim()
    sdkSha256 = sha256File(SDK_DIST_PATH)

    // workspace API 身份链：两个案例的 primary_dataset.id 与官方成果 result_id，
    // 并与 seed 输出互证（行数为入库公开合同）
    const expectedRows: Record<'microseismic' | 'resistivity', number> = {
      microseismic: MICRO_ROW_COUNT,
      resistivity: RHO_ROW_COUNT,
    }
    for (const [key, caseId] of [
      ['microseismic', MICRO_CASE_ID],
      ['resistivity', RHO_CASE_ID],
    ] as const) {
      const wsResp = await request.get(`/api/cases/${caseId}/workspace`)
      expect(wsResp.ok(), `${caseId} workspace 必须可用`).toBe(true)
      const workspace = await wsResp.json()
      expect(workspace.workspace_kind).toBe('builtin_preset')
      expect(workspace.primary_dataset?.status).toBe('validated')
      expect(workspace.primary_dataset?.profile?.row_count).toBe(expectedRows[key])
      expect(workspace.official_result?.materialized).toBe(true)
      const datasetVersionId = String(workspace.primary_dataset.id)
      const officialResultId = String(workspace.official_result.result_id)
      expect(datasetVersionId).toBe(String(cases[key].seed['dataset_version_id']))
      expect(officialResultId).toBe(String(cases[key].seed['official_result_id']))
      cases[key].identity = {
        ...cases[key].identity,
        case_id: caseId,
        dataset_version_id: datasetVersionId,
        official_result_id: officialResultId,
        row_count: expectedRows[key],
      }
    }
    mkdirSync(evidenceDir, { recursive: true })
  })

  test('电阻率分析中心：API 合同 → 桌面视觉门 → XY 分箱/剖面轴/模型对比交互 → 移动视口', async ({
    page,
    request,
    browser,
  }) => {
    test.setTimeout(600_000)
    const t0 = Date.now()
    browserVersion = browser.version()
    const ev = cases.resistivity
    const datasetId = String(ev.identity['dataset_version_id'])
    const officialResultId = String(ev.identity['official_result_id'])

    // --- API 门：analysis-summary 合同 ---------------------------------------
    const summaryStart = Date.now()
    const summaryResp = await request.get(`/api/datasets/${datasetId}/analysis-summary`)
    expect(summaryResp.ok()).toBe(true)
    const summary = await summaryResp.json()
    const summaryMs = Date.now() - summaryStart

    expect(summary.dataset_id).toBe(datasetId)
    expect(summary.case_id).toBe(RHO_CASE_ID)
    expect(summary.analysis_profile).toBe('resistivity')
    expect(summary.variable.name).toBe('RHO')
    expect(summary.quality.row_count).toBe(RHO_ROW_COUNT)
    expectFiniteStatistics(summary.statistics, '电阻率')

    const distribution = moduleOf(summary, 'distribution')
    expect(distribution.status).toBe('ok')
    expect(distribution.payload.method).toBeTruthy()
    expect(distribution.payload.source_fields?.value).toBe('RHO')
    // Task 6：log10 分箱（仅严格正值有限值）与排除计数随载荷出站
    const log10 = distribution.payload.log10
    expect(log10?.method, 'log10 分箱计算方法缺失').toBeTruthy()
    expect(log10?.bin_count, 'log10 分箱必须非空').toBeGreaterThan(0)
    expect(Array.isArray(log10?.bins)).toBe(true)
    expect(log10?.excluded_non_positive_count).toBeGreaterThanOrEqual(0)

    const depthSlices = moduleOf(summary, 'depth_slices')
    expect(depthSlices.status).toBe('ok')
    expect(depthSlices.payload.method).toBeTruthy()
    expect(depthSlices.payload.source_fields?.z).toBeTruthy()
    expectThresholdSource(depthSlices.payload, '电阻率 depth_slices')

    const anomaly = moduleOf(summary, 'spatial_anomaly')
    expect(anomaly.status).toBe('ok')
    expect(anomaly.payload.method).toBeTruthy()
    expectThresholdSource(anomaly.payload, '电阻率 spatial_anomaly')
    expect(anomaly.payload.bins.length, '空间异常分箱必须非空').toBeGreaterThan(0)

    const profileSlices = moduleOf(summary, 'profile_slices')
    expect(profileSlices.status).toBe('ok')
    expect(profileSlices.payload.axes.map((a: any) => a.axis)).toEqual(['x', 'y', 'z'])

    const comparison = moduleOf(summary, 'model_comparison')
    expect(comparison.status).toBe('ok')
    const candidates = comparison.payload.candidates as any[]
    expect(candidates.length, '模型对比必须含既有候选').toBeGreaterThanOrEqual(1)
    const official = candidates.find((c) => c.result_id === officialResultId)
    expect(official, '官方普通克里金候选缺失').toBeTruthy()
    expect(official.algorithm).toBe('ordinary_kriging')
    expect(official.materialized).toBe(true)
    expect(official.formal_selection).toBe(true)

    expect(summary.provenance.source_sha256).toBe(String(ev.seed['source_sha256']))
    expect(String(summary.provenance.calculation_version)).toMatch(/^analysis\./)
    expectNoAbsolutePath(summary, '电阻率 analysis-summary')

    ev.api = trimSummary(summary)
    ev.identity = {
      ...ev.identity,
      analysis_profile: summary.analysis_profile,
      calculation_version: summary.provenance.calculation_version,
      dataset_version: summary.provenance.dataset_version,
      source_sha256: summary.provenance.source_sha256,
    }

    // --- 页面门：1440×900 桌面分析中心 ----------------------------------------
    installObservers(page, ev)
    await page.setViewportSize(VIEWPORT)
    const enterStart = Date.now()
    await enterAnalysisCenter(page, RHO_CASE_ID, datasetId, '地下电阻率')
    const enterMs = Date.now() - enterStart

    await expect(page.getByTestId('analysis-profile-badge')).toContainText('电阻率')
    const qualityBadge = page.getByTestId('analysis-quality-badge')
    await expect(qualityBadge).toBeVisible()
    if (summary.quality.invalid_count === 0) {
      await expect(qualityBadge).toContainText('数据全部有效')
    }
    await expect(qualityBadge).toContainText('行')
    await expect(page.getByTestId('analysis-identity')).toContainText(datasetId)
    await expect(page.getByTestId('analysis-identity')).toContainText('计算版本')
    await expect(page.getByTestId('analysis-variable')).toContainText('RHO')

    // GPU/渲染环境（证据封套；本门不加载 SDK 帧）
    gpuRenderer = await page.evaluate(() => {
      const canvas = document.createElement('canvas')
      const gl = canvas.getContext('webgl2')
      if (!gl) return 'webgl2-unavailable'
      const ext = gl.getExtension('WEBGL_debug_renderer_info')
      const raw = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER)
      gl.getExtension('WEBGL_lose_context')?.loseContext()
      return String(raw)
    })
    dpr = await page.evaluate(() => window.devicePixelRatio)

    // 默认主区 = 高/低阻空间异常热力图：图例 + canvas 非空 + 中央区域非近单色
    const spatialPanel = page.getByTestId('spatial-feature-panel')
    await expect(spatialPanel).toBeVisible()
    await expect(spatialPanel.locator('h3')).toContainText('高/低阻区域')
    const legend = page.getByTestId('spatial-anomaly-legend')
    await expect(legend).toContainText('高阻区域')
    await expect(legend).toContainText('低阻区域')
    await expect(legend).toContainText('阈值来源')
    const spatialChart = page.getByTestId('spatial-chart')
    await expectCanvasPainted(spatialChart)
    const spatialPainted = await sampleCanvasPainted(spatialChart)
    const spatialShot = await spatialChart.screenshot()
    const spatialMetrics = await expectChartContent(page, spatialShot, '电阻率空间异常图')
    writeFileSync(evidencePath('rho-spatial-chart.png'), spatialShot)
    await page.screenshot({ path: evidencePath('rho-desktop-analysis.png') })

    // --- 交互 1：点击 XY 分箱 → 官方成果页（axis/x_range/y_range/dataset） ----
    const box = await spatialChart.boundingBox()
    expect(box).not.toBeNull()
    await page.mouse.click(box!.x + box!.width / 2, box!.y + box!.height / 2)
    await expect(page).toHaveURL(new RegExp(`#\\/results\\/${officialResultId}\\?`))
    const selectedUrl = page.url()
    expect(selectedUrl).toContain('axis=xy')
    expect(selectedUrl).toMatch(/x_range=[^&]+/)
    expect(selectedUrl).toMatch(/y_range=[^&]+/)
    expect(selectedUrl).toContain(`dataset=${datasetId}`)
    const hash = new URL(selectedUrl).hash
    const query = new URLSearchParams(hash.slice(hash.indexOf('?') + 1))
    ev.interactions['xy_selection'] = {
      result_id: officialResultId,
      axis: query.get('axis'),
      x_range: query.get('x_range'),
      y_range: query.get('y_range'),
      dataset: query.get('dataset'),
    }
    await page.screenshot({ path: evidencePath('rho-result-xy-selection.png') })
    await page.goBack()
    await expect(page.getByTestId('analysis-profile-badge')).toContainText('电阻率', {
      timeout: 60_000,
    })
    await expect(page.getByTestId('spatial-feature-panel')).toBeVisible({ timeout: 60_000 })

    // --- 交互 2：剖面统计轴 X→Y→Z 切换（截图差分超噪声阈值） ------------------
    await page.getByTestId('module-nav-item-profile_slices').click()
    await expect(page.getByTestId('profile-analysis-panel')).toBeVisible()
    const profileChart = page.getByTestId('profile-chart')
    await expectCanvasPainted(profileChart)
    const profilePainted = await sampleCanvasPainted(profileChart)
    await expect(page.getByTestId('profile-summary')).toContainText('X 轴剖面')
    // ECharts 入场动画（默认 1000ms）落定后取基线与静帧噪声
    await page.waitForTimeout(1600)
    const shotX = await profileChart.screenshot()
    await page.waitForTimeout(400)
    const shotX2 = await profileChart.screenshot()
    const noise = await countDiff(page, shotX, shotX2)
    const diffThreshold = Math.max(200, noise * 3 + 50)
    await page.getByTestId('axis-y').check()
    await expect(page.getByTestId('profile-summary')).toContainText('Y 轴剖面')
    await page.waitForTimeout(800)
    const shotY = await profileChart.screenshot()
    const diffXY = await countDiff(page, shotX, shotY)
    expect(diffXY, '剖面 X→Y 切换必须产生超噪声的可见变化').toBeGreaterThan(diffThreshold)
    await page.getByTestId('axis-z').check()
    await expect(page.getByTestId('profile-summary')).toContainText('Z 轴剖面')
    await page.waitForTimeout(800)
    const shotZ = await profileChart.screenshot()
    const diffYZ = await countDiff(page, shotY, shotZ)
    expect(diffYZ, '剖面 Y→Z 切换必须产生超噪声的可见变化').toBeGreaterThan(diffThreshold)
    writeFileSync(evidencePath('rho-profile-axis-x.png'), shotX)
    writeFileSync(evidencePath('rho-profile-axis-y.png'), shotY)
    writeFileSync(evidencePath('rho-profile-axis-z.png'), shotZ)
    ev.interactions['profile_axis_switch'] = {
      noise_diff: noise,
      threshold: diffThreshold,
      diff_x_to_y: diffXY,
      diff_y_to_z: diffYZ,
    }

    // --- 交互 3：模型对比点击候选 → 成果页 ------------------------------------
    const comparisonPanel = page.getByTestId('model-comparison-panel')
    await expect(comparisonPanel).toContainText('普通克里金')
    await comparisonPanel.getByTestId('model-candidate-row').first().click()
    await expect(page).toHaveURL(new RegExp(`#\\/results\\/${officialResultId}`))
    ev.interactions['candidate_click'] = {
      result_id: officialResultId,
      algorithm: 'ordinary_kriging',
    }
    await page.screenshot({ path: evidencePath('rho-result-candidate.png') })
    await page.goBack()
    await expect(page.getByTestId('analysis-profile-badge')).toContainText('电阻率', {
      timeout: 60_000,
    })

    // --- 移动视口 390×844：无页面级横向溢出且图表非空 --------------------------
    await page.setViewportSize(MOBILE_VIEWPORT)
    await page.goto(`/#/datasets/${datasetId}/analysis`, { waitUntil: 'load', timeout: 60_000 })
    await expect(page.getByTestId('analysis-profile-badge')).toContainText('电阻率', {
      timeout: 60_000,
    })
    const mobileChart = page.getByTestId('spatial-chart')
    await expect(mobileChart).toBeVisible()
    await expectCanvasPainted(mobileChart)
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth)
    expect(scrollWidth, '390×844 不得有页面级横向溢出').toBeLessThanOrEqual(MOBILE_VIEWPORT.width)
    const mobilePainted = await sampleCanvasPainted(mobileChart)
    const mobileMetrics = await expectChartContent(
      page,
      await mobileChart.screenshot(),
      '移动端空间异常图',
    )
    await page.screenshot({ path: evidencePath('rho-mobile-390.png'), fullPage: true })

    // --- 全局健康门 ------------------------------------------------------------
    expectHealthy(ev, '电阻率分析中心')

    ev.pixelStats = {
      desktop_spatial_chart: { painted_samples: spatialPainted, metrics: spatialMetrics },
      mobile_spatial_chart: { painted_samples: mobilePainted, metrics: mobileMetrics },
      profile_chart_painted_samples: profilePainted,
    }
    ev.timings = { summary_api_ms: summaryMs, enter_ms: enterMs, total_ms: Date.now() - t0 }

    console.log(
      `[analysis-live:rho] gpu=${gpuRenderer} 摘要=${summaryMs}ms 入场=${enterMs}ms ` +
        `空间图=${JSON.stringify(spatialMetrics)} 移动=${JSON.stringify(mobileMetrics)} ` +
        `剖面噪声=${noise} Δ(X→Y)=${diffXY} Δ(Y→Z)=${diffYZ} ` +
        `总耗时=${((Date.now() - t0) / 1000).toFixed(1)}s`,
    )
  })

  test('微震分析中心：API 合同 → 速度高/低值图例 → 分布图 → 普通克里金官方候选', async ({
    page,
    request,
  }) => {
    test.setTimeout(300_000)
    const t0 = Date.now()
    const ev = cases.microseismic
    const datasetId = String(ev.identity['dataset_version_id'])
    const officialResultId = String(ev.identity['official_result_id'])

    // --- API 门：analysis-summary 合同 ---------------------------------------
    const summaryStart = Date.now()
    const summaryResp = await request.get(`/api/datasets/${datasetId}/analysis-summary`)
    expect(summaryResp.ok()).toBe(true)
    const summary = await summaryResp.json()
    const summaryMs = Date.now() - summaryStart

    expect(summary.dataset_id).toBe(datasetId)
    expect(summary.case_id).toBe(MICRO_CASE_ID)
    expect(summary.analysis_profile).toBe('microseismic_velocity')
    expect(summary.variable.name).toBe('Vx')
    expect(summary.variable.unit).toBe('km/s')
    expect(summary.quality.row_count).toBe(MICRO_ROW_COUNT)
    expectFiniteStatistics(summary.statistics, '微震')

    const axisTrends = moduleOf(summary, 'axis_trends')
    expect(axisTrends.status).toBe('ok')
    expect(axisTrends.payload.method).toBeTruthy()
    expect(axisTrends.payload.source_fields?.x).toBeTruthy()
    expect(axisTrends.payload.axes.map((a: any) => a.axis)).toEqual(['x', 'y', 'z'])

    const gradient = moduleOf(summary, 'gradient')
    expect(gradient.status).toBe('ok')
    expect(gradient.payload.method).toBeTruthy()
    expect(gradient.payload.source_fields?.value).toBeTruthy()
    expect(gradient.payload.count).toBeGreaterThanOrEqual(0)

    const anomaly = moduleOf(summary, 'spatial_anomaly')
    expect(anomaly.status).toBe('ok')
    expect(anomaly.payload.method).toBeTruthy()
    expectThresholdSource(anomaly.payload, '微震 spatial_anomaly')
    expect(anomaly.payload.bins.length, '空间异常分箱必须非空').toBeGreaterThan(0)

    const distribution = moduleOf(summary, 'distribution')
    expect(distribution.status).toBe('ok')
    expect(distribution.payload.method).toBeTruthy()
    expect(distribution.payload.bin_count, '分布分箱必须非空').toBeGreaterThan(0)

    const comparison = moduleOf(summary, 'model_comparison')
    expect(comparison.status).toBe('ok')
    const candidates = comparison.payload.candidates as any[]
    expect(candidates.length, '模型对比必须含既有候选').toBeGreaterThanOrEqual(1)
    const official = candidates.find((c) => c.result_id === officialResultId)
    expect(official, '微震官方普通克里金候选缺失').toBeTruthy()
    expect(official.algorithm).toBe('ordinary_kriging')
    expect(official.materialized).toBe(true)
    expect(official.formal_selection).toBe(true)

    expect(summary.provenance.source_sha256).toBe(String(ev.seed['source_sha256']))
    expect(String(summary.provenance.calculation_version)).toMatch(/^analysis\./)
    expectNoAbsolutePath(summary, '微震 analysis-summary')

    ev.api = trimSummary(summary)
    ev.identity = {
      ...ev.identity,
      analysis_profile: summary.analysis_profile,
      calculation_version: summary.provenance.calculation_version,
      dataset_version: summary.provenance.dataset_version,
      source_sha256: summary.provenance.source_sha256,
    }

    // --- 页面门：1440×900 桌面分析中心 ----------------------------------------
    installObservers(page, ev)
    await page.setViewportSize(VIEWPORT)
    const enterStart = Date.now()
    await enterAnalysisCenter(page, MICRO_CASE_ID, datasetId, '微震速度')
    const enterMs = Date.now() - enterStart

    await expect(page.getByTestId('analysis-profile-badge')).toContainText('微震速度')
    const qualityBadge = page.getByTestId('analysis-quality-badge')
    await expect(qualityBadge).toBeVisible()
    if (summary.quality.invalid_count === 0) {
      await expect(qualityBadge).toContainText('数据全部有效')
    }
    await expect(page.getByTestId('analysis-variable')).toContainText('Vx')
    await expect(page.getByTestId('analysis-variable')).toContainText('km/s')

    // 默认主区 = 速度高/低值区域：图例可见 + canvas 非空 + 中央区域非近单色
    const spatialPanel = page.getByTestId('spatial-feature-panel')
    await expect(spatialPanel).toBeVisible()
    await expect(spatialPanel.locator('h3')).toContainText('速度高/低值区域')
    const legend = page.getByTestId('spatial-anomaly-legend')
    await expect(legend).toContainText('速度高值区域')
    await expect(legend).toContainText('速度低值区域')
    const spatialChart = page.getByTestId('spatial-chart')
    await expectCanvasPainted(spatialChart)
    const spatialPainted = await sampleCanvasPainted(spatialChart)
    const spatialShot = await spatialChart.screenshot()
    const spatialMetrics = await expectChartContent(page, spatialShot, '微震速度空间异常图')
    writeFileSync(evidencePath('micro-spatial-chart.png'), spatialShot)
    await page.screenshot({ path: evidencePath('micro-desktop-analysis.png') })

    // 分布图非空：切分布模块 → canvas 真实绘制 + 文本摘要
    await page.getByTestId('module-nav-item-distribution').click()
    await expect(page.getByTestId('distribution-panel')).toBeVisible()
    const distributionChart = page.getByTestId('distribution-chart')
    await expectCanvasPainted(distributionChart)
    const distributionPainted = await sampleCanvasPainted(distributionChart)
    await expect(page.getByTestId('distribution-summary')).toContainText('32 分箱')
    // ECharts 入场动画（默认 1000ms）落定后截图取证
    await page.waitForTimeout(1200)
    const distributionShot = await distributionChart.screenshot()
    const distributionMetrics = await expectChartContent(page, distributionShot, '微震速度分布图')
    writeFileSync(evidencePath('micro-distribution.png'), distributionShot)

    // 模型对比：普通克里金官方候选（已物化 + 正式选择徽标）
    const comparisonPanel = page.getByTestId('model-comparison-panel')
    await expect(comparisonPanel.getByTestId('model-candidate-row').first()).toBeVisible()
    await expect(comparisonPanel).toContainText('普通克里金')
    await expect(comparisonPanel.getByTestId('badge-materialized').first()).toBeVisible()
    await expect(comparisonPanel.getByTestId('badge-formal').first()).toBeVisible()

    // --- 全局健康门 ------------------------------------------------------------
    expectHealthy(ev, '微震分析中心')

    ev.pixelStats = {
      desktop_spatial_chart: { painted_samples: spatialPainted, metrics: spatialMetrics },
      distribution_chart: { painted_samples: distributionPainted, metrics: distributionMetrics },
    }
    ev.timings = { summary_api_ms: summaryMs, enter_ms: enterMs, total_ms: Date.now() - t0 }

    console.log(
      `[analysis-live:micro] 摘要=${summaryMs}ms 入场=${enterMs}ms ` +
        `空间图=${JSON.stringify(spatialMetrics)} 分布=${JSON.stringify(distributionMetrics)} ` +
        `总耗时=${((Date.now() - t0) / 1000).toFixed(1)}s`,
    )
  })

  test.afterAll(() => {
    writeEvidenceJson('environment.json', {
      created_at: new Date().toISOString(),
      platform: `${process.platform}/${process.arch}`,
      node: process.version,
      seed_commands: [
        'python -m geomodeling.preset_cli seed-microseismic --data-dir <isolated>',
        'python -m geomodeling.preset_cli seed-resistivity --data-dir <isolated>（example_data 内置源）',
      ],
    })
    writeEvidenceJson('identity.json', {
      resistivity: cases.resistivity.identity,
      microseismic: cases.microseismic.identity,
      seed: { resistivity: cases.resistivity.seed, microseismic: cases.microseismic.seed },
    })
    writeEvidenceJson('api-summary.json', {
      resistivity: cases.resistivity.api,
      microseismic: cases.microseismic.api,
    })
    writeEvidenceJson('network.json', {
      resistivity: {
        requests: cases.resistivity.network,
        failures: cases.resistivity.networkFailures,
      },
      microseismic: {
        requests: cases.microseismic.network,
        failures: cases.microseismic.networkFailures,
      },
    })
    writeEvidenceJson('console.json', {
      resistivity: cases.resistivity.console,
      microseismic: cases.microseismic.console,
    })
    writeEvidenceJson('pixel-stats.json', {
      resistivity: cases.resistivity.pixelStats,
      microseismic: cases.microseismic.pixelStats,
      gates: {
        chart_non_bg_min: 1000,
        chart_color_std_min: 5,
        axis_switch_over_noise: 'max(200, noise*3+50)',
        note: '中央 50% 区域像素判据（analyzeVolumePixels 同口径）；黑屏/近单色/空图判失败',
      },
    })
    writeEvidenceJson('interactions.json', {
      resistivity: cases.resistivity.interactions,
      microseismic: cases.microseismic.interactions,
    })
    writeEvidenceJson('timings.json', {
      resistivity: cases.resistivity.timings,
      microseismic: cases.microseismic.timings,
    })
  })
})
