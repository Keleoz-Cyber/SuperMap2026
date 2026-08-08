import {
  expect,
  test,
  type APIRequestContext,
  type Browser,
  type Page,
} from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { createHash, randomUUID } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  installLiveProbe,
  probeMessages,
  runLiveCommand,
  runV070RenderGates,
  type V070GateReport,
} from './v070RenderGates'

/**
 * v0.6.1 Task 14 live 验收 → v0.7.0 第二批 Task 12 扩展：
 * 32³/64³ 确定性基准网格的真实产品流体渲染门（协议 v2）。
 *
 * 真实链路：seed_volume_benchmarks.py 在隔离 GEOMODELING_DATA_DIR 落库
 * case/dataset/experiment/succeeded run/succeeded candidate + grid.npz →
 * 产品页 /#/results/<id>（POST materialize → 能力 GET → 显式 POST 资产 →
 * SuperMap3D iframe 握手）→ 协议/像素/交互/错误/计时门。断言（两个尺寸）：
 *
 *   POST 资产成功（首个成功 201）；manifest shape 与 grid/NetCDF 哈希匹配；
 *   iframe 30 秒内到 rendered（实测记录）；中央画布有非背景体积像素；
 *   X/Y/Z 剖面各自两个索引（1/4 与 3/4）超过静帧像素噪声，3D slice 状态
 *   只来自权威剖面响应（STATE_APPLIED 精确匹配 axis/index/coordinate/
 *   relativePosition）；等值面非背景像素；palette/log/filter/opacity/
 *   lighting/gradient/bounding-box 运行时控件各自超过噪声且权威统计不变；
 *   每源下载一份剖面分析 ZIP（四文件/CSV/统计/manifest 哈希/无路径泄漏）；
 *   无资源失败/pageerror/unhandledrejection（白名单仅两条产品内既有
 *   良性 4xx：建资产前的资产状态 404、通用数据集的微震派生 409）；
 *   64³ 每条命令点击后 5 秒内像素稳定（实测记录，不隐藏慢结果）。
 *
 * 证据写入 docs/evidence/v0.7.0-rendering-slice-analysis/<run-id>/
 * （仅测试运行时创建）：同一运行的全部文件报告同一 run ID、Git commit、
 * SDK 哈希、浏览器、GPU renderer、视口、DPR、结果/源身份、grid 哈希、
 * NetCDF 哈希。不碰默认运行时目录；uvicorn 生命周期由 Playwright webServer 管理。
 */

const HERE = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(HERE, '../..')
const SDK_DIST_PATH = path.join(REPO_ROOT, 'web', 'dist', 'SuperMap3D-2026', 'SuperMap3D.js')
const EVIDENCE_ROOT = path.join(REPO_ROOT, 'docs', 'evidence', 'v0.7.0-rendering-slice-analysis')
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
// 证据聚合（serial 模式同一 worker，模块级共享）
// ---------------------------------------------------------------------------

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
  gates: V070GateReport | null
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
    // 基准候选链自举（幂等）：与 supermap-volume-frame-live 同一
    // fixtures/seed_volume_benchmarks.py；本文件不得依赖其它规格的执行顺序。
    execFileSync(
      process.env.PYTHON ?? 'python',
      [path.join(REPO_ROOT, 'web', 'e2e-live', 'fixtures', 'seed_volume_benchmarks.py')],
      {
        cwd: REPO_ROOT,
        encoding: 'utf8',
        env: {
          ...process.env,
          GEOMODELING_DATA_DIR: dataDir,
          PYTHONPATH: path.join(REPO_ROOT, 'src'),
        },
        timeout: 120_000,
      },
    )
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
      gates: null,
    }
    records[size] = record
    browserVersion = browser.version()

    // 协议消息探针：产品页父侧窗口收 iframe 出站消息（只读观测，不改行为）
    await installLiveProbe(page)

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
    page.on('requestfailed', (r) => {
      // 导航式下载（location.assign → attachment）被浏览器以 ERR_ABORTED 中止属正常下载语义
      const p = pathOf(r.url())
      if (p.startsWith('/api/exports/') && r.failure()?.errorText === 'net::ERR_ABORTED') return
      record.networkFailures.push(`${r.method()} ${p} ${r.failure()?.errorText}`)
    })
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
    // v0.7.0 第二批：候选成果渲染默认值 linear + viridis（Task 2 合同）；
    // log 可用性由权威有效值是否全正决定（基准值域含负值 → 必须不可用）
    expect(capability.render_profile?.default_palette).toBe('viridis')
    expect(capability.render_profile?.default_scale).toBe('linear')
    expect(capability.render_profile?.log_available).toBe(seed.value_range[0] > 0)

    // 纯查询绝不隐式创建资产：该硬门只对 64³ 流程断言。32³ 候选同时被
    // supermap-volume-frame-live 使用（带自定义 launchOptions 的规格可能先于
    // 本文件执行），其资产可能已由该规格的显式 POST 创建；64³ 资产仅由本
    // 文件的显式 POST 创建，因此 404 门在任何套件执行顺序下都保持效力。
    const preAsset = await request.get(`/api/results/${seed.candidate_id}/render-assets/netcdf`)
    if (size === '64') {
      expect(preAsset.status(), '纯查询不得隐式创建资产（64³ 仅本文件使用）').toBe(404)
    } else {
      expect([200, 404]).toContain(preAsset.status())
    }

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
    const messages = await probeMessages(page)
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

    // --- v0.7.0 第二批渲染门：体积 → X/Y/Z 剖面 → 等值面 → 控件 →
    //     统计不变性 → 剖面导出（三源共用同一可观测检查序列） ---------------
    const frameLocator = page.getByTestId('volume-frame')
    await frameLocator.scrollIntoViewIfNeeded()
    const shot = () => page.getByTestId('volume-frame').screenshot()
    const saveShot = (name: string, buf: Buffer) =>
      writeFileSync(evidencePath(`${size}-${name}.png`), buf)

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
      logAvailable: capability.render_profile?.log_available === true,
      // 基准网格 x/y∈[0,500]、z∈[-500,0]：各向同性体盒（跨度相等是数据事实）
      expectedSpansMetres: [500, 500, 500],
    })
    record.gates = gates

    // 重置视角（产品面完整闭环，无协议错误）
    await runLiveCommand(page, shot, gates.noiseDiff, () =>
      page.getByTestId('reset-view').click(),
    )

    // 64³：每条命令点击后 5 秒内稳定（如实记录实测值）
    if (size === '64') {
      for (const name of ['filter', 'opacity', 'slice-mode', 'contour']) {
        expect(gates.timings[name], `64³ ${name} 稳定超过 5 秒`).toBeLessThanOrEqual(
          SETTLE_GATE_MS,
        )
      }
    }

    // --- 全局健康门：无协议错误/页面错误/资源失败 ----------------------------
    const finalMessages = await probeMessages(page)
    expect(finalMessages.filter((m) => m.type === 'ERROR')).toEqual([])
    expect(record.networkFailures).toEqual([])
    const consoleErrors = record.console.filter(
      (c) =>
        ['pageerror', 'error'].includes(c.type) &&
        !(
          c.text.includes('Failed to load resource') &&
          (benign4xx.some((p) => c.location.endsWith(p)) || c.location.includes('/api/exports/'))
        ),
    )
    expect(consoleErrors).toEqual([])

    record.pixelStats = {
      noise_diff: gates.noiseDiff,
      pixel_threshold: gates.pixelThreshold,
      base_metrics: gates.baseMetrics,
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
      post_ms: postMs,
      rendered_ms: renderedMs,
      rendered_gate_ms: RENDERED_GATE_MS,
      commands: gates.timings,
      settle_gate_ms: size === '64' ? SETTLE_GATE_MS : null,
      total_ms: Date.now() - t0,
    }

    console.log(
      `[native-volume-live] ${size}³ sdk=${record.sdkVersion} gpu=${record.gpuRenderer} ` +
        `POST=${postMs}ms rendered=${renderedMs}ms 体积=${JSON.stringify(gates.baseMetrics)} ` +
        `噪声=${gates.noiseDiff} 阈值=${gates.pixelThreshold} 剖面=${Object.entries(gates.sliceGates)
          .map(([a, g]) => `${a}(q${g.quarterIndex}/q${g.threeQuarterIndex},Δ${g.diff})`)
          .join(' ')} 控件差异=${Object.entries(gates.controlDiffs)
          .map(([k, v]) => `${k}=${v}`)
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
    writeEvidenceJson('slice-exports.json', {
      per_size: Object.fromEntries(
        Object.entries(records).map(([s, r]) => [s, r.gates?.exportManifest ?? null]),
      ),
    })
  })
})
