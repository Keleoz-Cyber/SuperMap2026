import { expect, test, type Frame, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { createHash, randomUUID } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * v0.6.1 合并前审查补充：内置电阻率 legacy 渲染源的真实 SDK live 门。
 *
 * 与 32³/64³ 门（supermap-native-volume-live.spec.ts）同一口径，但走的是
 * legacy 产品链路：隔离运行时初始未登记 → GET capability 必须
 * supported=false + LEGACY_RENDER_SOURCE_NOT_REGISTERED → 产品页
 * /#/case/resistivity 页内导入入口（multipart 上传合成确定性规则网格 CSV，
 * 绝不依赖机外私有数据）→ 页内登记身份 → 资产纯查询 404 →
 * 显式 POST 资产 → SuperMap3D iframe 握手 rendered → 身份/像素/错误门。
 *
 * 合成网格 8×12×20（非立方，回应电阻率 7×23×42 的细长物理比例），
 * 值域平滑有限、零 NoData；真实 RHO 网格的视觉验收见同目录
 * run-*-legacy-rho-demo 证据（演示运行时实拍）。
 *
 * 断言：
 *   导入 201 且登记身份（shape/property/units/grid SHA）与 CSV 内容一致；
 *   重复导入幂等 200 且登记不被改写；资产 POST 首个成功 201；
 *   manifest shape 与 grid/NetCDF 哈希匹配；
 *   iframe 30 秒内 rendered，RENDER_STATE 身份 = builtin_legacy/resistivity
 *   + grid/NetCDF 哈希；中央画布体积非背景像素 > 2000；
 *   Slice/Contour 各自非背景像素 > 500 且与上一模式像素差超静帧噪声；
 *   无协议错误/页面错误/资源失败（白名单仅资产创建前状态查询 404）。
 *
 * 证据写入 docs/evidence/v0.6.1-netcdf-native/<run-id>/（仅测试运行时创建）。
 */

const HERE = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(HERE, '../..')
const PROTOCOL = 'gmp-supermap-volume/v1'
const SDK_DIST_PATH = path.join(REPO_ROOT, 'web', 'dist', 'SuperMap3D-2026', 'SuperMap3D.js')
const EVIDENCE_ROOT = path.join(REPO_ROOT, 'docs', 'evidence', 'v0.6.1-netcdf-native')
const VIEWPORT = { width: 1280, height: 800 }
const RENDERED_GATE_MS = 30_000

// 确定性合成 legacy 网格：8×12×20 非立方、Z 向下为负（与电阻率约定一致）。
const GRID_SHAPE: [number, number, number] = [8, 12, 20]
const GRID_STEP_M = 25

function syntheticValue(ix: number, iy: number, iz: number): number {
  return (
    60 +
    30 * Math.sin((ix * GRID_STEP_M) / 100) * Math.cos((iy * GRID_STEP_M) / 150) +
    (iz * 40) / (GRID_SHAPE[2] - 1)
  )
}

function buildLegacyCsv(): { csv: string; vmin: number; vmax: number; csvSha256: string } {
  const lines = ['X,Y,Z,RHO']
  let vmin = Number.POSITIVE_INFINITY
  let vmax = Number.NEGATIVE_INFINITY
  for (let iz = 0; iz < GRID_SHAPE[2]; iz += 1) {
    for (let iy = 0; iy < GRID_SHAPE[1]; iy += 1) {
      for (let ix = 0; ix < GRID_SHAPE[0]; ix += 1) {
        const v = syntheticValue(ix, iy, iz)
        vmin = Math.min(vmin, v)
        vmax = Math.max(vmax, v)
        lines.push(`${ix * GRID_STEP_M},${iy * GRID_STEP_M},${-iz * GRID_STEP_M},${v}`)
      }
    }
  }
  const csv = `${lines.join('\n')}\n`
  return { csv, vmin, vmax, csvSha256: createHash('sha256').update(csv).digest('hex') }
}

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
// 像素工具（与 supermap-native-volume-live.spec.ts 同口径）
// ---------------------------------------------------------------------------

async function countNonBg(page: Page, shot: Buffer): Promise<{ nonBg: number; total: number }> {
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
    const d = ctx.getImageData(0, 0, c.width, c.height).data
    let nonBg = 0
    for (let i = 0; i < d.length; i += 4) {
      if (d[i] > 12 || d[i + 1] > 12 || d[i + 2] > 12) nonBg += 1
    }
    return { nonBg, total: c.width * c.height }
  }, dataUrl)
}

async function countDiff(page: Page, a: Buffer, b: Buffer): Promise<number> {
  const pair = [a, b].map((buf) => 'data:image/png;base64,' + buf.toString('base64'))
  return page.evaluate(async ([srcA, srcB]: [string, string]) => {
    const load = (src: string) =>
      new Promise<HTMLImageElement>((res, rej) => {
        const img = new Image()
        img.onload = () => res(img)
        img.onerror = rej
        img.src = src
      })
    const [ia, ib] = await Promise.all([load(srcA), load(srcB)])
    const read = (img: HTMLImageElement) => {
      const c = document.createElement('canvas')
      c.width = img.width
      c.height = img.height
      const ctx = c.getContext('2d')!
      ctx.drawImage(img, 0, 0)
      return { d: ctx.getImageData(0, 0, c.width, c.height).data, w: c.width }
    }
    const A = read(ia)
    const B = read(ib)
    let diff = 0
    for (let y = 0; y < ia.height; y += 1) {
      for (let x = 0; x < ia.width; x += 1) {
        const i = (y * A.w + x) * 4
        if (
          Math.abs(A.d[i] - B.d[i]) > 10 ||
          Math.abs(A.d[i + 1] - B.d[i + 1]) > 10 ||
          Math.abs(A.d[i + 2] - B.d[i + 2]) > 10
        ) {
          diff += 1
        }
      }
    }
    return diff
  }, pair as [string, string])
}

// 渲染发生在 iframe 内：帧等待必须落在子帧事件循环上
async function waitFrames(frame: Frame, frames: number): Promise<void> {
  await frame.evaluate(
    (n) =>
      new Promise<void>((resolve) => {
        let i = 0
        const tick = () => {
          i += 1
          if (i >= n) resolve()
          else requestAnimationFrame(tick)
        }
        requestAnimationFrame(tick)
      }),
    frames,
  )
}

// ---------------------------------------------------------------------------
// 证据聚合
// ---------------------------------------------------------------------------

const runId = isoRunId()
const evidenceDir = path.join(EVIDENCE_ROOT, runId)
let gitCommit = ''
let sdkSha256 = ''
let browserVersion = ''

interface LegacyRecord {
  registration: Record<string, unknown>
  identity: Record<string, unknown>
  pixelStats: Record<string, unknown>
  timings: Record<string, unknown>
  network: { method: string; path: string; status: number }[]
  networkFailures: string[]
  console: { type: string; text: string; location: string }[]
  sdkVersion: string | null
  gpuRenderer: string | null
  dpr: number | null
}

const record: LegacyRecord = {
  registration: {},
  identity: {},
  pixelStats: {},
  timings: {},
  network: [],
  networkFailures: [],
  console: [],
  sdkVersion: null,
  gpuRenderer: null,
  dpr: null,
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
      legacy: {
        source_kind: 'builtin_legacy',
        source_id: 'resistivity',
        grid_sha256: record.registration['grid_sha256'] ?? null,
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
// 测试
// ---------------------------------------------------------------------------

// 与 32³/64³ 门一致：真实 GPU（--use-angle=gl），SwiftShader 下时序不可靠。
test.use({ launchOptions: { args: ['--use-angle=gl'] } })

test.describe('v0.6.1 合并前审查：内置电阻率 legacy 体渲染 live 门', () => {
  test.describe.configure({ mode: 'serial' })

  test.beforeAll(() => {
    assertIsolatedDataDir()
    gitCommit = execFileSync('git', ['rev-parse', 'HEAD'], {
      cwd: REPO_ROOT,
      encoding: 'utf8',
    }).trim()
    sdkSha256 = sha256File(SDK_DIST_PATH)
    mkdirSync(evidenceDir, { recursive: true })
  })

  test('legacy 产品流：导入 → 资产 → rendered → 像素/身份/错误门', async ({
    page,
    request,
    browser,
  }) => {
    test.setTimeout(300_000)
    const t0 = Date.now()
    browserVersion = browser.version()
    const grid = buildLegacyCsv()

    // --- 真实 FastAPI：未登记 → 导入 → 登记身份 ------------------------------
    const health = await request.get('/api/health')
    expect(health.ok()).toBe(true)

    const preCap = await request.get('/api/cases/resistivity/render-capability')
    expect(preCap.ok()).toBe(true)
    const preCapability = await preCap.json()
    expect(preCapability.supported).toBe(false)
    expect(preCapability.reason_code).toBe('LEGACY_RENDER_SOURCE_NOT_REGISTERED')

    // 页内导入成功后由 POST 响应填取（注册身份供后续资产/身份断言复用）
    let registration: any = null

    // --- 产品页：显式 POST（唯一变异入口）→ iframe 30s 内 rendered ----------
    await page.addInitScript((proto: string) => {
      const w = window as any
      w.__liveProbe = { messages: [] as any[] }
      window.addEventListener('message', (event) => {
        const d = event.data as any
        if (d && d.protocol === proto) {
          w.__liveProbe.messages.push({
            type: d.type,
            phase: d.phase ?? null,
            code: d.code ?? null,
            identity: d.identity ?? null,
            sdkVersion: d.sdkVersion ?? null,
          })
        }
      })
    }, PROTOCOL)

    // 良性 4xx 白名单：建资产前的资产状态 404（产品页既有行为）
    const benign4xx = ['/api/cases/resistivity/render-assets/netcdf']
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
    page.on('requestfailed', (r) =>
      record.networkFailures.push(`${r.method()} ${pathOf(r.url())} ${r.failure()?.errorText}`),
    )
    page.on('response', (r) => {
      const p = pathOf(r.url())
      record.network.push({ method: r.request().method(), path: p, status: r.status() })
      if (r.status() >= 400 && !benign4xx.includes(p)) {
        record.networkFailures.push(`${r.status()} ${r.request().method()} ${p}`)
      }
    })

    await page.setViewportSize(VIEWPORT)
    await page.goto('/#/case/resistivity', { waitUntil: 'load', timeout: 60_000 })
    await expect(page.getByTestId('native-volume-panel')).toBeVisible({ timeout: 60_000 })

    // 未登记：稳定原因码 + 显式导入入口；绝无创建资产入口
    await expect(page.getByTestId('unsupported-reason')).toContainText(
      'LEGACY_RENDER_SOURCE_NOT_REGISTERED',
      { timeout: 60_000 },
    )
    await expect(page.getByTestId('legacy-import')).toBeVisible()
    await expect(page.getByTestId('create-asset')).toHaveCount(0)

    // 产品内导入真实链路：页内选择 CSV → multipart POST → 登记身份展示
    const csvPath = test.info().outputPath('legacy-grid.csv')
    writeFileSync(csvPath, grid.csv, 'utf8')
    await page.getByTestId('legacy-import-file').setInputFiles(csvPath)
    await page.getByTestId('import-units').fill('demo.unit')
    const [importResp] = await Promise.all([
      page.waitForResponse(
        (r) =>
          r.request().method() === 'POST' &&
          pathOf(r.url()) === '/api/cases/resistivity/render-sources/import',
        { timeout: 120_000 },
      ),
      page.getByTestId('legacy-import-submit').click(),
    ])
    expect(importResp.status()).toBe(201)
    registration = await importResp.json()
    expect(registration.source_kind).toBe('builtin_legacy')
    expect(registration.source_id).toBe('resistivity')
    expect(registration.shape).toEqual([...GRID_SHAPE])
    expect(registration.property_name).toBe('RHO')
    expect(registration.units).toBe('demo.unit')
    expect(registration.grid_sha256).toMatch(/^[0-9a-f]{64}$/)
    expect(registration.import_source_sha256).toBe(grid.csvSha256)
    expect(String(registration.artifact_dir)).not.toMatch(/^[A-Za-z]:[\\/]/)
    expect(String(registration.artifact_dir)).not.toContain('..')
    record.registration = registration

    // 登记身份页内可见；导入入口消失；面板翻转为可创建资产
    const identityBanner = page.getByTestId('legacy-import-identity')
    await expect(identityBanner).toBeVisible({ timeout: 60_000 })
    await expect(identityBanner).toContainText('8×12×20')
    await expect(identityBanner).toContainText(registration.grid_sha256.slice(0, 16))
    await expect(page.getByTestId('legacy-import')).toHaveCount(0)

    // 同网格重导入（API）：幂等 200，登记身份逐字不改写
    const reimport = await request.post('/api/cases/resistivity/render-sources/import', {
      multipart: {
        file: { name: 'grid.csv', mimeType: 'text/csv', buffer: Buffer.from(grid.csv) },
        x_column: 'X',
        y_column: 'Y',
        z_column: 'Z',
        value_column: 'RHO',
        property_name: 'RHO',
        units: 'demo.unit',
      },
    })
    expect(reimport.status()).toBe(200)
    expect(await reimport.json()).toEqual(registration)

    const capResp = await request.get('/api/cases/resistivity/render-capability')
    expect(capResp.ok()).toBe(true)
    const capability = await capResp.json()
    expect(capability.supported).toBe(true)
    expect(capability.source_kind).toBe('builtin_legacy')
    expect(capability.source_id).toBe('resistivity')
    expect(capability.dimension).toBe('3d')
    expect(capability.grid_kind).toBe('regular')
    expect(capability.property_name).toBe('RHO')
    expect(capability.units).toBe('demo.unit')
    expect(capability.geolocation_status).toBe('display_anchor_only')
    expect(capability.display_transform?.contract).toBe('wgs84_display_anchor_v1')

    // 资产尚未创建：纯查询 404，绝不隐式创建
    const preAsset = await request.get('/api/cases/resistivity/render-assets/netcdf')
    expect(preAsset.status()).toBe(404)

    const createButton = page.getByTestId('create-asset')
    await expect(createButton).toBeVisible({ timeout: 60_000 })

    const postStart = Date.now()
    const [postResp] = await Promise.all([
      page.waitForResponse(
        (r) =>
          r.request().method() === 'POST' &&
          pathOf(r.url()) === '/api/cases/resistivity/render-assets/netcdf',
        { timeout: 120_000 },
      ),
      createButton.click(),
    ])
    const postMs = Date.now() - postStart
    expect([200, 201]).toContain(postResp.status())
    const asset = await postResp.json()
    expect(asset.id).toMatch(/^nc-[0-9a-f]{32}$/)
    expect(asset.status).toBe('ready')
    expect(asset.renderer).toBe('supermap_voxelgrid_netcdf')
    expect(asset.source_kind).toBe('builtin_legacy')
    expect(asset.source_id).toBe('resistivity')
    expect(asset.grid_sha256).toBe(registration.grid_sha256)
    expect(asset.netcdf_sha256).toMatch(/^[0-9a-f]{64}$/)

    // manifest shape 与哈希匹配
    const manifestResp = await request.get(asset.manifest_url)
    expect(manifestResp.ok()).toBe(true)
    const manifest = await manifestResp.json()
    expect(manifest.source_kind).toBe('builtin_legacy')
    expect(manifest.source_id).toBe('resistivity')
    expect(manifest.shape).toEqual([...GRID_SHAPE])
    expect(manifest.grid_sha256).toBe(registration.grid_sha256)
    expect(manifest.netcdf_sha256).toBe(asset.netcdf_sha256)
    expect(manifest.variable_name).toBe('RHO')
    expect(manifest.dimension_names).toEqual(['x', 'y', 'z'])
    expect(manifest.nodata_count).toBe(0)
    expect(manifest.display_transform).toEqual(capability.display_transform)
    const [vmin, vmax] = manifest.encoded_value_range ?? manifest.value_range
    expect(vmax).toBeGreaterThan(vmin)
    expect(Math.abs(vmin - grid.vmin)).toBeLessThan(1e-4)
    expect(Math.abs(vmax - grid.vmax)).toBeLessThan(1e-4)

    // iframe 30 秒内到 rendered（实测耗时记录到 timings）
    const phaseLocator = page.getByTestId('volume-phase')
    await expect(phaseLocator).toHaveText('已渲染', { timeout: RENDERED_GATE_MS })
    const renderedMs = Date.now() - postStart

    // 协议身份：RENDER_STATE.rendered 的 identity 与源/网格/NetCDF 哈希一致
    const messages: any[] = await page.evaluate(() => (window as any).__liveProbe.messages)
    const renderedMsg = messages.find((m) => m.type === 'RENDER_STATE' && m.phase === 'rendered')
    expect(renderedMsg).toBeTruthy()
    const expectedIdentity = {
      sourceKind: 'builtin_legacy',
      sourceId: 'resistivity',
      gridSha256: registration.grid_sha256,
      netcdfSha256: asset.netcdf_sha256,
    }
    expect(renderedMsg.identity).toEqual(expectedIdentity)
    expect(messages.filter((m) => m.type === 'ERROR')).toEqual([])
    const readyMsg = messages.find((m) => m.type === 'FRAME_READY')
    record.sdkVersion = readyMsg?.sdkVersion ?? null
    expect(String(record.sdkVersion)).toMatch(/\d+/)

    // 只读诊断快照：相位/图层类型/身份
    const frame = page.frames().find((f) => f.url().includes('/supermap-volume-frame/'))
    expect(frame).toBeTruthy()
    const diag = await frame!.evaluate(() => (window as any).__GMP_VOLUME_FRAME__)
    expect(diag.phase).toBe('rendered')
    expect(diag.layerType).toBe('VoxelGridLayer3D')
    expect(diag.mode).toBe('volume')
    expect(diag.identity).toEqual(expectedIdentity)
    expect(diag.errors).toEqual([])

    // GPU renderer / DPR（写入证据）
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
      asset_id: asset.id,
      renderer: asset.renderer,
      grid_sha256: asset.grid_sha256,
      netcdf_sha256: asset.netcdf_sha256,
      manifest_sha256_fields: {
        shape: manifest.shape,
        variable_name: manifest.variable_name,
        nodata_count: manifest.nodata_count,
        encoded_value_range: manifest.encoded_value_range,
      },
      rendered_identity: renderedMsg.identity,
      diag_layer_type: diag.layerType,
      sdk_version: record.sdkVersion,
    }

    // --- 像素门：静帧噪声基线 → 基准非背景 → Slice/Contour 响应 --------------
    const frameLocator = page.getByTestId('volume-frame')
    await frameLocator.scrollIntoViewIfNeeded()
    const frameBox = await frameLocator.boundingBox()
    expect(frameBox).toBeTruthy()
    const centralClip = {
      x: frameBox!.x + frameBox!.width * 0.25,
      y: frameBox!.y + frameBox!.height * 0.25,
      width: frameBox!.width * 0.5,
      height: frameBox!.height * 0.5,
    }
    const shotCentral = () => page.screenshot({ clip: centralClip })
    const shotElement = () => page.getByTestId('volume-frame').screenshot()

    const noiseShot1 = await shotCentral()
    await waitFrames(frame!, 10)
    const noiseShot2 = await shotCentral()
    const noiseDiff = await countDiff(page, noiseShot1, noiseShot2)
    const pixelThreshold = Math.max(200, noiseDiff * 3 + 50)

    const baseCentral = noiseShot2
    const baseStats = await countNonBg(page, baseCentral)
    expect(baseStats.nonBg).toBeGreaterThan(2000)
    writeFileSync(evidencePath('legacy-volume.png'), await shotElement())

    const protocolCount = () => page.evaluate(() => (window as any).__liveProbe.messages.length)

    const runCommand = async (
      name: string,
      act: () => Promise<void>,
    ): Promise<{ total_ms: number; central: Buffer }> => {
      const cmdStart = Date.now()
      const before = await protocolCount()
      await act()
      await page.waitForFunction((n) => (window as any).__liveProbe.messages.length > n, before, {
        timeout: 30_000,
      })
      let previous = await shotCentral()
      let settled = false
      const settleStart = Date.now()
      while (Date.now() - settleStart < 20_000) {
        await page.waitForTimeout(250)
        const next = await shotCentral()
        const d = await countDiff(page, previous, next)
        if (d <= Math.max(50, noiseDiff * 2)) {
          settled = true
          previous = next
          break
        }
        previous = next
      }
      if (!settled) {
        console.warn(`[legacy-volume-live] ${name} 20s 内未稳定（如实记录）`)
      }
      return { total_ms: Date.now() - cmdStart, central: previous }
    }

    const diffs: Record<string, number> = {}
    const commandTimings: Record<string, number> = {}

    // slice 模式
    const slice = await runCommand('slice', async () => {
      await page.getByTestId('mode-slice').click()
    })
    const sliceStats = await countNonBg(page, slice.central)
    expect(sliceStats.nonBg, 'legacy Slice 必须有非背景体数据像素').toBeGreaterThan(500)
    diffs.slice = await countDiff(page, baseCentral, slice.central)
    expect(diffs.slice).toBeGreaterThan(pixelThreshold)
    commandTimings.slice = slice.total_ms
    writeFileSync(evidencePath('legacy-slice.png'), await shotElement())

    // contour 模式
    const contour = await runCommand('contour', async () => {
      await page.getByTestId('mode-contour').click()
    })
    const contourStats = await countNonBg(page, contour.central)
    expect(contourStats.nonBg, 'legacy Contour 必须有非背景等值面像素').toBeGreaterThan(500)
    diffs.contour = await countDiff(page, slice.central, contour.central)
    expect(diffs.contour).toBeGreaterThan(pixelThreshold)
    commandTimings.contour = contour.total_ms
    writeFileSync(evidencePath('legacy-contour.png'), await shotElement())

    // 恢复体积模式（产品面完整闭环，无协议错误）
    await runCommand('restore-volume', () => page.getByTestId('mode-volume').click())

    // --- 全局健康门：无协议错误/页面错误/资源失败 ----------------------------
    const finalMessages: any[] = await page.evaluate(() => (window as any).__liveProbe.messages)
    expect(finalMessages.filter((m) => m.type === 'ERROR')).toEqual([])
    expect(record.networkFailures).toEqual([])
    const consoleErrors = record.console.filter(
      (c) =>
        ['pageerror', 'error'].includes(c.type) &&
        !(
          c.text.includes('Failed to load resource') &&
          benign4xx.some((p) => c.location.endsWith(p))
        ),
    )
    expect(consoleErrors).toEqual([])

    record.pixelStats = {
      clip: centralClip,
      noise_diff: noiseDiff,
      pixel_threshold: pixelThreshold,
      base_non_bg: baseStats.nonBg,
      base_total: baseStats.total,
      slice_non_bg: sliceStats.nonBg,
      contour_non_bg: contourStats.nonBg,
      diffs,
      gates: {
        base_non_bg_min: 2000,
        mode_non_bg_min: 500,
        response_over_noise: 'max(200, noise*3+50)',
      },
    }
    record.timings = {
      post_ms: postMs,
      rendered_ms: renderedMs,
      rendered_gate_ms: RENDERED_GATE_MS,
      commands: commandTimings,
      total_ms: Date.now() - t0,
    }

    console.log(
      `[legacy-volume-live] sdk=${record.sdkVersion} gpu=${record.gpuRenderer} ` +
        `POST=${postMs}ms rendered=${renderedMs}ms 非背景=${baseStats.nonBg} 噪声=${noiseDiff} ` +
        `阈值=${pixelThreshold} slice非背景=${sliceStats.nonBg} contour非背景=${contourStats.nonBg} ` +
        `差异: slice=${diffs.slice} contour=${diffs.contour} 总耗时=${((Date.now() - t0) / 1000).toFixed(1)}s`,
    )
  })

  test.afterAll(() => {
    // 证据只在测试运行时生成；六份 JSON 共用同一身份封套
    writeEvidenceJson('environment.json', {
      created_at: new Date().toISOString(),
      platform: `${process.platform}/${process.arch}`,
      node: process.version,
      grid_source: 'synthetic-deterministic-8x12x20',
    })
    writeEvidenceJson('identity.json', { legacy: record.identity, registration: record.registration })
    writeEvidenceJson('network.json', {
      legacy: { requests: record.network, failures: record.networkFailures },
    })
    writeEvidenceJson('console.json', { legacy: record.console })
    writeEvidenceJson('pixel-stats.json', { legacy: record.pixelStats })
    writeEvidenceJson('timings.json', { legacy: record.timings })
  })
})
