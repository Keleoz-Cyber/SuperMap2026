import { expect, test, type APIRequestContext, type BrowserContext, type Page } from '@playwright/test'
import { execFileSync, spawn, type ChildProcess } from 'node:child_process'
import { createHash, randomUUID } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  ensureGasRenderAsset,
  seedGasPreset,
  type GasAssetIdentity,
  type GasSeedRecord,
} from './fixtures/gasPreset'
import {
  analyzeVolumePixels,
  expectVolumeContent,
  installLiveProbe,
  probeMessages,
  runV070RenderGates,
  setSliceIndex,
  waitFrames,
  waitSliceApplied,
  type V070GateReport,
} from './v070RenderGates'

/**
 * v0.8.0 第三批 Task 9：瓦斯含量预置官方成果的真实 SDK live 门（协议 v2）。
 *
 * 真实链路：全新隔离 GEOMODELING_DATA_DIR → fixtures/gasPreset.ts 的
 * seedGasPreset（唯一生产入口 preset_cli seed-gas；--source 缺省为项目内
 * example_data/瓦斯含量_合格样品.csv 内置源，无需任何外部私有源或环境变量，
 * 因此本规格没有也不需要外部私有源式跳过门）→
 * ensureGasRenderAsset 显式 POST 资产 ready → API 身份链（workspace/
 * render-capability/官方成果/manifest：candidate_result、CH4_content、ml/g、
 * regular 网格 151×333×12）→ 产品页首页瓦斯卡 → 统一工作台（builtin_preset、
 * validated 58 行、官方成果）→ 成果页自动 rendered → 复用 v070RenderGates
 * 核心判据跑 Volume/X/Y/Z Slice（各轴两索引）/Contour + 光照开关/渐变
 * 透明度/色带切换/透明度滑块/值域过滤的像素响应 + 包围盒线框贴体
 * （expectedSpansMetres 按真实 bounds 计算：[2992.986, 6639.015, 54.6185]）→
 * 普通刷新 rendered。黑屏/Logo-only/背景单色/旧 app.js/协议超时/空资产标
 * ready 一律判失败。
 *
 * 稀疏数据语义：58 个合格样品（28 个 XY 柱）的插值场是解释性估计；本批按
 * 全部模式应渲染成功写门——若某模式真实运行出现类型化失败，必须展示失败
 * 原因且协议 ERROR 非空（健康门判失败），绝不允许空白 iframe 标 rendered。
 *
 * 用例 2 在同一持久化 profile 上覆盖四种缓存场景（机制与
 * warm-cache-upgrade-live.spec.ts 一致，数据源为瓦斯 candidate_result 链）：
 *   1. fresh context：全新 profile 首访；
 *   2. 普通刷新：同 profile reload；
 *   3. 服务重启后刷新：杀/起自管 uvicorn（同数据目录同 dist）后 reload；
 *   4. warm-cache 升级：先向 HTTP 缓存种植「旧版无查询串 URL」的陈旧 app.js
 *      条目（v1 风格毒化载荷 + max-age=86400），再普通刷新——版本化 URL
 *      必须绕过陈旧条目，真实 v2 app.js 从网络加载并渲染成功。
 * 每场景 Volume+Z 剖面内容判据（阈值与 v070RenderGates 一致）+ 整页/iframe
 * 截图。服务器生命周期由本规格用例 2 自管：默认端口 5278（本机 Windows
 * Hyper-V 保留段 5141–5240 内 bind 直接 errno 13），可用
 * GEOMODELING_WARM_CACHE_PORT 覆盖。
 *
 * GEOMODELING_DATA_DIR 缺失时 beforeAll 直接失败，不静默跳过。证据写入
 * docs/evidence/v0.8.0-batch-3-gas/<run-id>/（仅真实运行时创建；提交前按
 * 目录 README 扫描绝对路径/凭据/私有源内容）。
 */

const HERE = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(HERE, '../..')
const SDK_DIST_PATH = path.join(REPO_ROOT, 'web', 'dist', 'SuperMap3D-2026', 'SuperMap3D.js')
const EVIDENCE_ROOT = path.join(REPO_ROOT, 'docs', 'evidence', 'v0.8.0-batch-3-gas')
const VIEWPORT = { width: 1280, height: 800 }
const RENDERED_GATE_MS = 60_000
const PRESET_CASE_ID = 'gas'
const GAS_ROW_COUNT = 58
// 官方基线网格合同（config/presets/gas-official-baseline.json，入库公开事实）：
// 151×333×12=603,396 节点 @[20,20,5]m，值全有限零 NoData，
// 值域 ≈[1.54, 30.28] ml/g 全正（log 可用）；bounds
// X[1023.802,4016.788] Y[1049.716,7688.731] Z[121.0375,175.656]
const EXPECTED_SHAPE = [151, 333, 12]
const EXPECTED_VARIABLE = 'CH4_content'
const EXPECTED_VALUE_UNIT = 'ml/g'
const EXPECTED_SPANS_METRES: [number, number, number] = [2992.986, 6639.015, 54.6185]
const EXPECTED_VALUE_RANGE: [number, number] = [1.54, 30.28]
// 源样品值域 [0.05, 34.3] ml/g（example_data 字节合同，入库公开事实）
const SOURCE_VALUE_RANGE: [number, number] = [0.05, 34.3]
const LIVE_PORT = Number(process.env.GEOMODELING_LIVE_PORT ?? 5201)
const BASE = process.env.GEOMODELING_E2E_URL ?? `http://127.0.0.1:${LIVE_PORT}`
const WARM_CACHE_PORT = Number(process.env.GEOMODELING_WARM_CACHE_PORT ?? 5278)
const WARM_CACHE_BASE = `http://127.0.0.1:${WARM_CACHE_PORT}`

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

// ---------------------------------------------------------------------------
// 证据聚合
// ---------------------------------------------------------------------------

const runId = isoRunId()
const evidenceDir = path.join(EVIDENCE_ROOT, runId)
let gitCommit = ''
let sdkSha256 = ''
let browserVersion = ''

interface GasLiveRecord {
  seed: Record<string, unknown>
  identity: Record<string, unknown>
  pixelStats: Record<string, unknown>
  timings: Record<string, unknown>
  network: { method: string; path: string; status: number }[]
  networkFailures: string[]
  console: { type: string; text: string; location: string }[]
  sdkVersion: string | null
  gpuRenderer: string | null
  dpr: number | null
  gates: V070GateReport | null
  scenarios: Record<string, unknown>[]
}

const record: GasLiveRecord = {
  seed: {},
  identity: {},
  pixelStats: {},
  timings: {},
  network: [],
  networkFailures: [],
  console: [],
  sdkVersion: null,
  gpuRenderer: null,
  dpr: null,
  gates: null,
  scenarios: [],
}

function evidencePath(name: string): string {
  return path.join(evidenceDir, name)
}

function commonEnvelope() {
  return {
    run_id: runId,
    git_commit: gitCommit,
    sdk_sha256: sdkSha256,
    sdk_version: record.sdkVersion,
    browser: { name: 'chromium', version: browserVersion },
    gpu_renderer: record.gpuRenderer,
    viewport: VIEWPORT,
    device_pixel_ratio: record.dpr,
    results: {
      gas: {
        case_id: PRESET_CASE_ID,
        dataset_version_id: record.seed['dataset_version_id'] ?? null,
        official_result_id: record.seed['official_result_id'] ?? null,
        source_sha256: record.seed['source_sha256'] ?? null,
        grid_sha256: record.identity['grid_sha256'] ?? null,
        netcdf_sha256: record.identity['netcdf_sha256'] ?? null,
        asset_id: record.identity['asset_id'] ?? null,
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
// 用例 2 自管服务器（与 warm-cache-upgrade-live 同一机制）
// ---------------------------------------------------------------------------

function startServer(dataDir: string): ChildProcess {
  return spawn(
    process.env.PYTHON ?? 'python',
    [
      '-m',
      'uvicorn',
      'geomodeling.api.app:app',
      '--host',
      '127.0.0.1',
      '--port',
      String(WARM_CACHE_PORT),
      '--workers',
      '1',
    ],
    {
      cwd: REPO_ROOT,
      env: {
        ...process.env,
        PYTHONPATH: path.join(REPO_ROOT, 'src'),
        GEOMODELING_DATA_DIR: dataDir,
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    },
  )
}

async function waitHealth(timeoutMs = 60_000): Promise<void> {
  const start = Date.now()
  for (;;) {
    try {
      const resp = await fetch(`${WARM_CACHE_BASE}/api/health`)
      if (resp.ok) return
    } catch {
      // 未就绪
    }
    if (Date.now() - start > timeoutMs) throw new Error('uvicorn 健康检查超时')
    await new Promise((r) => setTimeout(r, 500))
  }
}

async function stopServer(child: ChildProcess): Promise<void> {
  await new Promise<void>((resolve) => {
    child.once('exit', () => resolve())
    child.kill('SIGTERM')
    setTimeout(() => {
      child.kill('SIGKILL')
      resolve()
    }, 5_000)
  })
}

interface ScenarioOutcome {
  volumeMetrics: unknown
  sliceMetrics: unknown
}

/** 缓存场景验收：rendered + Volume/Z 剖面内容判据 + 整页/iframe 截图。 */
async function gateScenario(
  page: Page,
  request: APIRequestContext,
  assetId: string,
  sliceIndex: number,
  tag: string,
): Promise<ScenarioOutcome> {
  const phase = page.getByTestId('volume-phase')
  await expect(phase, `${tag}：相位必须到达已渲染`).toHaveText('已渲染', {
    timeout: RENDERED_GATE_MS,
  })
  const messages = await probeMessages(page)
  expect(messages.filter((m) => m.type === 'ERROR'), `${tag}：不得有协议错误`).toEqual([])

  const frame = page.frames().find((f) => f.url().includes('/supermap-volume-frame/'))
  expect(frame, `${tag}：体渲染 iframe 必须存在`).toBeTruthy()
  const diag = await frame!.evaluate(() => (window as any).__GMP_VOLUME_FRAME__)
  expect(diag.phase).toBe('rendered')
  expect(diag.errors).toEqual([])

  const frameLocator = page.getByTestId('volume-frame')
  await frameLocator.scrollIntoViewIfNeeded()
  const shot = () => frameLocator.screenshot()

  // Volume 内容判据（与 v070RenderGates 同阈值）
  const volumeMetrics = await analyzeVolumePixels(page, await shot())
  expectVolumeContent(volumeMetrics, `${tag} Volume`, { minNonBg: 2000, minCoverage: 0.15 })

  // Z 剖面：切模式 → UI 步进到目标索引 → 权威剖面等待（坐标标签与
  // STATE_APPLIED 精确匹配由 waitSliceApplied 门禁）→ 内容判据
  await page.getByTestId('mode-slice').click()
  await setSliceIndex(page, sliceIndex)
  await waitSliceApplied(page, request, frame!, assetId, 'z', sliceIndex)
  await waitFrames(frame!, 6)
  const sliceMetrics = await analyzeVolumePixels(page, await shot())
  expectVolumeContent(sliceMetrics, `${tag} Z 剖面`, { minNonBg: 500, minCoverage: 0.03 })
  await page.getByTestId('mode-volume').click()

  await page.screenshot({ path: path.join(evidenceDir, `${tag}-page.png`) })
  writeFileSync(path.join(evidenceDir, `${tag}-iframe.png`), await shot())

  return { volumeMetrics, sliceMetrics }
}

// ---------------------------------------------------------------------------
// 测试
// ---------------------------------------------------------------------------

// 与 v0.6.1/v0.7.0 各 live 门一致：真实 GPU（--use-angle=gl），SwiftShader 下时序不可靠。
test.use({ launchOptions: { args: ['--use-angle=gl'] } })

test.describe('v0.8.0 第三批：瓦斯预置官方成果真实 SDK live 门', () => {
  test.describe.configure({ mode: 'serial' })

  let dataDir = ''
  let seeded: GasSeedRecord
  let fixtureAsset: GasAssetIdentity

  test.beforeAll(async () => {
    dataDir = assertIsolatedDataDir()
    // 预置 seed（唯一生产入口；幂等；内置 example_data 源，无外部私有源依赖）
    seeded = seedGasPreset(dataDir)
    record.seed = {
      case_id: seeded.case_id,
      workspace_kind: seeded.workspace_kind,
      dataset_version_id: seeded.dataset_version_id,
      experiment_id: seeded.experiment_id,
      run_id: seeded.run_id,
      official_result_id: seeded.official_result.result_id,
      official_url: seeded.official_result.url,
      materialized: seeded.official_result.materialized,
      source_sha256: seeded.source_sha256,
      baseline_sha256: seeded.baseline_sha256,
    }
    gitCommit = execFileSync('git', ['rev-parse', 'HEAD'], {
      cwd: REPO_ROOT,
      encoding: 'utf8',
    }).trim()
    sdkSha256 = sha256File(SDK_DIST_PATH)
    // 显式 POST 资产确保 ready（201 首建/200 幂等）；空资产标 ready 直接抛错
    fixtureAsset = await ensureGasRenderAsset(BASE, seeded.official_result.result_id)
    mkdirSync(evidenceDir, { recursive: true })
  })

  test('用例 1：首页 → 工作台 → 成果页身份链 → 五模式渲染门与交互 → 普通刷新', async ({
    page,
    request,
    browser,
  }) => {
    test.setTimeout(900_000)
    const t0 = Date.now()
    browserVersion = browser.version()
    const officialResultId = String(record.seed['official_result_id'])

    // --- 真实 FastAPI 身份链：workspace → 能力 → 官方成果 → 资产/manifest ----
    const health = await request.get('/api/health')
    expect(health.ok()).toBe(true)

    const wsResp = await request.get(`/api/cases/${PRESET_CASE_ID}/workspace`)
    expect(wsResp.ok()).toBe(true)
    const workspace = await wsResp.json()
    expect(workspace.workspace_kind).toBe('builtin_preset')
    expect(workspace.capabilities).toEqual({
      data_summary: true,
      experiments: true,
      official_result: true,
      native_volume: true,
    })
    expect(workspace.primary_dataset.status).toBe('validated')
    expect(workspace.primary_dataset.profile.mapping.x).toBe('X')
    expect(workspace.primary_dataset.profile.mapping.y).toBe('Y')
    expect(workspace.primary_dataset.profile.mapping.z).toBe('Z')
    expect(workspace.primary_dataset.profile.mapping.value).toBe(EXPECTED_VARIABLE)
    expect(workspace.primary_dataset.profile.mapping.value_unit).toBe(EXPECTED_VALUE_UNIT)
    expect(workspace.primary_dataset.profile.mapping.coordinate_kind).toBe('local_linear')
    expect(workspace.primary_dataset.profile.row_count).toBe(GAS_ROW_COUNT)
    expect(workspace.official_result.result_id).toBe(officialResultId)
    expect(workspace.official_result.materialized).toBe(true)
    expect(workspace.provenance_summary.source_sha256).toBe(record.seed['source_sha256'])
    // 预置 provenance 绝无旧术语与本机路径
    const wsSerialized = JSON.stringify(workspace)
    expect(wsSerialized).not.toMatch(/S3M|legacy|暂缓/)
    expect(wsSerialized).not.toMatch(/[A-Za-z]:[\\/]/)

    // 官方成果能力：候选成果渲染链（candidate_result，绝非 builtin_legacy）
    const capResp = await request.get(`/api/results/${officialResultId}/render-capability`)
    expect(capResp.ok()).toBe(true)
    const capability = await capResp.json()
    expect(capability.supported).toBe(true)
    expect(capability.source_kind).toBe('candidate_result')
    expect(capability.source_id).toBe(officialResultId)
    expect(capability.dimension).toBe('3d')
    expect(capability.grid_kind).toBe('regular')
    expect(capability.property_name).toBe(EXPECTED_VARIABLE)
    expect(capability.units).toBe(EXPECTED_VALUE_UNIT)
    expect(capability.geolocation_status).toBe('display_anchor_only')
    expect(capability.render_profile?.default_palette).toBe('viridis')
    expect(capability.render_profile?.default_scale).toBe('linear')
    expect(capability.render_profile?.log_available).toBe(true)

    // 官方成果身份：普通克里金基线（spherical/24）+ 冻结网格形状（入库公开合同）
    const officialMetaResp = await request.get(`/api/results/${officialResultId}`)
    expect(officialMetaResp.ok()).toBe(true)
    const officialMeta = await officialMetaResp.json()
    expect(officialMeta.algorithm).toBe('ordinary_kriging')
    expect(officialMeta.parameters?.variogram_model).toBe('spherical')
    expect(officialMeta.parameters?.neighbor_count).toBe(24)
    expect(officialMeta.shape).toEqual(EXPECTED_SHAPE)
    expect(officialMeta.cell_count).toBe(603_396)

    // 资产已由夹具显式 POST：纯查询 ready 且身份一致
    const assetResp = await request.get(`/api/results/${officialResultId}/render-assets/netcdf`)
    expect(assetResp.ok()).toBe(true)
    const asset = await assetResp.json()
    expect(asset.id).toBe(fixtureAsset.id)
    expect(asset.status).toBe('ready')
    expect(asset.renderer).toBe('supermap_voxelgrid_netcdf')
    expect(asset.source_kind).toBe('candidate_result')
    expect(asset.source_id).toBe(officialResultId)

    const manifestResp = await request.get(asset.manifest_url)
    expect(manifestResp.ok()).toBe(true)
    const manifest = await manifestResp.json()
    expect(manifest.format).toBe('supermap-voxel-netcdf')
    expect(manifest.source_kind).toBe('candidate_result')
    expect(manifest.source_id).toBe(officialResultId)
    expect(manifest.shape).toEqual(EXPECTED_SHAPE)
    expect(manifest.variable_name).toBe(EXPECTED_VARIABLE)
    expect(manifest.dimension_names).toEqual(['x', 'y', 'z'])
    expect(manifest.nodata_count).toBe(0)
    expect(manifest.grid_sha256).toBe(asset.grid_sha256)
    expect(manifest.netcdf_sha256).toBe(asset.netcdf_sha256)
    const [vmin, vmax] = manifest.encoded_value_range ?? manifest.value_range
    expect(vmax).toBeGreaterThan(vmin)
    expect(vmin).toBeGreaterThan(0) // CH4_content 恒为正（log 可用），绝不静默换算
    // 入库公开事实：官方网格值域 ≈[1.54, 30.28] ml/g，且不超出源样品值域
    expect(Math.abs(vmin - EXPECTED_VALUE_RANGE[0])).toBeLessThanOrEqual(0.05)
    expect(Math.abs(vmax - EXPECTED_VALUE_RANGE[1])).toBeLessThanOrEqual(0.05)
    expect(vmin).toBeGreaterThanOrEqual(SOURCE_VALUE_RANGE[0] - 1e-6)
    expect(vmax).toBeLessThanOrEqual(SOURCE_VALUE_RANGE[1] + 1e-6)

    // --- 产品页：首页瓦斯卡 → 统一工作台 → 官方成果 --------------------------
    await installLiveProbe(page)

    const pathOf = (url: string) => {
      try {
        return new URL(url).pathname
      } catch {
        return url
      }
    }
    page.on('console', (m) =>
      record.console.push({
        type: m.type(),
        text: m.text().slice(0, 400),
        location: pathOf(m.location()?.url ?? ''),
      }),
    )
    page.on('pageerror', (e) =>
      record.console.push({ type: 'pageerror', text: String(e).slice(0, 400), location: '' }),
    )
    page.on('requestfailed', (r) => {
      // 导航式下载（location.assign → attachment）被浏览器以 ERR_ABORTED 中止属正常下载语义
      const p = pathOf(r.url())
      if (p.startsWith('/api/exports/') && r.failure()?.errorText === 'net::ERR_ABORTED') return
      record.networkFailures.push(`${r.method()} ${p} ${r.failure()?.errorText}`)
    })
    // 良性 4xx 白名单：成果未物化/资产未创建前的状态 404（产品页既有语义）
    const benign4xxPatterns = [
      /^\/api\/results\/[^/]+$/,
      /^\/api\/results\/[^/]+\/render-assets\/netcdf$/,
    ]
    page.on('response', (r) => {
      const p = pathOf(r.url())
      record.network.push({ method: r.request().method(), path: p, status: r.status() })
      if (r.status() >= 400 && !benign4xxPatterns.some((re) => re.test(p))) {
        record.networkFailures.push(`${r.status()} ${r.request().method()} ${p}`)
      }
    })

    await page.setViewportSize(VIEWPORT)
    await page.goto('/', { waitUntil: 'load', timeout: 60_000 })
    // 首页瓦斯预置卡：active + builtin_preset 徽标，无暂缓/DAT/legacy 文案
    const gasCard = page.locator('.case-card:has-text("煤层瓦斯")')
    await expect(gasCard).toHaveCount(1, { timeout: 60_000 })
    await expect(gasCard).not.toHaveClass(/disabled/)
    await expect(gasCard).toContainText('散点预置 · 官方基线成果')
    await expect(gasCard).toContainText('标准化散点 · 58 个合格样品')
    await expect(gasCard).toContainText('X/Y/Z/CH4_content')
    await expect(gasCard).toContainText(EXPECTED_VALUE_UNIT)
    await expect(gasCard).not.toContainText('暂缓')
    await expect(gasCard).not.toContainText('DAT')
    await expect(gasCard).not.toContainText('legacy')

    // 统一案例工作台（builtin_preset：数据摘要/官方成果）
    await gasCard.getByTestId('enter-case-workspace').click()
    await expect(page).toHaveURL(/#\/cases\/gas$/, { timeout: 60_000 })
    await expect(page.getByTestId('case-workspace-header')).toContainText('煤层瓦斯', {
      timeout: 60_000,
    })
    await expect(page.getByTestId('case-workspace-header')).toContainText('CSV 预置')
    await expect(page.getByTestId('workspace-overview')).toBeVisible()
    await expect(page.getByTestId('workspace-data')).toBeVisible()
    await expect(page.getByTestId('workspace-data')).toContainText(`行数 ${GAS_ROW_COUNT}`)
    await expect(page.getByTestId('workspace-data')).toContainText('validated')
    await expect(page.getByTestId('workspace-data')).toContainText(
      'X/Y/Z -> CH4_content',
    )
    await expect(page.getByTestId('open-official-result')).toContainText('查看官方成果')
    await expect(page.getByTestId('workspace-results')).toContainText('官方成果')
    await expect(page.getByTestId('workspace-results')).toContainText('已物化')

    // 官方成果直达成果页：算法身份 + NetCDF 面板（资产已 ready → 自动 rendered）
    await page.getByTestId('open-official-result').click()
    await expect(page).toHaveURL(new RegExp(`#\\/results\\/${officialResultId}`), {
      timeout: 60_000,
    })
    await expect(page.locator('.page-sub')).toContainText('ordinary_kriging')
    await expect(page.locator('.page-sub')).toContainText('151×333×12')
    await expect(page.getByTestId('native-volume-panel')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByTestId('create-asset')).toHaveCount(0)

    const phaseLocator = page.getByTestId('volume-phase')
    const renderStart = Date.now()
    await expect(phaseLocator).toHaveText('已渲染', { timeout: RENDERED_GATE_MS })
    const renderedMs = Date.now() - renderStart

    // 协议身份：RENDER_STATE.rendered 与源/网格/NetCDF 哈希一致
    const messages = await probeMessages(page)
    const renderedMsg = messages.find((m) => m.type === 'RENDER_STATE' && m.phase === 'rendered')
    expect(renderedMsg).toBeTruthy()
    const expectedIdentity = {
      sourceKind: 'candidate_result',
      sourceId: officialResultId,
      gridSha256: asset.grid_sha256,
      netcdfSha256: asset.netcdf_sha256,
    }
    expect(renderedMsg.identity).toEqual(expectedIdentity)
    expect(messages.filter((m) => m.type === 'ERROR')).toEqual([])
    const readyMsg = messages.find((m) => m.type === 'FRAME_READY')
    record.sdkVersion = readyMsg?.sdkVersion ?? null
    expect(String(record.sdkVersion)).toMatch(/\d+/)

    // 只读诊断快照
    const frame = page.frames().find((f) => f.url().includes('/supermap-volume-frame/'))
    expect(frame).toBeTruthy()
    const diag = await frame!.evaluate(() => (window as any).__GMP_VOLUME_FRAME__)
    expect(diag.phase).toBe('rendered')
    expect(diag.layerType).toBe('VoxelGridLayer3D')
    expect(diag.mode).toBe('volume')
    expect(diag.identity).toEqual(expectedIdentity)
    expect(diag.errors).toEqual([])

    record.gpuRenderer = await page.evaluate(() => {
      const canvas = document.createElement('canvas')
      const gl = canvas.getContext('webgl2')
      if (!gl) return 'webgl2-unavailable'
      const ext = gl.getExtension('WEBGL_debug_renderer_info')
      const raw = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER)
      gl.getExtension('WEBGL_lose_context')?.loseContext()
      return String(raw)
    })
    record.dpr = await page.evaluate(() => window.devicePixelRatio)

    record.identity = {
      official_result_id: officialResultId,
      dataset_version_id: record.seed['dataset_version_id'],
      asset_id: asset.id,
      renderer: asset.renderer,
      algorithm: 'ordinary_kriging',
      grid_sha256: asset.grid_sha256,
      netcdf_sha256: asset.netcdf_sha256,
      manifest_shape: manifest.shape,
      variable_name: manifest.variable_name,
      value_range: [vmin, vmax],
      rendered_identity: renderedMsg.identity,
      diag_layer_type: diag.layerType,
      sdk_version: record.sdkVersion,
    }

    // --- 五模式渲染门（与 32³/64³/微震/电阻率预置同一可观测检查序列） ---------
    const frameLocator = page.getByTestId('volume-frame')
    await frameLocator.scrollIntoViewIfNeeded()
    const shot = () => page.getByTestId('volume-frame').screenshot()
    const saveShot = (name: string, buf: Buffer) =>
      writeFileSync(evidencePath(`gas-${name}.png`), buf)

    const gates = await runV070RenderGates({
      page,
      request,
      frame: frame!,
      shot,
      saveShot,
      assetId: asset.id,
      identity: {
        assetId: asset.id,
        gridSha256: asset.grid_sha256,
        netcdfSha256: asset.netcdf_sha256,
      },
      valueRange: [vmin, vmax],
      logAvailable: true,
      // 官方基线网格真实各向异性体盒（按数据 bounds 计算）：不得切成方盒
      expectedSpansMetres: EXPECTED_SPANS_METRES,
    })
    record.gates = gates

    // --- 普通刷新场景：资产已 ready → 面板自动 rendered，像素判据同前 ----------
    const refreshStart = Date.now()
    await page.reload({ waitUntil: 'load' })
    await expect(page.getByTestId('native-volume-panel')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByTestId('create-asset')).toHaveCount(0)
    await expect(phaseLocator).toHaveText('已渲染', { timeout: RENDERED_GATE_MS })
    const refreshRenderedMs = Date.now() - refreshStart
    const refreshMessages = await probeMessages(page)
    const refreshRendered = refreshMessages.find(
      (m) => m.type === 'RENDER_STATE' && m.phase === 'rendered',
    )
    expect(refreshRendered).toBeTruthy()
    expect(refreshRendered.identity).toEqual(expectedIdentity)
    expect(refreshMessages.filter((m) => m.type === 'ERROR')).toEqual([])
    await expect(page.locator('.el-loading-mask:visible')).toHaveCount(0, { timeout: 30_000 })
    const refreshMetrics = await analyzeVolumePixels(page, await shot())
    expectVolumeContent(refreshMetrics, '普通刷新后体积', { minNonBg: 2000, minCoverage: 0.15 })

    // --- 全局健康门：无协议错误/页面错误/资源失败 ------------------------------
    const finalMessages = await probeMessages(page)
    expect(finalMessages.filter((m) => m.type === 'ERROR')).toEqual([])
    expect(record.networkFailures).toEqual([])
    const consoleErrors = record.console.filter(
      (c) =>
        ['pageerror', 'error'].includes(c.type) &&
        !(
          c.text.includes('Failed to load resource') &&
          (benign4xxPatterns.some((re) => re.test(c.location)) ||
            c.location.includes('/api/exports/'))
        ),
    )
    expect(consoleErrors).toEqual([])

    record.pixelStats = {
      noise_diff: gates.noiseDiff,
      pixel_threshold: gates.pixelThreshold,
      base_metrics: gates.baseMetrics,
      refresh_metrics: refreshMetrics,
      geometry: gates.geometry,
      slice_mode_metrics: gates.sliceModeMetrics,
      contour_metrics: gates.contourMetrics,
      control_diffs: gates.controlDiffs,
      slice_gates: gates.sliceGates,
      stats_invariant: gates.statsInvariant,
      unsettled_commands: gates.unsettledCommands,
      gates: {
        base_non_bg_min: 2000,
        mode_non_bg_min: 500,
        coverage_min: 'volume 0.15 / modes 0.03（中央区域，去 Logo/罗盘）',
        color_std_min: 5,
        component_ratio_min: 0.9,
        response_over_noise: 'max(200, noise*3+50)',
        control_over_noise: 'max(80, noise*2+20)',
      },
    }
    record.timings = {
      rendered_ms: renderedMs,
      refresh_rendered_ms: refreshRenderedMs,
      rendered_gate_ms: RENDERED_GATE_MS,
      commands: gates.timings,
      total_ms: Date.now() - t0,
    }

    console.log(
      `[gas-live] sdk=${record.sdkVersion} gpu=${record.gpuRenderer} ` +
        `rendered=${renderedMs}ms 刷新=${refreshRenderedMs}ms ` +
        `体积=${JSON.stringify(gates.baseMetrics)} 噪声=${gates.noiseDiff} ` +
        `剖面=${Object.entries(gates.sliceGates)
          .map(([a, g]) => `${a}(q${g.quarterIndex}/q${g.threeQuarterIndex},Δ${g.diff})`)
          .join(' ')} 总耗时=${((Date.now() - t0) / 1000).toFixed(1)}s`,
    )
  })

  test('用例 2：fresh / 普通刷新 / 服务重启刷新 / warm-cache 升级四缓存场景', async ({
    playwright,
    request,
  }) => {
    test.setTimeout(600_000)
    const officialResultId = String(record.seed['official_result_id'])
    const officialResultUrl = String(record.seed['official_url'])

    // candidate_result 身份链（公开 HTTP，幂等）：工作台 → 官方成果 → 显式 POST 资产
    let server: ChildProcess | null = startServer(dataDir)
    let context: BrowserContext | null = null
    try {
      await waitHealth()
      const wsResp = await request.get(`${WARM_CACHE_BASE}/api/cases/${PRESET_CASE_ID}/workspace`)
      expect(wsResp.ok()).toBe(true)
      const workspace = await wsResp.json()
      expect(workspace.workspace_kind).toBe('builtin_preset')
      expect(workspace.official_result?.result_id).toBe(officialResultId)
      expect(workspace.official_result?.materialized).toBe(true)

      const assetResp = await request.post(
        `${WARM_CACHE_BASE}/api/results/${officialResultId}/render-assets/netcdf`,
        { data: {} },
      )
      expect([200, 201]).toContain(assetResp.status())
      const asset = await assetResp.json()
      expect(asset.status).toBe('ready')
      expect(asset.source_kind).toBe('candidate_result')
      expect(asset.source_id).toBe(officialResultId)
      const assetId = asset.id

      const manifestResp = await request.get(`${WARM_CACHE_BASE}${asset.manifest_url}`)
      expect(manifestResp.ok()).toBe(true)
      const manifest = await manifestResp.json()
      expect(manifest.source_kind).toBe('candidate_result')
      expect(manifest.shape).toEqual(EXPECTED_SHAPE)
      // Z 剖面索引取 1/4 层位（官方网格 12 层 → 3），与五模式门同一量级
      const zSliceIndex = Math.max(1, Math.floor(manifest.shape[2] * 0.25))

      const profileDir = path.join(dataDir, 'warm-cache-profile')
      context = await playwright.chromium.launchPersistentContext(profileDir, {
        headless: true,
        args: ['--use-angle=gl'],
        viewport: VIEWPORT,
      })
      await context.addInitScript((proto: string) => {
        const w = window as any
        w.__liveProbe = { messages: [] as any[] }
        window.addEventListener('message', (event) => {
          const d = event.data as any
          if (d && d.protocol === proto) {
            w.__liveProbe.messages.push({
              type: d.type,
              phase: d.phase ?? null,
              code: d.code ?? null,
              slice: d.appliedState?.slice ?? null,
            })
          }
        })
      }, 'gmp-supermap-volume/v2')

      const page = await context.newPage()

      // --- 场景 1：fresh context ----------------------------------------------
      await page.goto(`${WARM_CACHE_BASE}/#${officialResultUrl}`, {
        waitUntil: 'load',
        timeout: 60_000,
      })
      let result = await gateScenario(page, request, assetId, zSliceIndex, '1-fresh')
      record.scenarios.push({ scenario: 'fresh-context', ...result })

      // --- 场景 2：普通刷新 ----------------------------------------------------
      await page.reload({ waitUntil: 'load' })
      result = await gateScenario(page, request, assetId, zSliceIndex, '2-reload')
      record.scenarios.push({ scenario: 'normal-reload', ...result })

      // --- 场景 3：服务重启后刷新 ----------------------------------------------
      await stopServer(server)
      server = startServer(dataDir)
      await waitHealth()
      await page.reload({ waitUntil: 'load' })
      result = await gateScenario(page, request, assetId, zSliceIndex, '3-server-restart')
      record.scenarios.push({ scenario: 'server-restart-reload', ...result })

      // --- 场景 4：warm-cache 升级（陈旧无查询串 app.js 条目已在缓存） ----------
      // 种植陈旧条目：v1 风格毒化载荷 + max-age，经旧式无查询串 URL 进入 HTTP 缓存
      await page.route('**/supermap-volume-frame/app.js', (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/javascript',
          headers: { 'Cache-Control': 'public, max-age=86400' },
          body: `// stale v1-era payload planted for warm-cache upgrade testing
window.parent.postMessage({ protocol: 'gmp-supermap-volume/v1', type: 'FRAME_READY',
  requestId: 'stale', sdkVersion: 'stale', contextType: 2 }, window.location.origin)`,
        }),
      )
      await page.route('**/warm-cache-planter.html', (route) =>
        route.fulfill({
          status: 200,
          contentType: 'text/html',
          body: '<!doctype html><html><head><script src="/supermap-volume-frame/app.js"></script></head><body>planter</body></html>',
        }),
      )
      await page.goto(`${WARM_CACHE_BASE}/warm-cache-planter.html`, { waitUntil: 'load' })
      await page.unroute('**/supermap-volume-frame/app.js')
      await page.unroute('**/warm-cache-planter.html')

      // 普通刷新回到成果页：版本化 URL 必须绕过陈旧条目
      await page.goto(`${WARM_CACHE_BASE}/#${officialResultUrl}`, {
        waitUntil: 'load',
        timeout: 60_000,
      })
      result = await gateScenario(page, request, assetId, zSliceIndex, '4-warm-cache-upgrade')
      // 版本化 app.js 必须携带当前内容版本；陈旧毒化条目（无查询串 URL）不得被命中。
      // 注意：同一版本 URL 的缓存命中（fromCache=true）是合法的同源缓存语义，
      // 不是断言目标——真正的证明是 rendered + diag v2 + 无协议错误（gateScenario 已门禁）。
      const frame = page.frames().find((f) => f.url().includes('/supermap-volume-frame/'))
      const appJsEntry = await frame!.evaluate(() => {
        const hit = performance.getEntriesByType('resource').find((e) => e.name.includes('app.js'))
        return hit
          ? { name: hit.name, transferSize: hit.transferSize, fromCache: hit.transferSize === 0 }
          : null
      })
      expect(appJsEntry, '版本化 app.js 资源条目必须存在').toBeTruthy()
      const entryUrl = new URL(appJsEntry!.name)
      expect(entryUrl.searchParams.get('v'), '必须携带当前帧内容版本').toMatch(/^[0-9a-f]{16}$/)
      // 且与父页注入的 iframe 版本一致（同源同一构建）
      const frameUrl = new URL(frame!.url())
      expect(entryUrl.searchParams.get('v')).toBe(frameUrl.searchParams.get('v'))
      // 陈旧条目是无查询串的裸 URL；命中它意味着版本化失效（此处防御性钉死）
      expect(entryUrl.search).not.toBe('')
      record.scenarios.push({ scenario: 'warm-cache-upgrade', appJs: appJsEntry, ...result })
      record.identity = { ...record.identity, warm_cache_asset_id: assetId }
    } finally {
      if (context) await context.close()
      if (server) await stopServer(server)
    }
  })

  test.afterAll(() => {
    writeEvidenceJson('environment.json', {
      created_at: new Date().toISOString(),
      platform: `${process.platform}/${process.arch}`,
      node: process.version,
      seed_command: 'python -m geomodeling.preset_cli seed-gas --data-dir <isolated>',
      warm_cache_port: WARM_CACHE_PORT,
    })
    writeEvidenceJson('identity.json', { gas: record.identity, seed: record.seed })
    writeEvidenceJson('network.json', {
      gas: { requests: record.network, failures: record.networkFailures },
    })
    writeEvidenceJson('console.json', { gas: record.console })
    writeEvidenceJson('pixel-stats.json', { gas: record.pixelStats })
    writeEvidenceJson('timings.json', { gas: record.timings })
    writeEvidenceJson('slice-exports.json', { gas: record.gates?.exportManifest ?? null })
    writeEvidenceJson('scenarios.json', {
      case_id: PRESET_CASE_ID,
      source_kind: 'candidate_result',
      official_result_id: record.seed['official_result_id'] ?? null,
      asset_id: record.identity['warm_cache_asset_id'] ?? record.identity['asset_id'] ?? null,
      browser: 'chromium(persistent)',
      scenarios: record.scenarios,
    })
  })
})
