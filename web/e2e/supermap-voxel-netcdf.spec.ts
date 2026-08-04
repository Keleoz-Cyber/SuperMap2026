import { test, expect } from '@playwright/test'
import { createHash } from 'node:crypto'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * v0.6.1 VoxelGridLayer3D + NetCDF POC 浏览器验收（真实平台，非 mock）。
 *
 * 依赖本机 FastAPI 平台（127.0.0.1:8000，含 /supermap-voxel-netcdf 页面与
 * supermap-voxel-netcdf-export API）与固定三维成果
 * 35348bb3-be03-4862-b764-ee165ae0c7dc。平台不可达时整组 skip（CI 冒烟安全）。
 */

const BASE = process.env.VOXEL_POC_BASE_URL ?? 'http://127.0.0.1:8000'
const RESULT_ID = '35348bb3-be03-4862-b764-ee165ae0c7dc'
const GRID_SHA256 = '54c313c9328f8c06e079efacf8099a4b07446e284121369a10b846c4b71bb69f'
const PAGE_URL = `${BASE}/supermap-voxel-netcdf/index.html?result_id=${RESULT_ID}&grid_sha256=${GRID_SHA256}&clean=1`
const EVIDENCE_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../docs/evidence/v0.6.1-voxelgrid-netcdf-poc')

const PANEL_MASK = [0, 0, 680, 560] // 左上状态面板区域，像素统计排除

interface PixelCount { nonBg: number; total: number }

async function countNonBg(page: any, shot: Buffer): Promise<PixelCount> {
  const dataUrl = 'data:image/png;base64,' + shot.toString('base64')
  return page.evaluate(async ([src, mask]: [string, number[]]) => {
    const img = new Image()
    await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = src })
    const c = document.createElement('canvas')
    c.width = img.width
    c.height = img.height
    const ctx = c.getContext('2d')!
    ctx.drawImage(img, 0, 0)
    const d = ctx.getImageData(0, 0, c.width, c.height).data
    let nonBg = 0
    for (let y = 0; y < c.height; y++) {
      for (let x = 0; x < c.width; x++) {
        if (x >= mask[0] && x <= mask[2] && y >= mask[1] && y <= mask[3]) continue
        const i = (y * c.width + x) * 4
        if (d[i] > 12 || d[i + 1] > 12 || d[i + 2] > 12) nonBg++
      }
    }
    return { nonBg, total: c.width * c.height - (mask[2] - mask[0]) * (mask[3] - mask[1]) }
  }, [dataUrl, PANEL_MASK])
}

async function countDiff(page: any, a: Buffer, b: Buffer): Promise<number> {
  const pair = [a, b].map((buf) => 'data:image/png;base64,' + buf.toString('base64'))
  return page.evaluate(async ([srcA, srcB, mask]: [string, string, number[]]) => {
    const load = (src: string) => new Promise<HTMLImageElement>((res, rej) => {
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
    for (let y = 0; y < ia.height; y++) {
      for (let x = 0; x < ia.width; x++) {
        if (x >= mask[0] && x <= mask[2] && y >= mask[1] && y <= mask[3]) continue
        const i = (y * A.w + x) * 4
        if (Math.abs(A.d[i] - B.d[i]) > 10 || Math.abs(A.d[i + 1] - B.d[i + 1]) > 10 || Math.abs(A.d[i + 2] - B.d[i + 2]) > 10) diff++
      }
    }
    return diff
  }, [...pair, PANEL_MASK])
}

async function waitFrames(page: any, frames: number): Promise<void> {
  await page.evaluate(
    (n) =>
      new Promise<void>((resolve) => {
        let i = 0
        const tick = () => {
          i += 1
          i >= n ? resolve() : requestAnimationFrame(tick)
        }
        requestAnimationFrame(tick)
      }),
    frames,
  )
}

test.describe('v0.6.1 VoxelGridLayer3D + NetCDF POC（真实平台）', () => {
  let platformUp = false
  let manifest: any = null

  test.beforeAll(async ({ request }) => {
    try {
      const health = await request.get(`${BASE}/api/health`, { timeout: 5000 })
      platformUp = health.ok()
    } catch {
      platformUp = false
    }
    if (platformUp) {
      const resp = await request.get(`${BASE}/api/results/${RESULT_ID}/supermap-voxel-netcdf-export`, { timeout: 30000 })
      expect(resp.ok()).toBeTruthy()
      manifest = (await resp.json()).manifest
    }
  })

  test('原生体渲染五态像素验收', async ({ page }) => {
    test.skip(!platformUp, `平台 ${BASE} 不可达（本规格需要真实 FastAPI 平台与固定成果）`)

    const consoleLog: { type: string; text: string }[] = []
    const failedRequests: string[] = []
    page.on('console', (m) => consoleLog.push({ type: m.type(), text: m.text().slice(0, 400) }))
    page.on('pageerror', (e) => consoleLog.push({ type: 'pageerror', text: String(e).slice(0, 400) }))
    page.on('requestfailed', (r) => failedRequests.push(`${r.url()} ${r.failure()?.errorText}`))
    page.on('response', (r) => {
      const u = r.url()
      if (r.status() >= 400 && (u.includes('.nc') || u.includes('SuperMap3D-2026') || u.includes('Workers') || u.includes('Assets'))) {
        failedRequests.push(`${r.status()} ${u}`)
      }
    })

    mkdirSync(EVIDENCE_DIR, { recursive: true })
    const startedAt = new Date().toISOString()

    await page.goto(PAGE_URL, { waitUntil: 'load', timeout: 60000 })
    await page.waitForFunction(
      () => (window as any).__VOXEL_POC__ && ['rendered', 'failed'].includes((window as any).__VOXEL_POC__.phase),
      undefined,
      { timeout: 90000 },
    )
    const poc = await page.evaluate(() => JSON.parse(JSON.stringify((window as any).__VOXEL_POC__)))
    expect(poc.phase).toBe('rendered')
    expect(poc.layerType).toBe('VoxelGridLayer3D')
    expect(poc.renderMode).toBe('VolumeRendering')
    expect(poc.identity.resultId).toBe(RESULT_ID)
    expect(poc.identity.gridSha256).toBe(GRID_SHA256)
    expect(poc.errors).toEqual([])

    const env = await page.evaluate(() => {
      const gl = document.createElement('canvas').getContext('webgl2')
      const ext = gl && gl.getExtension('WEBGL_debug_renderer_info')
      return {
        webgl2: !!gl,
        gpuRenderer: ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : 'n/a',
        userAgent: navigator.userAgent,
        devicePixelRatio: window.devicePixelRatio,
        viewport: [window.innerWidth, window.innerHeight],
      }
    })

    // 噪声基线：静止画面连拍两次
    const noiseShot1 = await page.screenshot()
    await waitFrames(page, 10)
    const noiseShot2 = await page.screenshot()
    const noiseDiff = await countDiff(page, noiseShot1, noiseShot2)
    const pixelThreshold = Math.max(200, noiseDiff * 3 + 50)

    // 01 基准
    const shotDefault = await page.screenshot()
    const baseStats = await countNonBg(page, shotDefault)
    expect(baseStats.nonBg).toBeGreaterThan(5000)

    // 02 阈值：最小过滤值提到中位区间
    await page.evaluate(() => {
      const l = (window as any).__layer
      const mid = l.minFiltration + (l.maxFiltration - l.minFiltration) * 0.55
      l.minFiltration = mid
    })
    await waitFrames(page, 45)
    const shotThreshold = await page.screenshot()
    const diffThreshold = await countDiff(page, shotDefault, shotThreshold)
    expect(diffThreshold).toBeGreaterThan(pixelThreshold)

    // 03 不透明度：重建 opacityTransferFunction（opaqueRate 属性本构建包不进 uniform）
    await page.evaluate(() => {
      const l = (window as any).__layer
      const o = new (window as any).SuperMap3D.PiecewiseFunction()
      o.addPoint(l.minFiltration, 0.12)
      o.addPoint(l.maxFiltration, 0.12)
      l.opacityTransferFunction = o
    })
    await waitFrames(page, 45)
    const shotOpacity = await page.screenshot()
    const diffOpacity = await countDiff(page, shotThreshold, shotOpacity)
    expect(diffOpacity).toBeGreaterThan(pixelThreshold)

    // 04 Slice
    await page.evaluate(() => {
      ;(window as any).__layer.volumeRenderMode = (window as any).SuperMap3D.VolumeRenderMode.Slice
    })
    await waitFrames(page, 45)
    const shotSlice = await page.screenshot()
    const diffSlice = await countDiff(page, shotOpacity, shotSlice)
    expect(diffSlice).toBeGreaterThan(pixelThreshold)

    // 05 ContourValue
    await page.evaluate(() => {
      ;(window as any).__layer.volumeRenderMode = (window as any).SuperMap3D.VolumeRenderMode.ContourValue
    })
    await waitFrames(page, 45)
    const shotContour = await page.screenshot()
    const diffContour = await countDiff(page, shotSlice, shotContour)
    expect(diffContour).toBeGreaterThan(pixelThreshold)

    expect(failedRequests).toEqual([])
    const pageErrors = consoleLog.filter((c) => ['pageerror', 'error'].includes(c.type))
    expect(pageErrors).toEqual([])

    // 证据落盘
    writeFileSync(path.join(EVIDENCE_DIR, '01-volume-default.png'), shotDefault)
    writeFileSync(path.join(EVIDENCE_DIR, '02-volume-threshold.png'), shotThreshold)
    writeFileSync(path.join(EVIDENCE_DIR, '03-volume-opacity.png'), shotOpacity)
    writeFileSync(path.join(EVIDENCE_DIR, '04-slice.png'), shotSlice)
    writeFileSync(path.join(EVIDENCE_DIR, '05-contour.png'), shotContour)
    writeFileSync(path.join(EVIDENCE_DIR, 'console.json'), JSON.stringify(consoleLog, null, 2))
    writeFileSync(path.join(EVIDENCE_DIR, 'network.json'), JSON.stringify({ failedRequests, note: '仅记录 .nc/SDK/Workers/Assets 的 4xx/5xx 与请求失败' }, null, 2))
    writeFileSync(path.join(EVIDENCE_DIR, 'export-manifest.json'), JSON.stringify(manifest, null, 2))
    writeFileSync(
      path.join(EVIDENCE_DIR, 'evidence.json'),
      JSON.stringify(
        {
          startedAtUtc: startedAt,
          baseUrl: BASE,
          resultId: RESULT_ID,
          gridSha256: GRID_SHA256,
          netcdfSha256: manifest?.netcdf_sha256,
          layerType: poc.layerType,
          renderMode: poc.renderMode,
          identity: poc.identity,
          noiseFloorPixels: noiseDiff,
          pixelThreshold,
          nonBackground: { default: baseStats.nonBg },
          diffs: {
            'default->threshold': diffThreshold,
            'threshold->opacity': diffOpacity,
            'opacity->slice': diffSlice,
            'slice->contour': diffContour,
          },
          environment: env,
          manifestFileSha256: manifest
            ? createHash('sha256').update(JSON.stringify(manifest)).digest('hex')
            : null,
        },
        null,
        2,
      ),
    )
  })
})
