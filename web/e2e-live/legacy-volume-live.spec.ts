import { expect, test, type Frame, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { createHash, randomUUID } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { LEGACY_GRID_SHAPE, syntheticLegacyGridCsv } from './fixtures/legacyGrid'

/**
 * v0.6.1 合并前审查补充：内置电阻率 legacy 体渲染的**产品页**真实 SDK live 门。
 *
 * 与 32³/64³ 门（supermap-native-volume-live.spec.ts）同一像素口径；与
 * supermap-volume-frame-live.spec.ts（CLI 登记 + 隔离裸帧）互补——本规格验收
 * /#/case/resistivity 产品页：capability → 资产确保 → 页面自动 rendered →
 * 协议身份 → 体积/Slice/Contour 像素门 → 错误门。
 *
 * 共享单例纪律：live 套件共用一个隔离 GEOMODELING_DATA_DIR，
 * builtin_legacy/resistivity 注册是单例。本规格与 frame-live 使用
 * fixtures/legacyGrid.ts 的同一 CSV 字节，beforeAll 经 render_cli import-csv
 * 幂等确保登记（同网格同身份，任意执行顺序/并发均不冲突）；随后用一份
 * 不同网格断言覆盖保护（409 LEGACY_RENDER_SOURCE_CONFLICT 且登记不被改写）。
 * 未登记 fresh 状态的页内导入 UI 由 Mock E2E 覆盖（见
 * web/e2e/supermap-native-volume.spec.ts「内置电阻率」用例），本规格不依赖
 * 执行顺序。
 *
 * 证据写入 docs/evidence/v0.6.1-netcdf-native/<run-id>/（仅测试运行时创建）。
 * 真实 RHO 网格（7×23×42）的视觉证据见 run-*-legacy-rho-demo（演示运行时实拍，
 * 其 provenance 字段如实标注）。
 */

const HERE = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(HERE, '../..')
const PROTOCOL = 'gmp-supermap-volume/v1'
const SDK_DIST_PATH = path.join(REPO_ROOT, 'web', 'dist', 'SuperMap3D-2026', 'SuperMap3D.js')
const EVIDENCE_ROOT = path.join(REPO_ROOT, 'docs', 'evidence', 'v0.6.1-netcdf-native')
const VIEWPORT = { width: 1280, height: 800 }
const RENDERED_GATE_MS = 30_000

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

function csvValueRange(csv: string): [number, number] {
  let vmin = Number.POSITIVE_INFINITY
  let vmax = Number.NEGATIVE_INFINITY
  for (const line of csv.trim().split('\n').slice(1)) {
    const v = Number(line.split(',')[3])
    vmin = Math.min(vmin, v)
    vmax = Math.max(vmax, v)
  }
  return [vmin, vmax]
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
let registration: { grid_sha256: string; shape: number[] } | null = null

const record = {
  identity: {} as Record<string, unknown>,
  pixelStats: {} as Record<string, unknown>,
  timings: {} as Record<string, unknown>,
  network: [] as { method: string; path: string; status: number }[],
  networkFailures: [] as string[],
  console: [] as { type: string; text: string; location: string }[],
  sdkVersion: null as string | null,
  gpuRenderer: null as string | null,
  dpr: null as number | null,
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
        grid_sha256: registration?.grid_sha256 ?? null,
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

test.describe('v0.6.1 合并前审查：内置电阻率 legacy 产品页体渲染 live 门', () => {
  test.describe.configure({ mode: 'serial' })

  test.beforeAll(() => {
    const dataDir = assertIsolatedDataDir()
    const fixtureDir = path.join(dataDir, 'live-fixtures')
    mkdirSync(fixtureDir, { recursive: true })
    const csvPath = path.join(fixtureDir, 'legacy-resistivity-grid.csv')
    writeFileSync(csvPath, syntheticLegacyGridCsv(), 'utf8')
    // 与 frame-live 同一 CSV 字节：幂等确保登记（任意执行顺序/并发均同身份）
    const stdout = execFileSync(
      process.env.PYTHON ?? 'python',
      [
        '-m',
        'geomodeling.render_cli',
        'import-csv',
        '--source-id',
        'resistivity',
        '--csv',
        csvPath,
        '--x',
        'x',
        '--y',
        'y',
        '--z',
        'z',
        '--value',
        'value',
        '--property-name',
        'RHO',
        '--units',
        'ohm-m',
        '--data-dir',
        dataDir,
      ],
      { cwd: REPO_ROOT, encoding: 'utf8', timeout: 120_000 },
    )
    registration = JSON.parse(stdout)
    expect(registration!.grid_sha256).toMatch(/^[0-9a-f]{64}$/)
    expect(registration!.shape).toEqual([...LEGACY_GRID_SHAPE])
    gitCommit = execFileSync('git', ['rev-parse', 'HEAD'], {
      cwd: REPO_ROOT,
      encoding: 'utf8',
    }).trim()
    sdkSha256 = sha256File(SDK_DIST_PATH)
    mkdirSync(evidenceDir, { recursive: true })
  })

  test('legacy 产品页：capability → 资产 → rendered → 像素/身份/错误门', async ({
    page,
    request,
    browser,
  }) => {
    test.setTimeout(300_000)
    const t0 = Date.now()
    browserVersion = browser.version()
    const csv = syntheticLegacyGridCsv()
    const [expectVmin, expectVmax] = csvValueRange(csv)

    // --- 真实 FastAPI：登记态 capability -------------------------------------
    const health = await request.get('/api/health')
    expect(health.ok()).toBe(true)

    const capResp = await request.get('/api/cases/resistivity/render-capability')
    expect(capResp.ok()).toBe(true)
    const capability = await capResp.json()
    expect(capability.supported).toBe(true)
    expect(capability.source_kind).toBe('builtin_legacy')
    expect(capability.source_id).toBe('resistivity')
    expect(capability.dimension).toBe('3d')
    expect(capability.grid_kind).toBe('regular')
    expect(capability.property_name).toBe('RHO')
    expect(capability.units).toBe('ohm-m')
    expect(capability.geolocation_status).toBe('display_anchor_only')
    expect(capability.display_transform?.contract).toBe('wgs84_display_anchor_v1')

    // --- 覆盖保护：不同网格必须 409 且登记不被改写 ----------------------------
    // 冲突网格必须仍是完整笛卡尔网格（否则 422 校验先于 409 身份冲突）：
    // 同一形状/值公式，x 轴整体平移 50 m → 轴不同即身份不同。
    const conflictRows = ['x,y,z,value']
    for (let ix = 0; ix < LEGACY_GRID_SHAPE[0]; ix += 1) {
      for (let iy = 0; iy < LEGACY_GRID_SHAPE[1]; iy += 1) {
        for (let iz = 0; iz < LEGACY_GRID_SHAPE[2]; iz += 1) {
          const x = ix * 100 + 50
          const y = iy * 100
          const z = -800 + iz * 100
          const value = 310 + 280 * Math.sin(x / 220) * Math.cos(y / 260) + 20 * Math.sin(z / 90)
          conflictRows.push(`${x},${y},${z},${value.toFixed(6)}`)
        }
      }
    }
    const conflictCsv = `${conflictRows.join('\n')}\n`
    const conflict = await request.post('/api/cases/resistivity/render-sources/import', {
      multipart: {
        file: { name: 'other.csv', mimeType: 'text/csv', buffer: Buffer.from(conflictCsv) },
        x_column: 'x',
        y_column: 'y',
        z_column: 'z',
        value_column: 'value',
        property_name: 'RHO',
        units: 'ohm-m',
      },
    })
    expect(conflict.status()).toBe(409)
    const conflictBody = await conflict.json()
    expect(conflictBody.error?.code ?? conflictBody.code).toBe('LEGACY_RENDER_SOURCE_CONFLICT')
    const capAfter = await (await request.get('/api/cases/resistivity/render-capability')).json()
    expect(capAfter.supported).toBe(true)

    // --- 资产确保：404 → 显式 POST；并发创建 409 → 轮询 ready ----------------
    let asset: any = null
    const preAsset = await request.get('/api/cases/resistivity/render-assets/netcdf')
    if (preAsset.status() === 404) {
      const postResp = await request.post('/api/cases/resistivity/render-assets/netcdf', {
        data: {},
      })
      if (postResp.status() === 409) {
        // 套件内并发创建（frame-live）：轮询直至 ready，绝不改写他人资产
        const pollStart = Date.now()
        while (Date.now() - pollStart < 60_000) {
          const st = await request.get('/api/cases/resistivity/render-assets/netcdf')
          if (st.ok()) {
            const body = await st.json()
            if (body.status === 'ready') {
              asset = body
              break
            }
            if (body.status === 'failed') break
          }
          await new Promise((r) => setTimeout(r, 500))
        }
      } else {
        expect([200, 201]).toContain(postResp.status())
        asset = await postResp.json()
      }
    } else {
      expect(preAsset.ok()).toBe(true)
      asset = await preAsset.json()
    }
    expect(asset, '资产必须达到 ready').toBeTruthy()
    expect(asset.status).toBe('ready')
    expect(asset.id).toMatch(/^nc-[0-9a-f]{32}$/)
    expect(asset.renderer).toBe('supermap_voxelgrid_netcdf')
    expect(asset.grid_sha256).toBe(registration!.grid_sha256)
    expect(asset.netcdf_sha256).toMatch(/^[0-9a-f]{64}$/)

    // manifest shape 与哈希匹配（值域与 CSV 实算一致）
    const manifestResp = await request.get(asset.manifest_url)
    expect(manifestResp.ok()).toBe(true)
    const manifest = await manifestResp.json()
    expect(manifest.source_kind).toBe('builtin_legacy')
    expect(manifest.source_id).toBe('resistivity')
    expect(manifest.shape).toEqual([...LEGACY_GRID_SHAPE])
    expect(manifest.grid_sha256).toBe(registration!.grid_sha256)
    expect(manifest.netcdf_sha256).toBe(asset.netcdf_sha256)
    expect(manifest.variable_name).toBe('RHO')
    expect(manifest.dimension_names).toEqual(['x', 'y', 'z'])
    expect(manifest.nodata_count).toBe(0)
    expect(manifest.display_transform).toEqual(capability.display_transform)
    const [vmin, vmax] = manifest.encoded_value_range ?? manifest.value_range
    expect(vmax).toBeGreaterThan(vmin)
    expect(Math.abs(vmin - expectVmin)).toBeLessThan(1e-4)
    expect(Math.abs(vmax - expectVmax)).toBeLessThan(1e-4)

    // --- 产品页：协议探针 + 网络/控制台监听 ----------------------------------
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

    const benign4xx: string[] = []
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
    // 已登记：绝不出现导入入口；资产 ready → 面板自动进入渲染
    await expect(page.getByTestId('legacy-import')).toHaveCount(0)

    const phaseLocator = page.getByTestId('volume-phase')
    const renderStart = Date.now()
    await expect(phaseLocator).toHaveText('已渲染', { timeout: RENDERED_GATE_MS })
    const renderedMs = Date.now() - renderStart

    // 协议身份：RENDER_STATE.rendered 的 identity 与源/网格/NetCDF 哈希一致
    const messages: any[] = await page.evaluate(() => (window as any).__liveProbe.messages)
    const renderedMsg = messages.find((m) => m.type === 'RENDER_STATE' && m.phase === 'rendered')
    expect(renderedMsg).toBeTruthy()
    const expectedIdentity = {
      sourceKind: 'builtin_legacy',
      sourceId: 'resistivity',
      gridSha256: registration!.grid_sha256,
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
      rendered_ms: renderedMs,
      rendered_gate_ms: RENDERED_GATE_MS,
      commands: commandTimings,
      total_ms: Date.now() - t0,
    }

    console.log(
      `[legacy-volume-live] sdk=${record.sdkVersion} gpu=${record.gpuRenderer} ` +
        `rendered=${renderedMs}ms 非背景=${baseStats.nonBg} 噪声=${noiseDiff} ` +
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
      grid_source: 'fixtures/legacyGrid.ts synthetic-6x7x8（与 frame-live 同字节）',
    })
    writeEvidenceJson('identity.json', { legacy: record.identity, registration })
    writeEvidenceJson('network.json', {
      legacy: { requests: record.network, failures: record.networkFailures },
    })
    writeEvidenceJson('console.json', { legacy: record.console })
    writeEvidenceJson('pixel-stats.json', { legacy: record.pixelStats })
    writeEvidenceJson('timings.json', { legacy: record.timings })
  })
})
