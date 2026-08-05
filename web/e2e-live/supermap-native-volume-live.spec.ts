import {
  expect,
  test,
  type APIRequestContext,
  type Browser,
  type Frame,
  type Page,
} from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { createHash, randomUUID } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * v0.6.1 Task 14 live 验收：32³/64³ 确定性基准网格的真实产品流体渲染门。
 *
 * 真实链路：seed_volume_benchmarks.py 在隔离 GEOMODELING_DATA_DIR 落库
 * case/dataset/experiment/succeeded run/succeeded candidate + grid.npz →
 * 产品页 /#/results/<id>（POST materialize → 能力 GET → 显式 POST 资产 →
 * SuperMap3D iframe 握手）→ 协议/像素/交互/错误/计时门。断言（两个尺寸）：
 *
 *   POST 资产成功（首个成功 201）；manifest shape 与 grid/NetCDF 哈希匹配；
 *   iframe 30 秒内到 rendered（实测记录）；中央画布有非背景体积像素；
 *   filter/opacity/slice/contour 各自超过静帧像素噪声；
 *   无资源失败/pageerror/unhandledrejection（白名单仅两条产品内既有
 *   良性 4xx：建资产前的资产状态 404、通用数据集的微震派生 409）；
 *   64³ 每条命令点击后 5 秒内像素稳定（实测记录，不隐藏慢结果）。
 *
 * 证据写入 docs/evidence/v0.6.1-netcdf-native/<run-id>/（仅测试运行时创建）：
 * 同一运行的全部文件报告同一 run ID、Git commit、SDK 哈希、浏览器、
 * GPU renderer、视口、DPR、结果/源身份、grid 哈希、NetCDF 哈希。
 * 不碰默认运行时目录；uvicorn 生命周期由 Playwright webServer 管理。
 */

const HERE = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(HERE, '../..')
const PROTOCOL = 'gmp-supermap-volume/v1'
const SDK_DIST_PATH = path.join(REPO_ROOT, 'web', 'dist', 'SuperMap3D-2026', 'SuperMap3D.js')
const EVIDENCE_ROOT = path.join(REPO_ROOT, 'docs', 'evidence', 'v0.6.1-netcdf-native')
const SEED_JSON_REL = path.join('live-fixtures', 'volume-benchmarks.json')
const VIEWPORT = { width: 1280, height: 800 }
const SETTLE_GATE_MS = 5_000
const RENDERED_GATE_MS = 30_000

interface SeedEntry {
  candidate_id: string
  case_id: string
  dataset_version_id: string
  experiment_id: string
  run_id: string
  grid_sha256: string
  shape: number[]
  value_range: [number, number]
  nodata_count: number
  property_name: string
  units: string
  variable_name: string
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
// 像素工具（与 Task 9 supermap-volume-frame-live.spec.ts 同口径）
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

// 渲染发生在 iframe 内：帧等待必须落在子帧事件循环上（与 Task 9 同理）
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
// 证据聚合（serial 模式同一 worker，模块级共享）
// ---------------------------------------------------------------------------

interface CommandTiming {
  ack_ms: number
  settle_ms: number
  total_ms: number
}

interface SizeRecord {
  seed: SeedEntry
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

const runId = isoRunId()
const evidenceDir = path.join(EVIDENCE_ROOT, runId)
const seeds: Record<string, SeedEntry> = {}
const records: Record<string, SizeRecord> = {}
let gitCommit = ''
let sdkSha256 = ''
let browserVersion = ''

function evidencePath(name: string): string {
  return path.join(evidenceDir, name)
}

function commonEnvelope() {
  return {
    run_id: runId,
    git_commit: gitCommit,
    sdk_sha256: sdkSha256,
    sdk_version: records['32']?.sdkVersion ?? records['64']?.sdkVersion ?? null,
    browser: { name: 'chromium', version: browserVersion },
    gpu_renderer: records['32']?.gpuRenderer ?? records['64']?.gpuRenderer ?? null,
    viewport: VIEWPORT,
    device_pixel_ratio: records['32']?.dpr ?? records['64']?.dpr ?? null,
    results: Object.fromEntries(
      Object.entries(records).map(([size, r]) => [
        size,
        {
          candidate_id: r.seed.candidate_id,
          case_id: r.seed.case_id,
          dataset_version_id: r.seed.dataset_version_id,
          experiment_id: r.seed.experiment_id,
          run_id: r.seed.run_id,
          grid_sha256: r.seed.grid_sha256,
          netcdf_sha256: r.identity['netcdf_sha256'] ?? null,
          asset_id: r.identity['asset_id'] ?? null,
        },
      ]),
    ),
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

// 性能门要求真实 GPU：headless 默认 SwiftShader 软渲 64³ 单命令重渲 >20s，
// --use-angle=gl 走本机 NVIDIA OpenGL（实测 renderer 写入 environment.json）。
// launchOptions 强制独立 worker，只能顶层声明（仅作用于本文件）。
test.use({ launchOptions: { args: ['--use-angle=gl'] } })

test.describe('v0.6.1 Task 14：32³/64³ 原生体渲染 live 门', () => {
  test.describe.configure({ mode: 'serial' })

  test.beforeAll(() => {
    const dataDir = assertIsolatedDataDir()
    const seedFile = path.join(dataDir, SEED_JSON_REL)
    const seedDoc = JSON.parse(readFileSync(seedFile, 'utf8'))
    expect(seedDoc.schema).toBe('v0.6.1-volume-benchmarks/v1')
    for (const size of ['32', '64']) {
      const entry = seedDoc.sizes?.[size]
      expect(entry, `种子缺少 ${size}³ 条目`).toBeTruthy()
      expect(entry.grid_sha256).toMatch(/^[0-9a-f]{64}$/)
      expect(entry.shape).toEqual([Number(size), Number(size), Number(size)])
      expect(entry.nodata_count).toBe(8)
      seeds[size] = entry
    }
    gitCommit = execFileSync('git', ['rev-parse', 'HEAD'], {
      cwd: REPO_ROOT,
      encoding: 'utf8',
    }).trim()
    sdkSha256 = sha256File(SDK_DIST_PATH)
    mkdirSync(evidenceDir, { recursive: true })
  })

  async function runSizeFlow(
    size: '32' | '64',
    { page, request, browser }: { page: Page; request: APIRequestContext; browser: Browser },
  ) {
    test.setTimeout(300_000)
    const seed = seeds[size]
    const n = Number(size)
    const t0 = Date.now()
    const record: SizeRecord = {
      seed,
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
    records[size] = record
    browserVersion = browser.version()

    // 协议消息探针：产品页父侧窗口收 iframe 出站消息（只读观测，不改行为）
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

    // 良性 4xx 白名单：产品页既有行为（建资产前的资产状态 404、通用数据集微震派生 409）
    const benign4xx = [
      `/api/results/${seed.candidate_id}/render-assets/netcdf`,
      `/api/datasets/${seed.dataset_version_id}/derivation`,
    ]
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

    // --- 真实 FastAPI 门：capability →（UI）显式 POST → manifest -------------
    const health = await request.get('/api/health')
    expect(health.ok()).toBe(true)

    const capResp = await request.get(`/api/results/${seed.candidate_id}/render-capability`)
    expect(capResp.ok()).toBe(true)
    const capability = await capResp.json()
    expect(capability.supported).toBe(true)
    expect(capability.source_kind).toBe('candidate_result')
    expect(capability.source_id).toBe(seed.candidate_id)
    expect(capability.dimension).toBe('3d')
    expect(capability.grid_kind).toBe('regular')
    expect(capability.property_name).toBe(seed.property_name)
    expect(capability.units).toBe(seed.units)
    expect(capability.geolocation_status).toBe('display_anchor_only')
    expect(capability.display_transform?.contract).toBe('wgs84_display_anchor_v1')

    // 全新隔离运行时：此前从未创建资产（纯查询 404，绝不隐式创建）
    const preAsset = await request.get(`/api/results/${seed.candidate_id}/render-assets/netcdf`)
    expect(preAsset.status()).toBe(404)

    // --- 产品页：显式 POST（唯一变异入口）→ iframe 30s 内 rendered ----------
    await page.setViewportSize(VIEWPORT)
    await page.goto(`/#/results/${seed.candidate_id}`, { waitUntil: 'load', timeout: 60_000 })
    await expect(page.getByTestId('native-volume-panel')).toBeVisible({ timeout: 60_000 })
    const createButton = page.getByTestId('create-asset')
    await expect(createButton).toBeVisible({ timeout: 60_000 })

    const postStart = Date.now()
    const [postResp] = await Promise.all([
      page.waitForResponse(
        (r) =>
          r.request().method() === 'POST' &&
          pathOf(r.url()) === `/api/results/${seed.candidate_id}/render-assets/netcdf`,
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
    expect(asset.source_kind).toBe('candidate_result')
    expect(asset.source_id).toBe(seed.candidate_id)
    expect(asset.grid_sha256).toBe(seed.grid_sha256)
    expect(asset.netcdf_sha256).toMatch(/^[0-9a-f]{64}$/)

    // manifest shape 与哈希匹配
    const manifestResp = await request.get(asset.manifest_url)
    expect(manifestResp.ok()).toBe(true)
    const manifest = await manifestResp.json()
    expect(manifest.source_kind).toBe('candidate_result')
    expect(manifest.source_id).toBe(seed.candidate_id)
    expect(manifest.shape).toEqual([n, n, n])
    expect(manifest.grid_sha256).toBe(seed.grid_sha256)
    expect(manifest.netcdf_sha256).toBe(asset.netcdf_sha256)
    expect(manifest.variable_name).toBe(seed.variable_name)
    expect(manifest.dimension_names).toEqual(['x', 'y', 'z'])
    expect(manifest.nodata_count).toBe(seed.nodata_count)
    expect(manifest.display_transform).toEqual(capability.display_transform)
    const [vmin, vmax] = manifest.encoded_value_range ?? manifest.value_range
    expect(vmax).toBeGreaterThan(vmin)
    expect(Math.abs(vmin - seed.value_range[0])).toBeLessThan(1e-4)
    expect(Math.abs(vmax - seed.value_range[1])).toBeLessThan(1e-4)

    // iframe 30 秒内到 rendered（实测耗时记录到 timings）
    const phaseLocator = page.getByTestId('volume-phase')
    await expect(phaseLocator).toHaveText('已渲染', { timeout: RENDERED_GATE_MS })
    const renderedMs = Date.now() - postStart

    // 协议身份：RENDER_STATE.rendered 的 identity 与源/网格/NetCDF 哈希一致
    const messages: any[] = await page.evaluate(() => (window as any).__liveProbe.messages)
    const renderedMsg = messages.find((m) => m.type === 'RENDER_STATE' && m.phase === 'rendered')
    expect(renderedMsg).toBeTruthy()
    const expectedIdentity = {
      sourceKind: 'candidate_result',
      sourceId: seed.candidate_id,
      gridSha256: seed.grid_sha256,
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

    // GPU renderer / DPR（写入证据；两个尺寸必须一致）
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
    if (size === '64') {
      expect(record.gpuRenderer).toBe(records['32'].gpuRenderer)
      expect(record.dpr).toBe(records['32'].dpr)
    }

    record.identity = {
      candidate_id: seed.candidate_id,
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

    // --- 像素门：静帧噪声基线 → 基准非背景 → 四命令响应 ----------------------
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
    const shotElement = () =>
      page.getByTestId('volume-frame').screenshot()

    const noiseShot1 = await shotCentral()
    await waitFrames(frame!, 10)
    const noiseShot2 = await shotCentral()
    const noiseDiff = await countDiff(page, noiseShot1, noiseShot2)
    const pixelThreshold = Math.max(200, noiseDiff * 3 + 50)

    const baseCentral = noiseShot2
    const baseStats = await countNonBg(page, baseCentral)
    expect(baseStats.nonBg).toBeGreaterThan(2000)
    writeFileSync(evidencePath(`${size}-volume.png`), await shotElement())

    const protocolCount = () => page.evaluate(() => (window as any).__liveProbe.messages.length)

    // 命令后像素稳定等待：连续两帧差异 ≤ 静帧噪声口径即视为稳定；
    // 返回 ack/settle/total 三段实测（settle 轮询上限 20s，超时如实记录）
    const runCommand = async (
      name: string,
      act: () => Promise<void>,
    ): Promise<{ timing: CommandTiming; central: Buffer }> => {
      const cmdStart = Date.now()
      const before = await protocolCount()
      await act()
      await page.waitForFunction((n) => (window as any).__liveProbe.messages.length > n, before, {
        timeout: 30_000,
      })
      const ackMs = Date.now() - cmdStart
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
      const settleMs = Date.now() - ackMs - cmdStart
      const totalMs = Date.now() - cmdStart
      if (!settled) {
        console.warn(`[native-volume-live] ${size}³ ${name} 20s 内未稳定（如实记录）`)
      }
      return {
        timing: { ack_ms: ackMs, settle_ms: settleMs, total_ms: totalMs },
        central: previous,
      }
    }

    const diffs: Record<string, number> = {}
    const commandTimings: Record<string, CommandTiming> = {}

    // filter：最小过滤值提到中位区间以上（走产品真实输入框 + 应用按钮）
    const filterMin = vmin + (vmax - vmin) * 0.55
    const filter = await runCommand('filter', async () => {
      await page.getByTestId('filter-min').fill(filterMin.toFixed(6))
      await page.getByTestId('filter-max').fill(vmax.toFixed(6))
      await page.getByTestId('filter-apply').click()
    })
    diffs.filter = await countDiff(page, baseCentral, filter.central)
    expect(diffs.filter).toBeGreaterThan(pixelThreshold)
    commandTimings.filter = filter.timing
    writeFileSync(evidencePath(`${size}-threshold.png`), await shotElement())

    // opacity：不透明度压到 0.12（滑杆 input 事件，与用户拖拽同路径）
    const opacity = await runCommand('opacity', async () => {
      await page.getByTestId('opacity-slider').evaluate((el, v) => {
        const input = el as HTMLInputElement
        input.value = v
        input.dispatchEvent(new Event('input', { bubbles: true }))
      }, '0.12')
    })
    diffs.opacity = await countDiff(page, filter.central, opacity.central)
    expect(diffs.opacity).toBeGreaterThan(pixelThreshold)
    commandTimings.opacity = opacity.timing
    if (size === '64') {
      writeFileSync(evidencePath('64-opacity.png'), await shotElement())
    }

    // slice 模式
    const slice = await runCommand('slice', async () => {
      await page.getByTestId('mode-slice').click()
    })
    const sliceStats = await countNonBg(page, slice.central)
    expect(sliceStats.nonBg, `${size}³ Slice 必须有非背景体数据像素`).toBeGreaterThan(500)
    diffs.slice = await countDiff(page, opacity.central, slice.central)
    expect(diffs.slice).toBeGreaterThan(pixelThreshold)
    commandTimings.slice = slice.timing
    if (size === '64') {
      writeFileSync(evidencePath('64-slice.png'), await shotElement())
    }

    // contour 模式
    const contour = await runCommand('contour', async () => {
      await page.getByTestId('mode-contour').click()
    })
    const contourStats = await countNonBg(page, contour.central)
    expect(contourStats.nonBg, `${size}³ Contour 必须有非背景等值面像素`).toBeGreaterThan(500)
    diffs.contour = await countDiff(page, slice.central, contour.central)
    expect(diffs.contour).toBeGreaterThan(pixelThreshold)
    commandTimings.contour = contour.timing
    if (size === '64') {
      writeFileSync(evidencePath('64-contour.png'), await shotElement())
    }

    // 恢复体积模式 + 重置视角（产品面完整闭环，无协议错误）
    await runCommand('restore-volume', () => page.getByTestId('mode-volume').click())
    await runCommand('reset-view', () => page.getByTestId('reset-view').click())

    // 64³：每条命令点击后 5 秒内稳定（如实记录实测值）
    if (size === '64') {
      for (const name of ['filter', 'opacity', 'slice', 'contour']) {
        expect(commandTimings[name].total_ms, `64³ ${name} 稳定超过 5 秒`).toBeLessThanOrEqual(
          SETTLE_GATE_MS,
        )
      }
    }

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
        response_over_noise: 'max(200, noise*3+50)',
      },
    }
    record.timings = {
      post_ms: postMs,
      rendered_ms: renderedMs,
      rendered_gate_ms: RENDERED_GATE_MS,
      commands: commandTimings,
      settle_gate_ms: size === '64' ? SETTLE_GATE_MS : null,
      total_ms: Date.now() - t0,
    }

    console.log(
      `[native-volume-live] ${size}³ sdk=${record.sdkVersion} gpu=${record.gpuRenderer} ` +
        `POST=${postMs}ms rendered=${renderedMs}ms 非背景=${baseStats.nonBg} 噪声=${noiseDiff} ` +
        `阈值=${pixelThreshold} 差异: filter=${diffs.filter} opacity=${diffs.opacity} ` +
        `slice=${diffs.slice} contour=${diffs.contour} ` +
        `稳定ms: ${Object.entries(commandTimings)
          .map(([k, v]) => `${k}=${v.total_ms}`)
          .join(' ')} 总耗时=${((Date.now() - t0) / 1000).toFixed(1)}s`,
    )
  }

  test('32³ 产品流：身份/非空/像素响应/错误门', async ({ page, request, browser }) => {
    await runSizeFlow('32', { page, request, browser })
  })

  test('64³ 产品流：身份/非空/像素响应/错误/5 秒稳定门', async ({ page, request, browser }) => {
    await runSizeFlow('64', { page, request, browser })
  })

  test.afterAll(() => {
    // 证据只在测试运行时生成；六份 JSON 共用同一身份封套
    writeEvidenceJson('environment.json', {
      created_at: new Date().toISOString(),
      platform: `${process.platform}/${process.arch}`,
      node: process.version,
      seed_schema: 'v0.6.1-volume-benchmarks/v1',
    })
    writeEvidenceJson('identity.json', {
      per_size: Object.fromEntries(Object.entries(records).map(([s, r]) => [s, r.identity])),
    })
    writeEvidenceJson('network.json', {
      per_size: Object.fromEntries(
        Object.entries(records).map(([s, r]) => [
          s,
          { requests: r.network, failures: r.networkFailures },
        ]),
      ),
    })
    writeEvidenceJson('console.json', {
      per_size: Object.fromEntries(Object.entries(records).map(([s, r]) => [s, r.console])),
    })
    writeEvidenceJson('pixel-stats.json', {
      per_size: Object.fromEntries(Object.entries(records).map(([s, r]) => [s, r.pixelStats])),
    })
    writeEvidenceJson('timings.json', {
      per_size: Object.fromEntries(Object.entries(records).map(([s, r]) => [s, r.timings])),
    })
  })
})
