import { expect, test, type APIRequestContext, type BrowserContext, type Page } from '@playwright/test'
import { execFileSync, spawn, type ChildProcess } from 'node:child_process'
import { createHash, randomUUID } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  analyzeVolumePixels,
  expectVolumeContent,
  probeMessages,
  waitFrames,
} from './v070RenderGates'

/**
 * v0.7.0 第二批发布阻断修复验收 → v0.8.0 Task 10：缓存场景 × 真实 GPU 渲染门，
 * 数据源从已 410 退役的旧 legacy 电阻率链（旧 CLI 网格登记 + legacy
 * render-assets 路由）迁移到电阻率散点预置 candidate_result 链。
 *
 * 根因（阶段 0 已复现，证据随 PR 提交）：iframe 运行时资产曾位于无
 * Cache-Control 的稳定 URL，升级后浏览器复用缓存的旧协议 app.js，v1/v2
 * 消息双向静默丢弃 → 永久黑屏。修复：iframe URL 携带帧运行时内容哈希
 *（?v=）与 SDK 钉住哈希（?sdk=），升级即换 URL。
 *
 * 真实链路：隔离 GEOMODELING_DATA_DIR → preset_cli seed-resistivity --source
 * $GEOMODELING_RHO_SOURCE（外部私有 17,549 行标准化 CSV，绝不入库，官方基线
 * 默认读受控路径 config/presets/resistivity-official-baseline.json）→ 自管
 * uvicorn → GET /api/cases/resistivity/workspace 取官方成果 → 显式 POST
 * /api/results/<官方候选>/render-assets/netcdf（201 首建/200 幂等）→ 成果
 * 工作台页（/#/results/<id>）真实渲染。
 *
 * 跳过门（与 resistivity-scattered-live 对齐）：GEOMODELING_RHO_SOURCE 未设置
 * 时整文件 test.skip —— CI browser-live 无私有源，必须干净跳过并输出原因。
 * GEOMODELING_DATA_DIR 缺失（且未跳过）时 beforeAll 直接失败，不静默跳过。
 *
 * 本规格在同一持久化 profile 上覆盖四种缓存场景（真实 RTX GPU）：
 *   1. fresh context：全新 profile 首访；
 *   2. 普通刷新：同 profile reload；
 *   3. 服务重启后刷新：杀/起 uvicorn（同数据目录同 dist）后 reload；
 *   4. warm-cache 升级：先向 HTTP 缓存种植「旧版无查询串 URL」的陈旧 app.js
 *      条目（v1 风格毒化载荷 + max-age=86400），再普通刷新——版本化 URL
 *      必须绕过陈旧条目，真实 v2 app.js 从网络加载并渲染成功。
 *
 * 每场景：Volume 与 Z 剖面各跑一次中央区域彩色体素内容判据（去 Logo/罗盘/
 * 线框/背景；连通区 + 颜色标准差），阈值与 resistivity-scattered-live 的
 * v070RenderGates 完全一致（同一真实 RHO 资产，7×23×42 网格；Volume
 * 2000/0.15、剖面 500/0.03），保存整页与 iframe 裁剪截图。
 *
 * 服务器生命周期由本规格自管（独立于全局 webServer）：默认端口 5278——本机
 * Windows Hyper-V 保留段 5141–5240 内 bind 直接 errno 13（原默认 5203 落入
 * 该段），5278 已实测可 bind；可用 GEOMODELING_WARM_CACHE_PORT 覆盖。
 *
 * 证据写入 docs/evidence/v0.8.0-resistivity-dsi-like/<run-id>-warm-cache/
 * （仅真实运行时创建；提交前按目录 README 扫描绝对路径/凭据/私有源内容）。
 */

const RHO_SOURCE = process.env.GEOMODELING_RHO_SOURCE ?? ''
test.skip(
  !RHO_SOURCE,
  'GEOMODELING_RHO_SOURCE 未设置：电阻率标准化散点 CSV 是外部私有源，' +
    'CI browser-live 无此数据，本规格干净跳过；本机发布门请显式设置后运行',
)

const HERE = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(HERE, '../..')
const PORT = Number(process.env.GEOMODELING_WARM_CACHE_PORT ?? 5278)
const BASE = `http://127.0.0.1:${PORT}`
const EVIDENCE_ROOT = path.join(REPO_ROOT, 'docs', 'evidence', 'v0.8.0-resistivity-dsi-like')
const VIEWPORT = { width: 1280, height: 800 }
const RENDERED_GATE_MS = 60_000
// 官方基线网格合同（config/presets/resistivity-official-baseline.json，入库公开事实）：
// 7×23×42=6,762 单元 @20 m
const EXPECTED_SHAPE = [7, 23, 42]

const runId = `run-${new Date().toISOString().replace(/[-:]/g, '').replace(/\..*/, 'Z')}-${randomUUID().slice(0, 8)}`
const evidenceDir = path.join(EVIDENCE_ROOT, `${runId}-warm-cache`)

const scenarioReport: Record<string, unknown>[] = []
let gitCommit = ''
let sdkSha256 = ''

function assertIsolatedDataDir(): string {
  const dir = process.env.GEOMODELING_DATA_DIR
  if (!dir) throw new Error('Live E2E 要求调用环境提供唯一的 GEOMODELING_DATA_DIR')
  const normalized = dir.replace(/\\/g, '/')
  if (normalized.endsWith('var/geomodeling') || normalized.endsWith('var/demo_v041')) {
    throw new Error(`Live E2E 不得使用默认/演示数据目录：${dir}`)
  }
  return dir
}

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
      String(PORT),
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
      const resp = await fetch(`${BASE}/api/health`)
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

/** 场景验收：rendered + Volume/Z 剖面内容判据 + 整页/iframe 截图。 */
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

  // Z 剖面：切模式 → 等待权威剖面应用 → 内容判据（候选/内置共用通用 RenderAsset 路由）
  await page.getByTestId('mode-slice').click()
  const analysisResp = await request.get(
    `${BASE}/api/render-assets/${assetId}/slice-analysis?axis=z&index=${sliceIndex}`,
  )
  expect(analysisResp.ok()).toBe(true)
  const analysis = await analysisResp.json()
  await expect(page.getByTestId('slice-coordinate-label')).toContainText(
    `Z = ${analysis.slice.coordinate}`,
    { timeout: 30_000 },
  )
  await expect
    .poll(
      async () => {
        const msgs = await probeMessages(page)
        const last = [...msgs].reverse().find((m) => m.type === 'STATE_APPLIED' && m.slice)
        return last?.slice ?? null
      },
      { timeout: 30_000 },
    )
    .toMatchObject({ axis: 'z', index: sliceIndex, coordinate: analysis.slice.coordinate })
  await waitFrames(frame!, 6)
  const sliceMetrics = await analyzeVolumePixels(page, await shot())
  expectVolumeContent(sliceMetrics, `${tag} Z 剖面`, { minNonBg: 500, minCoverage: 0.03 })
  await page.getByTestId('mode-volume').click()

  await page.screenshot({ path: path.join(evidenceDir, `${tag}-page.png`) })
  writeFileSync(path.join(evidenceDir, `${tag}-iframe.png`), await shot())

  return { volumeMetrics, sliceMetrics }
}

test.describe('v0.8.0：电阻率散点预置四缓存场景真实 GPU 门', () => {
  test.describe.configure({ mode: 'serial' })

  let dataDir = ''
  let server: ChildProcess | null = null
  let context: BrowserContext | null = null
  let officialResultId = ''
  let officialResultUrl = ''
  let assetId = ''

  test.beforeAll(() => {
    dataDir = assertIsolatedDataDir()
    // 预置 seed（唯一生产入口；幂等；外部私有源经 --source 显式传入，绝不入库）
    const stdout = execFileSync(
      process.env.PYTHON ?? 'python',
      [
        '-m',
        'geomodeling.preset_cli',
        'seed-resistivity',
        '--source',
        RHO_SOURCE,
        '--data-dir',
        dataDir,
      ],
      {
        cwd: REPO_ROOT,
        encoding: 'utf8',
        env: { ...process.env, PYTHONPATH: path.join(REPO_ROOT, 'src') },
        timeout: 600_000,
      },
    )
    const seeded = JSON.parse(stdout.trim().split('\n').pop()!)
    expect(seeded.case_id).toBe('resistivity')
    expect(seeded.workspace_kind).toBe('builtin_preset')
    expect(seeded.official_result.materialized).toBe(true)
    officialResultId = seeded.official_result.result_id
    officialResultUrl = seeded.official_result.url
    gitCommit = execFileSync('git', ['rev-parse', 'HEAD'], {
      cwd: REPO_ROOT,
      encoding: 'utf8',
    }).trim()
    sdkSha256 = createHash('sha256')
      .update(readFileSync(path.join(REPO_ROOT, 'web', 'dist', 'SuperMap3D-2026', 'SuperMap3D.js')))
      .digest('hex')
    mkdirSync(evidenceDir, { recursive: true })
  })

  test('fresh / 刷新 / 重启刷新 / warm-cache 升级', async ({ playwright, request }) => {
    test.setTimeout(600_000)

    // candidate_result 身份链（公开 HTTP，幂等）：工作台 → 官方成果 → 显式 POST 资产
    server = startServer(dataDir)
    await waitHealth()
    const wsResp = await request.get(`${BASE}/api/cases/resistivity/workspace`)
    expect(wsResp.ok()).toBe(true)
    const workspace = await wsResp.json()
    expect(workspace.workspace_kind).toBe('builtin_preset')
    expect(workspace.official_result?.result_id).toBe(officialResultId)
    expect(workspace.official_result?.materialized).toBe(true)

    const assetResp = await request.post(
      `${BASE}/api/results/${officialResultId}/render-assets/netcdf`,
      { data: {} },
    )
    expect([200, 201]).toContain(assetResp.status())
    const asset = await assetResp.json()
    expect(asset.status).toBe('ready')
    expect(asset.source_kind).toBe('candidate_result')
    expect(asset.source_id).toBe(officialResultId)
    assetId = asset.id

    const manifestResp = await request.get(`${BASE}${asset.manifest_url}`)
    expect(manifestResp.ok()).toBe(true)
    const manifest = await manifestResp.json()
    expect(manifest.source_kind).toBe('candidate_result')
    expect(manifest.shape).toEqual(EXPECTED_SHAPE)
    // Z 剖面索引取 1/4 层位（官方网格 42 层 → 10），与五模式门同一量级
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

    // --- 场景 1：fresh context ------------------------------------------------
    await page.goto(`${BASE}/#${officialResultUrl}`, { waitUntil: 'load', timeout: 60_000 })
    let result = await gateScenario(page, request, assetId, zSliceIndex, '1-fresh')
    scenarioReport.push({ scenario: 'fresh-context', ...result })

    // --- 场景 2：普通刷新 -----------------------------------------------------
    await page.reload({ waitUntil: 'load' })
    result = await gateScenario(page, request, assetId, zSliceIndex, '2-reload')
    scenarioReport.push({ scenario: 'normal-reload', ...result })

    // --- 场景 3：服务重启后刷新 ----------------------------------------------
    await stopServer(server)
    server = startServer(dataDir)
    await waitHealth()
    await page.reload({ waitUntil: 'load' })
    result = await gateScenario(page, request, assetId, zSliceIndex, '3-server-restart')
    scenarioReport.push({ scenario: 'server-restart-reload', ...result })

    // --- 场景 4：warm-cache 升级（陈旧无查询串 app.js 条目已在缓存） -----------
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
    await page.goto(`${BASE}/warm-cache-planter.html`, { waitUntil: 'load' })
    await page.unroute('**/supermap-volume-frame/app.js')
    await page.unroute('**/warm-cache-planter.html')

    // 普通刷新回到成果页：版本化 URL 必须绕过陈旧条目
    await page.goto(`${BASE}/#${officialResultUrl}`, { waitUntil: 'load', timeout: 60_000 })
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
    scenarioReport.push({ scenario: 'warm-cache-upgrade', appJs: appJsEntry, ...result })

    await context.close()
    context = null
  })

  test.afterAll(() => {
    if (context) void context.close()
    if (server) void stopServer(server)
    mkdirSync(evidenceDir, { recursive: true })
    writeFileSync(
      path.join(evidenceDir, 'scenarios.json'),
      `${JSON.stringify(
        {
          run_id: runId,
          git_commit: gitCommit,
          sdk_sha256: sdkSha256,
          case_id: 'resistivity',
          source_kind: 'candidate_result',
          official_result_id: officialResultId,
          asset_id: assetId,
          browser: 'chromium(persistent)',
          viewport: VIEWPORT,
          scenarios: scenarioReport,
        },
        null,
        2,
      )}\n`,
      'utf8',
    )
  })
})
