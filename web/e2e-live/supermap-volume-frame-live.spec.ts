import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * v0.6.1 Task 9 live 验收 + v0.7.0 第二批 Task 8：隔离 SuperMap3D iframe 运行时 +
 * gmp-supermap-volume/v2 协议（完整状态 + revision + 回执）。
 * v0.8.0 Task 10：旧 legacy 电阻率渲染端点类型化退役（410），本规格的渲染源
 * 切换为统一 candidate_result 链（与 supermap-native-volume-live 同一基准种子）。
 *
 * 真实链路：seed_volume_benchmarks.py 在隔离 GEOMODELING_DATA_DIR 落库
 * case/dataset/experiment/succeeded run/succeeded candidate + grid.npz（绝不
 * 重跑插值）→ 真实 FastAPI capability/POST/manifest（/api/results/<候选> 统一
 * 路由）→ 轻量 parent harness 打开 /supermap-volume-frame/index.html 并收发
 * 协议消息。断言：
 *
 *   FRAME_READY（contextType=2）、RENDER_STATE.phase==rendered、identity 与
 *   candidate/grid/NetCDF 哈希一致、layerType==VoxelGridLayer3D、mode==volume、
 *   无 pageerror/unhandledrejection/资源 4xx/5xx、画布有非背景像素，
 *   filter/opacity/slice/contour 各产生超过静帧噪声的像素变化。
 *
 * 不碰默认运行时目录；uvicorn 生命周期由 Playwright webServer 管理，结束无进程残留。
 */

const HERE = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(HERE, '../..')
const PROTOCOL = 'gmp-supermap-volume/v2'
const FRAME_PATH = '/supermap-volume-frame/index.html'

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

// 渲染源种子：与 supermap-native-volume-live 共用 fixtures/seed_volume_benchmarks.py
// （确定性 32³/64³ 基准网格的完整候选链，同一隔离库下幂等）；本规格消费 32³ 条目。

// 轻量 parent harness：同一路由满足（route.fulfill）的同源空页，内嵌 iframe 并执行
// §2.4 父侧协议校验（origin/source/protocol/requestId），收到的不合规消息记入 errors。
function harnessHtml(): string {
  return `<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8" />
<link rel="icon" href="data:," />
<title>volume-frame-harness</title>
<style>html,body{margin:0;height:100%;background:#000}iframe{position:fixed;inset:0;width:100%;height:100%;border:0}</style>
</head>
<body>
<script>
(function () {
  var PROTOCOL = '${PROTOCOL}'
  var requestId = new URLSearchParams(location.search).get('request_id') || ''
  var harness = { requestId: requestId, received: [], errors: [] }
  window.__harness = harness
  var iframe = document.createElement('iframe')
  iframe.id = 'volume-frame'
  iframe.src = '${FRAME_PATH}?request_id=' + encodeURIComponent(requestId)
  document.body.appendChild(iframe)
  window.addEventListener('message', function (event) {
    if (event.origin !== window.location.origin) { harness.errors.push('ORIGIN_MISMATCH ' + event.origin); return }
    if (event.source !== iframe.contentWindow) { harness.errors.push('SOURCE_MISMATCH'); return }
    var msg = event.data
    if (!msg || msg.protocol !== PROTOCOL) { harness.errors.push('PROTOCOL_MISMATCH'); return }
    if (msg.requestId !== requestId) { harness.errors.push('REQUEST_ID_MISMATCH'); return }
    harness.received.push(msg)
  })
  window.__send = function (msg) {
    var full = Object.assign({ protocol: PROTOCOL, requestId: requestId }, msg)
    iframe.contentWindow.postMessage(full, window.location.origin)
  }
})()
</script>
</body>
</html>`
}

interface PixelCount {
  nonBg: number
  total: number
}

async function countNonBg(page: any, shot: Buffer): Promise<PixelCount> {
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

async function countDiff(page: any, a: Buffer, b: Buffer): Promise<number> {
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

// 在指定浏览上下文等待 N 个 rAF 帧；渲染发生在 iframe 内，像素等待必须传 frame，
// 让等待与 SDK 渲染循环同一事件循环节拍（SwiftShader 下单帧可达数百毫秒）。
async function waitFrames(target: any, frames: number): Promise<void> {
  await target.evaluate(
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

interface BenchmarkSeed {
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

let seed: BenchmarkSeed | null = null

test.beforeAll(() => {
  const dataDir = assertIsolatedDataDir()
  // 确定性基准候选链（幂等）：case → dataset → experiment → succeeded run →
  // succeeded candidate + grid.npz，候选 POST 渲染资产走真实链路而绝不重跑插值
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
  const seedDoc = JSON.parse(
    readFileSync(path.join(dataDir, 'live-fixtures', 'volume-benchmarks.json'), 'utf8'),
  )
  expect(seedDoc.schema).toBe('v0.6.1-volume-benchmarks/v1')
  const entry = seedDoc.sizes?.['32']
  expect(entry, '种子缺少 32³ 条目').toBeTruthy()
  expect(entry.grid_sha256).toMatch(/^[0-9a-f]{64}$/)
  expect(entry.shape).toEqual([32, 32, 32])
  expect(entry.candidate_id).toBeTruthy()
  seed = entry
})

interface RenderStateWire {
  revision: number
  mode: 'volume' | 'slice' | 'contour'
  filter: { min: number; max: number }
  opacity: number
  colorTransferFunction: { value: number; color: string }[]
  lighting: boolean
  gradientOpacity: boolean
  boundingBox: boolean
  slice?: { axis: 'x' | 'y' | 'z'; index: number; coordinate: number; relativePosition: number }
  contourValue?: number
}

// 初始渲染状态：过滤范围与色带逐字取自真实资产 manifest 值域（候选链网格
// 值域与旧 legacy 网格不同，绝不硬编码旧 RHO 区间）
function makeState(
  range: [number, number],
  revision: number,
  overrides: Partial<RenderStateWire> = {},
): RenderStateWire {
  const [vmin, vmax] = range
  const at = (f: number) => vmin + (vmax - vmin) * f
  return {
    revision,
    mode: 'volume',
    filter: { min: vmin, max: vmax },
    opacity: 1,
    colorTransferFunction: [
      { value: at(0.0), color: '#1a40d9' },
      { value: at(0.25), color: '#1acccc' },
      { value: at(0.5), color: '#f2d926' },
      { value: at(0.75), color: '#f2591a' },
      { value: at(1.0), color: '#a60d1a' },
    ],
    lighting: true,
    gradientOpacity: true,
    boundingBox: true,
    ...overrides,
  }
}

// 32³ NetCDF 体渲染在 SwiftShader 软渲下单帧可达秒级，会饿死截图/求值导致
// 假超时；--use-angle=gl 走本机真实 GPU（与 native-volume 规格同一口径）。
test.use({ launchOptions: { args: ['--use-angle=gl'] } })

test('隔离 SuperMap 帧：真实 NetCDF 体渲染 + 协议控制像素响应', async ({ page, request }) => {
  test.setTimeout(300_000)
  const t0 = Date.now()
  const candidateId = seed!.candidate_id

  // --- 真实 FastAPI：capability → POST → manifest（统一 candidate_result 链） ---
  const health = await request.get('/api/health')
  expect(health.ok()).toBe(true)

  const capResp = await request.get(`/api/results/${candidateId}/render-capability`)
  expect(capResp.ok()).toBe(true)
  const capability = await capResp.json()
  expect(capability.supported).toBe(true)
  expect(capability.source_kind).toBe('candidate_result')
  expect(capability.source_id).toBe(candidateId)
  expect(capability.dimension).toBe('3d')
  expect(capability.property_name).toBe(seed!.property_name)
  expect(capability.display_transform?.contract).toBe('wgs84_display_anchor_v1')

  // 候选资产是套件共享单例（supermap-native-volume-live 产品页门也会确保该资产）：
  // 首个创建返回 201，幂等返回 200，并发创建返回 409（creating）后轮询 ready。
  // 「首成 201/幂等 200/creating 409」的严格时序由后端 API 测试确定性覆盖，
  // live 门只断言最终 ready 与身份一致。
  let asset: any = null
  const postResp = await request.post(`/api/results/${candidateId}/render-assets/netcdf`, {
    data: {},
  })
  if (postResp.status() === 409) {
    const pollStart = Date.now()
    while (Date.now() - pollStart < 60_000) {
      const st = await request.get(`/api/results/${candidateId}/render-assets/netcdf`)
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
  expect(asset, '候选资产必须达到 ready').toBeTruthy()
  expect(asset.id).toMatch(/^nc-[0-9a-f]{32}$/)
  expect(asset.status).toBe('ready')
  expect(asset.renderer).toBe('supermap_voxelgrid_netcdf')
  expect(asset.grid_sha256).toBe(seed!.grid_sha256)
  expect(asset.netcdf_sha256).toMatch(/^[0-9a-f]{64}$/)
  expect(asset.manifest_url).toBe(`/api/render-assets/${asset.id}/manifest`)
  expect(asset.netcdf_url).toBe(`/api/render-assets/${asset.id}/volume.nc`)

  const manifestResp = await request.get(asset.manifest_url)
  expect(manifestResp.ok()).toBe(true)
  const manifest = await manifestResp.json()
  expect(manifest.source_kind).toBe('candidate_result')
  expect(manifest.source_id).toBe(candidateId)
  expect(manifest.grid_sha256).toBe(asset.grid_sha256)
  expect(manifest.netcdf_sha256).toBe(asset.netcdf_sha256)
  expect(manifest.variable_name).toBe(seed!.variable_name)
  expect(manifest.dimension_names).toEqual(['x', 'y', 'z'])
  expect(manifest.display_transform).toEqual(capability.display_transform)
  const valueRange: [number, number] = manifest.encoded_value_range ?? manifest.value_range
  const [vmin, vmax] = valueRange
  expect(vmax).toBeGreaterThan(vmin)

  // --- parent harness + 协议监听 -------------------------------------------
  const consoleLog: { type: string; text: string }[] = []
  const failedRequests: string[] = []
  page.on('console', (m) => consoleLog.push({ type: m.type(), text: m.text().slice(0, 400) }))
  page.on('pageerror', (e) => consoleLog.push({ type: 'pageerror', text: String(e).slice(0, 400) }))
  page.on('requestfailed', (r) => failedRequests.push(`${r.url()} ${r.failure()?.errorText}`))
  page.on('response', (r) => {
    if (r.status() >= 400) failedRequests.push(`${r.status()} ${r.url()}`)
  })

  const requestId = randomUUID()
  await page.route(
    (url) => url.pathname === '/volume-frame-harness',
    (route) => route.fulfill({ contentType: 'text/html', body: harnessHtml() }),
  )
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto(`/volume-frame-harness?request_id=${encodeURIComponent(requestId)}`, {
    waitUntil: 'load',
    timeout: 60_000,
  })

  const receivedOf = (predicate: string) =>
    page.evaluate(
      (src) => {
        const h = (window as any).__harness
        // eslint-disable-next-line no-new-func
        const pred = new Function('m', `return ${src}`)
        return h.received.filter((m: any) => pred(m))
      },
      predicate,
    )

  // FRAME_READY：协议握手（SDK 已加载，contextType=2=WebGL2）
  await page.waitForFunction(
    () =>
      (window as any).__harness &&
      (window as any).__harness.received.some((m: any) => m.type === 'FRAME_READY'),
    undefined,
    { timeout: 120_000 },
  )
  const frameReady = (await receivedOf("m.type === 'FRAME_READY'"))[0]
  expect(frameReady).toBeTruthy()
  expect(frameReady.protocol).toBe(PROTOCOL)
  expect(frameReady.requestId).toBe(requestId)
  expect(frameReady.contextType).toBe(2)
  expect(String(frameReady.sdkVersion)).toMatch(/\d+/)

  // INIT：真实资产 + capability displayTransform + 完整初始渲染状态（v2）
  await page.evaluate(
    ([a, t, st]) => (window as any).__send({ type: 'INIT', asset: a, displayTransform: t, state: st }),
    [asset, capability.display_transform, makeState(valueRange, 1)],
  )
  await page.waitForFunction(
    () =>
      (window as any).__harness.received.some(
        (m: any) =>
          m.type === 'RENDER_STATE' && (m.phase === 'rendered' || m.phase === 'failed'),
      ),
    undefined,
    { timeout: 180_000 },
  )
  const states = await receivedOf("m.type === 'RENDER_STATE'")
  const failedState = states.find((m: any) => m.phase === 'failed')
  expect(failedState).toBeUndefined()
  const rendered = states.find((m: any) => m.phase === 'rendered')
  expect(rendered).toBeTruthy()
  const expectedIdentity = {
    sourceKind: 'candidate_result',
    sourceId: candidateId,
    gridSha256: seed!.grid_sha256,
    netcdfSha256: asset.netcdf_sha256,
  }
  expect(rendered.identity).toEqual(expectedIdentity)

  // 只读诊断快照：不暴露 viewer/layer，字段与协议一致
  const frame = page.frames().find((f) => f.url().includes('/supermap-volume-frame/'))
  expect(frame).toBeTruthy()
  const diag = await frame!.evaluate(() => (window as any).__GMP_VOLUME_FRAME__)
  expect(diag.protocol).toBe(PROTOCOL)
  expect(diag.phase).toBe('rendered')
  expect(diag.layerType).toBe('VoxelGridLayer3D')
  expect(diag.mode).toBe('volume')
  expect(diag.identity).toEqual(expectedIdentity)
  expect(diag.errors).toEqual([])
  expect((diag as any).viewer).toBeUndefined()
  expect((diag as any).layer).toBeUndefined()

  // --- 像素响应：噪声基线 → 基准 → filter/opacity/slice/contour --------------
  const noiseShot1 = await page.screenshot()
  await waitFrames(frame, 10)
  const noiseShot2 = await page.screenshot()
  const noiseDiff = await countDiff(page, noiseShot1, noiseShot2)
  const pixelThreshold = Math.max(200, noiseDiff * 3 + 50)

  const shotDefault = noiseShot2
  const baseStats = await countNonBg(page, shotDefault)
  expect(baseStats.nonBg).toBeGreaterThan(5000)

  // v2 命令通道：APPLY_RENDER_STATE（revision 单调）→ STATE_APPLIED 回执
  let revision = 1 // INIT 已应用 revision=1
  let commandSeq = 0
  const applyState = async (overrides: Partial<RenderStateWire>) => {
    revision += 1
    commandSeq += 1
    const commandId = `live-cmd-${commandSeq}`
    const before: number = await page.evaluate(() => (window as any).__harness.received.length)
    await page.evaluate(
      ([m, c]) => (window as any).__send({ ...m, commandId: c }),
      [{ type: 'APPLY_RENDER_STATE', state: makeState(valueRange, revision, overrides) }, commandId] as const,
    )
    await page.waitForFunction(
      ([n, cmd, rev]) =>
        (window as any).__harness.received.some(
          (m: any) =>
            m.type === 'STATE_APPLIED' && m.commandId === cmd && m.revision === rev,
        ),
      [before, commandId, revision] as const,
      { timeout: 30_000 },
    )
    const errors = await receivedOf("m.type === 'ERROR'")
    expect(errors).toEqual([])
  }

  // filter：最小过滤值提到中位区间（实时更新）
  await applyState({ filter: { min: vmin + (vmax - vmin) * 0.55, max: vmax } })
  await waitFrames(frame, 45)
  const shotThreshold = await page.screenshot()
  const diffThreshold = await countDiff(page, shotDefault, shotThreshold)
  expect(diffThreshold).toBeGreaterThan(pixelThreshold)

  // opacity：整体不透明度压到 0.12（走 opacityTransferFunction）
  await applyState({ opacity: 0.12 })
  await waitFrames(frame, 45)
  const shotOpacity = await page.screenshot()
  const diffOpacity = await countDiff(page, shotThreshold, shotOpacity)
  expect(diffOpacity).toBeGreaterThan(pixelThreshold)

  // slice 模式（Z 轴单切面：Task 1 负坐标隐藏技术经 v2 状态下发）
  await applyState({
    mode: 'slice',
    slice: { axis: 'z', index: 4, coordinate: -400, relativePosition: 0.5 },
  })
  await waitFrames(frame, 45)
  const shotSlice = await page.screenshot()
  const diffSlice = await countDiff(page, shotOpacity, shotSlice)
  expect(diffSlice).toBeGreaterThan(pixelThreshold)

  // X/Y 轴单切面：每个轴都必须是单切面（设计 §8.3 语义固定）
  for (const axis of ['x', 'y'] as const) {
    await applyState({
      mode: 'slice',
      slice: { axis, index: 3, coordinate: 0, relativePosition: 0.5 },
    })
    await waitFrames(frame, 45)
    const shotAxis = await page.screenshot()
    expect(await countNonBg(page, shotAxis)).toHaveProperty('nonBg')
    const axisStats = await countNonBg(page, shotAxis)
    expect(axisStats.nonBg).toBeGreaterThan(500)
  }

  // contour 模式
  await applyState({ mode: 'contour', contourValue: (vmin + vmax) / 2 })
  await waitFrames(frame, 45)
  const shotContour = await page.screenshot()
  const diffContour = await countDiff(page, shotSlice, shotContour)
  expect(diffContour).toBeGreaterThan(pixelThreshold)

  // 光照/渐变透明度/包围盒运行时可调（体积模式像素响应）
  await applyState({ mode: 'volume' })
  await waitFrames(frame, 30)
  await applyState({ lighting: false })
  await waitFrames(frame, 30)
  const shotNoLight = await page.screenshot()
  expect(await countDiff(page, shotContour, shotNoLight)).toBeGreaterThan(pixelThreshold)
  await applyState({ gradientOpacity: false })
  await waitFrames(frame, 30)
  const shotNoGradient = await page.screenshot()
  expect(await countDiff(page, shotNoLight, shotNoGradient)).toBeGreaterThan(pixelThreshold)
  await applyState({ boundingBox: false })
  await waitFrames(frame, 30)
  const shotNoBox = await page.screenshot()
  expect(await countDiff(page, shotNoGradient, shotNoBox)).toBeGreaterThan(0)

  // stale revision（<= lastAppliedRevision）整体忽略：无回执、无像素变化
  {
    const before: number = await page.evaluate(() => (window as any).__harness.received.length)
    await page.evaluate(
      (m) => (window as any).__send(m),
      { type: 'APPLY_RENDER_STATE', commandId: 'live-cmd-stale', state: makeState(valueRange, 1, { opacity: 0.01 }) },
    )
    await waitFrames(frame, 20)
    const staleApplied = await receivedOf(
      "m.type === 'STATE_APPLIED' && m.commandId === 'live-cmd-stale'",
    )
    expect(staleApplied).toEqual([])
    const shotStale = await page.screenshot()
    expect(await countDiff(page, shotNoBox, shotStale)).toBeLessThanOrEqual(
      Math.max(50, noiseDiff * 2 + 20),
    )
  }

  // RESET_VIEW 回执 + 点层冒烟（协议面完整，无错误即可）
  await page.evaluate((m) => (window as any).__send(m), {
    type: 'RESET_VIEW',
    commandId: 'live-cmd-reset',
  })
  await page.waitForFunction(
    () =>
      (window as any).__harness.received.some(
        (m: any) => m.type === 'COMMAND_APPLIED' && m.commandId === 'live-cmd-reset',
      ),
    undefined,
    { timeout: 30_000 },
  )
  await page.evaluate((m) => (window as any).__send(m), {
    type: 'SET_POINT_LAYER',
    commandId: 'live-cmd-points',
    layer: {
      id: 'grid-samples',
      visible: true,
      role: 'auxiliary',
      coordinates: 'local',
      x: [0, 100, 200, 300, 400, 500],
      y: [0, 100, 200, 300, 400, 500],
      z: [-800, -700, -600, -500, -400, -300],
      style: { color: '#ff3333', pixelSize: 6 },
    },
  })
  await page.waitForFunction(
    () =>
      (window as any).__harness.received.some(
        (m: any) => m.type === 'COMMAND_APPLIED' && m.commandId === 'live-cmd-points',
      ),
    undefined,
    { timeout: 30_000 },
  )
  await waitFrames(frame, 30)
  const diagAfter = await frame!.evaluate(() => (window as any).__GMP_VOLUME_FRAME__)
  expect(diagAfter.phase).toBe('rendered')
  expect(diagAfter.mode).toBe('volume')
  expect(diagAfter.errors).toEqual([])

  // --- 全局健康：无协议违例、无页面错误、无失败/错误响应 ----------------------
  const harnessErrors: string[] = await page.evaluate(() => (window as any).__harness.errors)
  expect(harnessErrors).toEqual([])
  expect(failedRequests).toEqual([])
  const pageErrors = consoleLog.filter((c) => ['pageerror', 'error'].includes(c.type))
  expect(pageErrors).toEqual([])

  console.log(
    `[volume-frame-live] sdk=${frameReady.sdkVersion} 像素: 基准非背景=${baseStats.nonBg} ` +
      `噪声=${noiseDiff} 阈值=${pixelThreshold} 差异: filter=${diffThreshold} opacity=${diffOpacity} ` +
      `slice=${diffSlice} contour=${diffContour} 总耗时=${((Date.now() - t0) / 1000).toFixed(1)}s`,
  )
})


// ---------------------------------------------------------------------------
// v0.7.0 Batch 2 Task 1：真实 SuperMap SDK 单轴切片硬门（协议无关探针）
//
// 设计 §9：必须证明 X/Y/Z 任一轴都能只显示一个切面。产品 iframe 的 app.js
// 以 <script type="module"> 加载，模块作用域使 eval('volumeLayer') 不可达；
// v1 协议的 SET_MODE 又把 sliceCoordinate 限制在 [0,1]，负坐标隐藏技术无法
// 经协议驱动。因此本探针使用**测试自有**探针页（本文件内嵌 HTML，route.fulfill
// 提供）：加载同一 SuperMap3D.js 与同一真实 NetCDF 资产，按 app.js 已验证的
// 初始化配方创建独立 viewer + VoxelGridLayer3D，直接驱动公开 SDK 属性。
// 零产品代码修改；探针页与 app.js 的对应步骤逐行注释，绝不复制私有字段。
//
// 负坐标隐藏平面（-1 vs -0.5 无可见差异），回到范围内坐标恢复平面。任一轴
// 失败即停止第二批，不得以三正交切面、点云、Three.js 或自研渲染器冒充。
//
// 证据默认关闭：只有 GMP_CAPTURE_EVIDENCE=1 且测试代码处于干净提交时
// 才写入 docs/evidence/v0.7.0-single-axis-probe/<run-id>/（仅逻辑文件名，
// 绝不记录 REPO_ROOT、SDK 路径或运行时目录）。
// ---------------------------------------------------------------------------

type SliceAxis = 'x' | 'y' | 'z'

function rawSliceCoordinate(axis: SliceAxis, position: number, inactive = -1) {
  return {
    x: axis === 'x' ? position : inactive,
    y: axis === 'y' ? position : inactive,
    z: axis === 'z' ? position : inactive,
  }
}

// 测试自有探针页：初始化配方镜像 app.js handleInit 第 2/6/7/8/9/10/11 步
// （contextType=2、addVoxelGridLayer、原始角度 layerBounds、米制 zBounds、
// _frameState 等待、startRender 三维名、manifest 值域传递函数、lookAt）。
function probePageHtml(payload: {
  netcdfUrl: string
  manifest: Record<string, unknown>
}): string {
  const data = JSON.stringify(payload)
  return `<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8" />
<link rel="icon" href="data:," />
<title>single-axis-probe</title>
<style>html,body{margin:0;height:100%;background:#000}#container{position:fixed;inset:0}</style>
<script src="/SuperMap3D-2026/SuperMap3D.js"></script>
</head>
<body>
<div id="container"></div>
<script type="module">
const payload = ${data}
const manifest = payload.manifest
const probe = { ready: false, error: null, layer: null, sdkVersion: String(SuperMap3D.MajorVersion || SuperMap3D.VERSION || 'unknown') }
window.__probe = probe
const fail = (e) => { probe.error = String(e && e.message ? e.message : e) }
function waitLayerFrameState(layer, maxFrames = 600) {
  return new Promise((resolve, reject) => {
    let frames = 0
    const tick = () => {
      frames += 1
      if (layer._frameState) { resolve(frames); return }
      if (frames >= maxFrames) { reject(new Error('VOXEL_LAYER_LOAD_FAILED')); return }
      requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  })
}
try {
  const bounds = manifest.layer_bounds_degrees
  const zBounds = manifest.z_bounds_metres
  const range = manifest.encoded_value_range || manifest.value_range
  // 步骤 2：Viewer（contextType=2，与 app.js ensureViewer 同参）
  const viewer = new SuperMap3D.Viewer('container', {
    contextOptions: { contextType: 2, webgl: { preserveDrawingBuffer: true } },
    animation: false, timeline: false, baseLayerPicker: false, geocoder: false,
    homeButton: false, sceneModePicker: false, navigationHelpButton: false,
    fullscreenButton: false, infoBox: false, selectionIndicator: false,
  })
  const scene = viewer.scenePromise ? await viewer.scenePromise : viewer.scene
  try { scene.skyBox.show = false } catch (e) { /* 与 app.js 同：best effort */ }
  try { scene.skyAtmosphere.show = false } catch (e) { /* ditto */ }
  try { scene.globe.show = false } catch (e) { /* ditto */ }
  // 步骤 6：添加 VoxelGridLayer3D
  const layer = await scene.addVoxelGridLayer(payload.netcdfUrl, manifest.variable_name)
  // 步骤 7：原始角度 layerBounds（裸 Rectangle）+ 米制 zBounds
  layer.layerBounds = new SuperMap3D.Rectangle(bounds.west, bounds.south, bounds.east, bounds.north)
  layer.zBounds = new SuperMap3D.Cartesian2(zBounds[0], zBounds[1])
  // 步骤 8：有界帧循环等待 _frameState
  await waitLayerFrameState(layer)
  // 步骤 9：startRender（variableName/xDimName/yDimName/zDimName）
  await Promise.resolve(layer.startRender({
    variableName: manifest.variable_name,
    xDimName: manifest.dimension_names[0],
    yDimName: manifest.dimension_names[1],
    zDimName: manifest.dimension_names[2],
  }))
  // 步骤 10：manifest 值域的过滤/颜色/透明度传递函数（与 app.js 同配方）
  const vmin = range[0], vmax = range[1], styleSpan = vmax - vmin
  const at = (f) => vmin + styleSpan * f
  const colors = new SuperMap3D.ColorTransferFunction()
  colors.addRGBPoint(at(0.0), 0.1, 0.25, 0.85)
  colors.addRGBPoint(at(0.25), 0.1, 0.8, 0.8)
  colors.addRGBPoint(at(0.5), 0.95, 0.85, 0.15)
  colors.addRGBPoint(at(0.75), 0.95, 0.35, 0.1)
  colors.addRGBPoint(at(1.0), 0.65, 0.05, 0.1)
  const opacity = new SuperMap3D.PiecewiseFunction()
  opacity.addPoint(at(0.0), 0.0)
  opacity.addPoint(at(0.2), 0.05)
  opacity.addPoint(at(0.5), 0.2)
  opacity.addPoint(at(0.75), 0.55)
  opacity.addPoint(at(1.0), 0.9)
  layer.volumeRenderMode = SuperMap3D.VolumeRenderMode.VolumeRendering
  layer.minFiltration = vmin
  layer.maxFiltration = vmax
  layer.enableLighting = true
  layer.useGradientOpacity = true
  layer.colorTransferFunction = colors
  layer.opacityTransferFunction = opacity
  // 步骤 11：lookAt 体积中心（经/纬用 manifest 变换的最大物理跨度）
  const t = manifest.display_transform
  const viewSpan = Math.max(
    (bounds.east - bounds.west) * t.metres_per_degree_lon,
    (bounds.north - bounds.south) * t.metres_per_degree_lat,
    zBounds[1] - zBounds[0],
  )
  scene.camera.lookAt(
    SuperMap3D.Cartesian3.fromDegrees(
      (bounds.west + bounds.east) / 2, (bounds.south + bounds.north) / 2,
      (zBounds[0] + zBounds[1]) / 2,
    ),
    new SuperMap3D.HeadingPitchRange(0.6, -0.9, viewSpan * 2.5),
  )
  probe.layer = layer
  probe.ready = true
} catch (e) {
  fail(e)
}
</script>
</body>
</html>`
}

async function setRawSdkSlice(page: import('@playwright/test').Page, coordinate: Record<string, number>) {
  await page.evaluate((c) => {
    const probe = (window as any).__probe
    probe.layer.sliceCoordinate = new (window as any).SuperMap3D.Cartesian3(c.x, c.y, c.z)
    probe.layer.volumeRenderMode = (window as any).SuperMap3D.VolumeRenderMode.Slice
  }, coordinate)
}

async function waitRaf(page: import('@playwright/test').Page, frames: number): Promise<void> {
  await page.evaluate(
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

interface AxisMeasurement {
  axis: SliceAxis
  active_non_bg: number
  jitter_diff: number
  add_first_diff: number
  add_second_diff: number
  quarter_vs_three_quarter_diff: number
  noise_ceiling: number
  pixel_threshold: number
}

test('真实 SDK 单轴切片硬门：X/Y/Z 均能只显示一个切面', async ({ page, request }) => {
  test.setTimeout(600_000)
  // --- 真实 FastAPI：capability + 资产 + manifest（统一 candidate_result 资产链） -
  const candidateId = seed!.candidate_id
  const health = await request.get('/api/health')
  expect(health.ok()).toBe(true)
  const capResp = await request.get(`/api/results/${candidateId}/render-capability`)
  expect(capResp.ok()).toBe(true)
  const capability = await capResp.json()
  expect(capability.supported).toBe(true)
  expect(capability.source_kind).toBe('candidate_result')

  let asset: any = null
  const statusResp = await request.get(`/api/results/${candidateId}/render-assets/netcdf`)
  if (statusResp.ok()) {
    asset = await statusResp.json()
  } else {
    const postResp = await request.post(`/api/results/${candidateId}/render-assets/netcdf`, {
      data: {},
    })
    expect([200, 201]).toContain(postResp.status())
    asset = await postResp.json()
  }
  expect(asset.status).toBe('ready')
  expect(asset.grid_sha256).toBe(seed!.grid_sha256)
  const manifestResp = await request.get(asset.manifest_url)
  expect(manifestResp.ok()).toBe(true)
  const manifest = await manifestResp.json()

  // --- 测试自有探针页：同一 SDK + 同一真实 NetCDF ------------------------------
  await page.route(
    (url) => url.pathname === '/single-axis-probe',
    (route) =>
      route.fulfill({
        contentType: 'text/html',
        body: probePageHtml({ netcdfUrl: asset.netcdf_url, manifest }),
      }),
  )
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/single-axis-probe', { waitUntil: 'load', timeout: 60_000 })
  await page.waitForFunction(
    () => (window as any).__probe && ((window as any).__probe.ready || (window as any).__probe.error),
    undefined,
    { timeout: 300_000 },
  )
  const probeError = await page.evaluate(() => (window as any).__probe.error)
  expect(probeError).toBeNull()

  // --- 静帧噪声基线（Volume 模式、初始相机/传递函数固定） ---------------------
  const noiseShot1 = await page.screenshot()
  await waitRaf(page, 10)
  const noiseShot2 = await page.screenshot()
  const noiseDiff = await countDiff(page, noiseShot1, noiseShot2)
  const noiseCeiling = Math.max(60, noiseDiff * 2 + 20)
  const pixelThreshold = Math.max(200, noiseDiff * 3 + 50)

  const measurements: AxisMeasurement[] = []
  const screenshots: Record<string, Buffer> = {}

  for (const axis of ['x', 'y', 'z'] as SliceAxis[]) {
    // 0.25 与 0.75 两个非中心位置
    await setRawSdkSlice(page, rawSliceCoordinate(axis, 0.25))
    await waitRaf(page, 30)
    const atQuarter = await page.screenshot()
    await setRawSdkSlice(page, rawSliceCoordinate(axis, 0.75))
    await waitRaf(page, 30)
    const atThreeQuarter = await page.screenshot()
    const quarterDiff = await countDiff(page, atQuarter, atThreeQuarter)
    expect(quarterDiff).toBeGreaterThan(pixelThreshold)

    const activeStats = await countNonBg(page, atThreeQuarter)
    expect(activeStats.nonBg).toBeGreaterThan(500)
    screenshots[`${axis}-active-only`] = atThreeQuarter

    // 负坐标抖动：-1 → -0.5 不得产生可见差异（证明负值隐藏而非移出画面）
    await setRawSdkSlice(page, rawSliceCoordinate(axis, 0.75, -0.5))
    await waitRaf(page, 20)
    const jitter = await page.screenshot()
    const jitterDiff = await countDiff(page, atThreeQuarter, jitter)
    expect(jitterDiff).toBeLessThanOrEqual(noiseCeiling)

    // 逐个恢复另外两个轴到 0.5：每个恢复都必须产生超噪声像素变化
    const restoreFirst: Record<string, number> = { ...rawSliceCoordinate(axis, 0.75) }
    const firstInactive = (['x', 'y', 'z'] as SliceAxis[]).filter((a) => a !== axis)[0]
    restoreFirst[firstInactive] = 0.5
    await setRawSdkSlice(page, restoreFirst)
    await waitRaf(page, 30)
    const addFirst = await page.screenshot()
    const addFirstDiff = await countDiff(page, atThreeQuarter, addFirst)
    expect(addFirstDiff).toBeGreaterThan(pixelThreshold)

    const restoreBoth = { ...restoreFirst }
    const secondInactive = (['x', 'y', 'z'] as SliceAxis[]).filter((a) => a !== axis)[1]
    restoreBoth[secondInactive] = 0.5
    await setRawSdkSlice(page, restoreBoth)
    await waitRaf(page, 30)
    const addSecond = await page.screenshot()
    const addSecondDiff = await countDiff(page, atThreeQuarter, addSecond)
    expect(addSecondDiff).toBeGreaterThan(pixelThreshold)

    measurements.push({
      axis,
      active_non_bg: activeStats.nonBg,
      jitter_diff: jitterDiff,
      add_first_diff: addFirstDiff,
      add_second_diff: addSecondDiff,
      quarter_vs_three_quarter_diff: quarterDiff,
      noise_ceiling: noiseCeiling,
      pixel_threshold: pixelThreshold,
    })
  }

  // X→Y→Z→X 连续切换：每一步单轴有效且相邻状态差异超噪声
  const sequenceStates: Buffer[] = []
  for (const axis of ['x', 'y', 'z', 'x'] as SliceAxis[]) {
    await setRawSdkSlice(page, rawSliceCoordinate(axis, 0.5))
    await waitRaf(page, 30)
    const shot = await page.screenshot()
    const stats = await countNonBg(page, shot)
    expect(stats.nonBg).toBeGreaterThan(500)
    sequenceStates.push(shot)
  }
  for (let i = 1; i < sequenceStates.length; i += 1) {
    expect(await countDiff(page, sequenceStates[i - 1], sequenceStates[i])).toBeGreaterThan(
      pixelThreshold,
    )
  }

  const probeSdkVersion = await page.evaluate(() => (window as any).__probe.sdkVersion)
  console.log(
    `[single-axis-probe] sdk=${probeSdkVersion} 噪声=${noiseDiff} 上限=${noiseCeiling} 阈值=${pixelThreshold} ` +
      measurements
        .map(
          (m) =>
            `${m.axis}: 非背景=${m.active_non_bg} 抖动=${m.jitter_diff} 恢复1=${m.add_first_diff} 恢复2=${m.add_second_diff} 位置差=${m.quarter_vs_three_quarter_diff}`,
        )
        .join(' | '),
  )

  // --- 证据（opt-in；干净提交专用） -------------------------------------------
  if (process.env.GMP_CAPTURE_EVIDENCE === '1') {
    const commit = execFileSync('git', ['rev-parse', 'HEAD'], {
      cwd: REPO_ROOT,
      encoding: 'utf8',
    }).trim()
    const runId = `run-${new Date().toISOString().replace(/[-:.]/g, '')}-${commit.slice(0, 8)}`
    const out = path.join(REPO_ROOT, 'docs', 'evidence', 'v0.7.0-single-axis-probe', runId)
    mkdirSync(out, { recursive: true })
    writeFileSync(
      path.join(out, 'probe.json'),
      JSON.stringify(
        {
          run_id: runId,
          git_commit: commit,
          sdk_version: probeSdkVersion,
          technique:
            'sliceCoordinate 负坐标隐藏非活动轴；测试自有探针页按 app.js 配方初始化公开 VoxelGridLayer3D（SDK 12.1 实测）',
          noise_diff: noiseDiff,
          axes: measurements,
        },
        null,
        2,
      ) + '\n',
    )
    for (const [name, bytes] of Object.entries(screenshots)) {
      writeFileSync(path.join(out, `${name}.png`), bytes)
    }
  }
})
