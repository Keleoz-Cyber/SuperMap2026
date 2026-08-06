import { expect, test, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { createHash, randomUUID } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  installLiveProbe,
  probeMessages,
  runV070RenderGates,
  type V070GateReport,
} from './v070RenderGates'

/**
 * v0.7.0 Batch 1 Task 9 → v0.7.0 第二批 Task 12 扩展：微震 CSV 预置官方
 * 普通克里金成果的真实 SDK live 门（协议 v2）。
 *
 * 真实链路：全新隔离 GEOMODELING_DATA_DIR → preset_cli seed-microseismic
 * （正常 Case→Dataset→Experiment→Run→Candidate→materialize→FormalSelection
 * 链；只读 CSV 预置，绝无浏览器上传）→ API 身份链（workspace/能力/资产/
 * manifest：source→baseline→grid→NetCDF→asset 哈希一致）→ 产品页
 * /#/cases/builtin-microseismic-vx-1911 工作台 → 官方成果 → 显式 POST 资产 →
 * SuperMap3D iframe rendered → 体积/X/Y/Z 剖面（两索引超噪声 + STATE_APPLIED
 * 权威载荷）/等值面/运行时控件 + 权威统计不变性 + 剖面分析 ZIP 导出校验 →
 * 协议/网络/控制台错误门。
 *
 * 本门与 v0.6.1 其余专有 SDK live 门同一策略：只在本机发布门运行（CI 的
 * browser-live 仅过滤 platform-live.spec.ts）；SDK 缺失时 beforeAll 直接
 * 失败，不静默跳过。证据写入
 * docs/evidence/v0.7.0-rendering-slice-analysis/<run-id>/。
 */

const HERE = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(HERE, '../..')
const SDK_DIST_PATH = path.join(REPO_ROOT, 'web', 'dist', 'SuperMap3D-2026', 'SuperMap3D.js')
const EVIDENCE_ROOT = path.join(REPO_ROOT, 'docs', 'evidence', 'v0.7.0-rendering-slice-analysis')
const VIEWPORT = { width: 1280, height: 800 }
const RENDERED_GATE_MS = 60_000
const PRESET_CASE_ID = 'builtin-microseismic-vx-1911'
// 官方基线网格合同（config/presets/microseismic-official-baseline.json）
const EXPECTED_SHAPE = [35, 47, 82]
const EXPECTED_VARIABLE = 'Vx'

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

interface PresetRecord {
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
}

const record: PresetRecord = {
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
      preset: {
        case_id: PRESET_CASE_ID,
        official_result_id: record.seed['result_id'] ?? null,
        grid_sha256: record.identity['grid_sha256'] ?? null,
        netcdf_sha256: record.identity['netcdf_sha256'] ?? null,
        asset_id: record.identity['asset_id'] ?? null,
      },
    },
  }
}

function writeEvidenceJson(name: string, body: Record<string, unknown>) {
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

// 与 v0.6.1 各 live 门一致：真实 GPU（--use-angle=gl），SwiftShader 下时序不可靠。
test.use({ launchOptions: { args: ['--use-angle=gl'] } })

test.describe('v0.7.0 Batch 1：微震预置官方成果原生体渲染 live 门', () => {
  test.describe.configure({ mode: 'serial' })

  test.beforeAll(() => {
    const dataDir = assertIsolatedDataDir()
    // 预置 seed（唯一生产入口；幂等；只读受控 CSV，不碰默认/用户运行时）
    const stdout = execFileSync(
      process.env.PYTHON ?? 'python',
      ['-m', 'geomodeling.preset_cli', 'seed-microseismic', '--data-dir', dataDir],
      { cwd: REPO_ROOT, encoding: 'utf8', timeout: 600_000 },
    )
    const seeded = JSON.parse(stdout.trim().split('\n').pop()!)
    record.seed = {
      case_id: seeded.case_id,
      dataset_version_id: seeded.dataset_version_id,
      experiment_id: seeded.experiment_id,
      run_id: seeded.run_id,
      result_id: seeded.official_result.result_id,
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
    mkdirSync(evidenceDir, { recursive: true })
  })

  test('官方微震成果：身份链 → 工作台 → rendered → 像素/错误门', async ({
    page,
    request,
    browser,
  }) => {
    test.setTimeout(600_000)
    const t0 = Date.now()
    browserVersion = browser.version()
    const resultId = String(record.seed['result_id'])

    // --- 真实 FastAPI 身份链：workspace → 能力 → 资产 → manifest ------------
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
    expect(workspace.primary_dataset.profile.mapping.value_name).toBe('Vx')
    expect(workspace.primary_dataset.profile.mapping.value_unit).toBe('km/s')
    expect(workspace.primary_dataset.profile.row_count).toBe(1911)
    expect(workspace.official_result.result_id).toBe(resultId)
    expect(workspace.official_result.materialized).toBe(true)
    expect(workspace.provenance_summary.source_sha256).toBe(record.seed['source_sha256'])

    const capResp = await request.get(`/api/results/${resultId}/render-capability`)
    expect(capResp.ok()).toBe(true)
    const capability = await capResp.json()
    expect(capability.supported).toBe(true)
    expect(capability.source_kind).toBe('candidate_result')
    expect(capability.source_id).toBe(resultId)
    expect(capability.dimension).toBe('3d')
    expect(capability.grid_kind).toBe('regular')
    expect(capability.property_name).toBe('Vx')
    expect(capability.units).toBe('km/s')
    expect(capability.geolocation_status).toBe('display_anchor_only')
    // v0.7.0 第二批：候选成果渲染默认值 linear + viridis（Task 2 合同）
    expect(capability.render_profile?.default_palette).toBe('viridis')
    expect(capability.render_profile?.default_scale).toBe('linear')
    expect(capability.render_profile?.log_available).toBe(true)

    // 全新隔离运行时：资产纯查询 404（绝不隐式创建）
    const preAsset = await request.get(`/api/results/${resultId}/render-assets/netcdf`)
    expect(preAsset.status()).toBe(404)

    // --- 产品页：工作台 → 官方成果 → 显式 POST → rendered --------------------
    await installLiveProbe(page)

    // 良性 4xx 白名单：建资产前的资产状态 404（产品页既有行为）
    const benign4xx = [`/api/results/${resultId}/render-assets/netcdf`]
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

    await page.setViewportSize(VIEWPORT)
    await page.goto(`/#/cases/${PRESET_CASE_ID}`, { waitUntil: 'load', timeout: 60_000 })
    await expect(page.getByTestId('case-workspace-header')).toContainText('微震速度', {
      timeout: 60_000,
    })
    await expect(page.getByTestId('workspace-overview')).toBeVisible()
    await expect(page.getByTestId('workspace-data')).toBeVisible()
    await expect(page.getByTestId('workspace-experiments')).toBeVisible()

    // 官方成果直达成果页
    await page.getByTestId('open-official-result').click()
    await expect(page.getByTestId('native-volume-panel')).toBeVisible({ timeout: 60_000 })

    // 显式 POST 资产（唯一变异入口）
    const createButton = page.getByTestId('create-asset')
    await expect(createButton).toBeVisible({ timeout: 60_000 })
    const postStart = Date.now()
    const [postResp] = await Promise.all([
      page.waitForResponse(
        (r) =>
          r.request().method() === 'POST' &&
          pathOf(r.url()) === `/api/results/${resultId}/render-assets/netcdf`,
        { timeout: 300_000 },
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
    expect(asset.source_id).toBe(resultId)
    expect(asset.grid_sha256).toMatch(/^[0-9a-f]{64}$/)
    expect(asset.netcdf_sha256).toMatch(/^[0-9a-f]{64}$/)

    // manifest：官方基线网格合同与变量身份
    const manifestResp = await request.get(asset.manifest_url)
    expect(manifestResp.ok()).toBe(true)
    const manifest = await manifestResp.json()
    expect(manifest.source_kind).toBe('candidate_result')
    expect(manifest.source_id).toBe(resultId)
    expect(manifest.shape).toEqual(EXPECTED_SHAPE)
    expect(manifest.variable_name).toBe(EXPECTED_VARIABLE)
    expect(manifest.dimension_names).toEqual(['x', 'y', 'z'])
    expect(manifest.nodata_count).toBe(0)
    expect(manifest.grid_sha256).toBe(asset.grid_sha256)
    expect(manifest.netcdf_sha256).toBe(asset.netcdf_sha256)
    const [vmin, vmax] = manifest.encoded_value_range ?? manifest.value_range
    expect(vmax).toBeGreaterThan(vmin)
    expect(vmin).toBeGreaterThan(0)
    expect(vmax).toBeLessThan(10) // Vx 恒为 km/s，绝不静默换算 m/s

    // iframe rendered（真实 SDK，实测耗时记录）
    const phaseLocator = page.getByTestId('volume-phase')
    await expect(phaseLocator).toHaveText('已渲染', { timeout: RENDERED_GATE_MS })
    const renderedMs = Date.now() - postStart

    // 协议身份：RENDER_STATE.rendered 与源/网格/NetCDF 哈希一致
    const messages = await probeMessages(page)
    const renderedMsg = messages.find((m) => m.type === 'RENDER_STATE' && m.phase === 'rendered')
    expect(renderedMsg).toBeTruthy()
    const expectedIdentity = {
      sourceKind: 'candidate_result',
      sourceId: resultId,
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
      asset_id: asset.id,
      renderer: asset.renderer,
      grid_sha256: asset.grid_sha256,
      netcdf_sha256: asset.netcdf_sha256,
      manifest_shape: manifest.shape,
      variable_name: manifest.variable_name,
      rendered_identity: renderedMsg.identity,
      diag_layer_type: diag.layerType,
      sdk_version: record.sdkVersion,
    }

    // --- v0.7.0 第二批渲染门（与 32³/64³/legacy 同一可观测检查序列） ---------
    const frameLocator = page.getByTestId('volume-frame')
    await frameLocator.scrollIntoViewIfNeeded()
    const shot = () => page.getByTestId('volume-frame').screenshot()
    const saveShot = (name: string, buf: Buffer) =>
      writeFileSync(evidencePath(`preset-${name}.png`), buf)

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
    })
    record.gates = gates

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
      total_ms: Date.now() - t0,
    }

    console.log(
      `[preset-live] sdk=${record.sdkVersion} gpu=${record.gpuRenderer} ` +
        `POST=${postMs}ms rendered=${renderedMs}ms 体积=${JSON.stringify(gates.baseMetrics)} ` +
        `噪声=${gates.noiseDiff} 剖面=${Object.entries(gates.sliceGates)
          .map(([a, g]) => `${a}(q${g.quarterIndex}/q${g.threeQuarterIndex},Δ${g.diff})`)
          .join(' ')} 总耗时=${((Date.now() - t0) / 1000).toFixed(1)}s`,
    )
  })

  test.afterAll(() => {
    writeEvidenceJson('environment.json', {
      created_at: new Date().toISOString(),
      platform: `${process.platform}/${process.arch}`,
      node: process.version,
      seed_command: 'python -m geomodeling.preset_cli seed-microseismic --data-dir <isolated>',
    })
    writeEvidenceJson('identity.json', { preset: record.identity, seed: record.seed })
    writeEvidenceJson('network.json', {
      preset: { requests: record.network, failures: record.networkFailures },
    })
    writeEvidenceJson('console.json', { preset: record.console })
    writeEvidenceJson('pixel-stats.json', { preset: record.pixelStats })
    writeEvidenceJson('timings.json', { preset: record.timings })
    writeEvidenceJson('slice-exports.json', { preset: record.gates?.exportManifest ?? null })
  })
})
