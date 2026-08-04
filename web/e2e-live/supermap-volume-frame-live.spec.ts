import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * v0.6.1 Task 9 live 验收：隔离 SuperMap3D iframe 运行时 + gmp-supermap-volume/v1 协议。
 *
 * 真实链路：便携合成规则网格 CSV → Task 5 CLI 原子登记（隔离 GEOMODELING_DATA_DIR）
 * → 真实 FastAPI capability/POST/manifest（Task 6/7）→ 轻量 parent harness 打开
 * /supermap-volume-frame/index.html 并收发协议消息。断言：
 *
 *   FRAME_READY（contextType=2）、RENDER_STATE.phase==rendered、identity 与
 *   source/grid/NetCDF 哈希一致、layerType==VoxelGridLayer3D、mode==volume、
 *   无 pageerror/unhandledrejection/资源 4xx/5xx、画布有非背景像素，
 *   filter/opacity/slice/contour 各产生超过静帧噪声的像素变化。
 *
 * 不碰默认运行时目录；uvicorn 生命周期由 Playwright webServer 管理，结束无进程残留。
 */

const HERE = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(HERE, '../..')
const PROTOCOL = 'gmp-supermap-volume/v1'
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

// 便携合成规则网格：6×7×8 笛卡尔格点，光滑三维场（约 [10, 610]）。
function syntheticGridCsv(): string {
  const rows = ['x,y,z,value']
  for (let ix = 0; ix < 6; ix += 1) {
    for (let iy = 0; iy < 7; iy += 1) {
      for (let iz = 0; iz < 8; iz += 1) {
        const x = ix * 100
        const y = iy * 100
        const z = -800 + iz * 100
        const value = 310 + 280 * Math.sin(x / 220) * Math.cos(y / 260) + 20 * Math.sin(z / 90)
        rows.push(`${x},${y},${z},${value.toFixed(6)}`)
      }
    }
  }
  return `${rows.join('\n')}\n`
}

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

let registration: { grid_sha256: string; shape: number[] } | null = null

test.beforeAll(() => {
  const dataDir = assertIsolatedDataDir()
  const fixtureDir = path.join(dataDir, 'live-fixtures')
  mkdirSync(fixtureDir, { recursive: true })
  const csvPath = path.join(fixtureDir, 'legacy-resistivity-grid.csv')
  writeFileSync(csvPath, syntheticGridCsv(), 'utf8')
  // Task 5 真实登记链路：便携 CSV → 原子登记 render-sources/builtin_legacy/resistivity
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
  expect(registration!.shape).toEqual([6, 7, 8])
})

test('隔离 SuperMap 帧：真实 NetCDF 体渲染 + 协议控制像素响应', async ({ page, request }) => {
  test.setTimeout(300_000)
  const t0 = Date.now()

  // --- 真实 FastAPI：capability → POST（Task 6/7）→ manifest -----------------
  const health = await request.get('/api/health')
  expect(health.ok()).toBe(true)

  const capResp = await request.get('/api/cases/resistivity/render-capability')
  expect(capResp.ok()).toBe(true)
  const capability = await capResp.json()
  expect(capability.supported).toBe(true)
  expect(capability.source_kind).toBe('builtin_legacy')
  expect(capability.source_id).toBe('resistivity')
  expect(capability.dimension).toBe('3d')
  expect(capability.property_name).toBe('RHO')
  expect(capability.display_transform?.contract).toBe('wgs84_display_anchor_v1')

  const postResp = await request.post('/api/cases/resistivity/render-assets/netcdf', { data: {} })
  expect(postResp.status()).toBe(201)
  const asset = await postResp.json()
  expect(asset.id).toMatch(/^nc-[0-9a-f]{32}$/)
  expect(asset.status).toBe('ready')
  expect(asset.renderer).toBe('supermap_voxelgrid_netcdf')
  expect(asset.grid_sha256).toBe(registration!.grid_sha256)
  expect(asset.netcdf_sha256).toMatch(/^[0-9a-f]{64}$/)
  expect(asset.manifest_url).toBe(`/api/render-assets/${asset.id}/manifest`)
  expect(asset.netcdf_url).toBe(`/api/render-assets/${asset.id}/volume.nc`)

  const manifestResp = await request.get(asset.manifest_url)
  expect(manifestResp.ok()).toBe(true)
  const manifest = await manifestResp.json()
  expect(manifest.source_kind).toBe('builtin_legacy')
  expect(manifest.source_id).toBe('resistivity')
  expect(manifest.grid_sha256).toBe(asset.grid_sha256)
  expect(manifest.netcdf_sha256).toBe(asset.netcdf_sha256)
  expect(manifest.variable_name).toBe('RHO')
  expect(manifest.dimension_names).toEqual(['x', 'y', 'z'])
  expect(manifest.display_transform).toEqual(capability.display_transform)
  const [vmin, vmax] = manifest.encoded_value_range ?? manifest.value_range
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

  // INIT：真实资产 + capability displayTransform
  await page.evaluate(
    ([a, t]) => (window as any).__send({ type: 'INIT', asset: a, displayTransform: t }),
    [asset, capability.display_transform],
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
    sourceKind: 'builtin_legacy',
    sourceId: 'resistivity',
    gridSha256: registration!.grid_sha256,
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

  const sendAndWaitAck = async (msg: Record<string, unknown>) => {
    const before: number = await page.evaluate(() => (window as any).__harness.received.length)
    await page.evaluate((m) => (window as any).__send(m), msg)
    await page.waitForFunction((n) => (window as any).__harness.received.length > n, before, {
      timeout: 30_000,
    })
    const errors = await receivedOf("m.type === 'ERROR'")
    expect(errors).toEqual([])
  }

  // filter：最小过滤值提到中位区间（实时更新）
  await sendAndWaitAck({ type: 'SET_FILTER', min: vmin + (vmax - vmin) * 0.55, max: vmax })
  await waitFrames(frame, 45)
  const shotThreshold = await page.screenshot()
  const diffThreshold = await countDiff(page, shotDefault, shotThreshold)
  expect(diffThreshold).toBeGreaterThan(pixelThreshold)

  // opacity：整体不透明度压到 0.12（走 opacityTransferFunction）
  await sendAndWaitAck({ type: 'SET_OPACITY', opacity: 0.12 })
  await waitFrames(frame, 45)
  const shotOpacity = await page.screenshot()
  const diffOpacity = await countDiff(page, shotThreshold, shotOpacity)
  expect(diffOpacity).toBeGreaterThan(pixelThreshold)

  // slice 模式
  await sendAndWaitAck({ type: 'SET_MODE', mode: 'slice' })
  await waitFrames(frame, 45)
  const shotSlice = await page.screenshot()
  const diffSlice = await countDiff(page, shotOpacity, shotSlice)
  expect(diffSlice).toBeGreaterThan(pixelThreshold)

  // contour 模式
  await sendAndWaitAck({ type: 'SET_MODE', mode: 'contour' })
  await waitFrames(frame, 45)
  const shotContour = await page.screenshot()
  const diffContour = await countDiff(page, shotSlice, shotContour)
  expect(diffContour).toBeGreaterThan(pixelThreshold)

  // 恢复 volume + RESET_VIEW + 点层冒烟（协议面完整，无错误即可）
  await sendAndWaitAck({ type: 'SET_MODE', mode: 'volume' })
  await sendAndWaitAck({ type: 'RESET_VIEW' })
  await sendAndWaitAck({
    type: 'SET_POINT_LAYER',
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
