import { expect, type APIRequestContext, type Frame, type Page } from '@playwright/test'
import { createHash } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { inflateRawSync } from 'node:zlib'

/**
 * v0.7.0 第二批 Task 12：三源（32³/64³ 基准、内置电阻率 legacy、微震预置官方
 * 成果）共用的真实 SDK 渲染门原语。协议一律 gmp-supermap-volume/v2；
 * 3D slice 状态只认 STATE_APPLIED 回执里的权威载荷；剖面 ZIP 校验四文件、
 * CSV 真实轴坐标、统计一致、manifest 哈希与无路径/凭据泄漏。
 */

export const VOLUME_PROTOCOL_V2 = 'gmp-supermap-volume/v2'

export type SliceAxisName = 'x' | 'y' | 'z'

// ---------------------------------------------------------------------------
// 协议探针（v2）：捕获 STATE_APPLIED 的 mode/slice/revision 供权威断言
// ---------------------------------------------------------------------------

export async function installLiveProbe(page: Page): Promise<void> {
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
          revision: d.revision ?? null,
          mode: d.appliedState?.mode ?? null,
          slice: d.appliedState?.slice ?? null,
          capabilities: d.capabilities ?? null,
        })
      }
    })
  }, VOLUME_PROTOCOL_V2)
}

export function probeMessages(page: Page): Promise<any[]> {
  return page.evaluate(() => (window as any).__liveProbe.messages)
}

export function probeCount(page: Page): Promise<number> {
  return page.evaluate(() => (window as any).__liveProbe.messages.length)
}

// ---------------------------------------------------------------------------
// 像素工具（与 v0.6.1 各 live 门同口径）
// ---------------------------------------------------------------------------

export async function countNonBg(page: Page, shot: Buffer): Promise<{ nonBg: number; total: number }> {
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

export async function countDiff(page: Page, a: Buffer, b: Buffer): Promise<number> {
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
export async function waitFrames(frame: Frame, frames: number): Promise<void> {
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
// 命令执行：协议回执 + 像素稳定等待（settle 轮询上限 20s，超时如实记录）
// ---------------------------------------------------------------------------

export interface LiveCommandResult {
  totalMs: number
  settled: boolean
}

export async function runLiveCommand(
  page: Page,
  shot: () => Promise<Buffer>,
  noiseDiff: number,
  act: () => Promise<void>,
): Promise<LiveCommandResult & { shot: Buffer }> {
  const cmdStart = Date.now()
  const before = await probeCount(page)
  await act()
  await page.waitForFunction((n) => (window as any).__liveProbe.messages.length > n, before, {
    timeout: 30_000,
  })
  let previous = await shot()
  let settled = false
  const settleStart = Date.now()
  while (Date.now() - settleStart < 20_000) {
    await page.waitForTimeout(250)
    const next = await shot()
    const d = await countDiff(page, previous, next)
    if (d <= Math.max(50, noiseDiff * 2)) {
      settled = true
      previous = next
      break
    }
    previous = next
  }
  return { totalMs: Date.now() - cmdStart, settled, shot: previous }
}

// ---------------------------------------------------------------------------
// 正交切片 UI 驱动与权威回执等待
// ---------------------------------------------------------------------------

export async function selectSliceAxis(page: Page, axis: SliceAxisName): Promise<void> {
  await page.getByTestId(`axis-${axis}`).click()
}

async function readSliceIndex(page: Page): Promise<number> {
  return Number(((await page.getByTestId('slice-index-value').textContent()) ?? '').trim())
}

/** prev/next 步进到目标索引（真实点击；每步断言索引文本变化）。 */
export async function setSliceIndex(page: Page, target: number): Promise<void> {
  let guard = 0
  for (;;) {
    const current = await readSliceIndex(page)
    if (current === target) return
    if (guard++ > 100) throw new Error(`setSliceIndex →${target} 超过步数上限（当前 ${current}）`)
    const delta = target > current ? 1 : -1
    await page.getByTestId(delta > 0 ? 'slice-next' : 'slice-prev').click()
    await expect.poll(() => readSliceIndex(page), { timeout: 5_000 }).toBe(current + delta)
  }
}

/**
 * 权威剖面等待：API 响应坐标 → 面板坐标标签一致；最后一条带 slice 的
 * STATE_APPLIED 回执必须精确匹配 {axis,index,coordinate,relativePosition}。
 * 返回 API 分析响应（含三轴元数据/统计）。
 */
export async function waitSliceApplied(
  page: Page,
  request: APIRequestContext,
  frame: Frame,
  assetId: string,
  axis: SliceAxisName,
  index: number,
): Promise<any> {
  const resp = await request.get(
    `/api/render-assets/${assetId}/slice-analysis?axis=${axis}&index=${index}`,
  )
  expect(resp.ok()).toBe(true)
  const analysis = await resp.json()
  const coordinate = analysis.slice.coordinate
  await expect(page.getByTestId('slice-coordinate-label')).toContainText(
    `${axis.toUpperCase()} = ${coordinate}`,
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
    .toMatchObject({
      axis,
      index,
      coordinate,
      relativePosition: analysis.slice.sdk_relative_position,
    })
  // 回执后再等几帧让像素落地
  await waitFrames(frame, 6)
  return analysis
}

// ---------------------------------------------------------------------------
// 统计捕获与不变性
// ---------------------------------------------------------------------------

export async function captureSliceStatistics(
  request: APIRequestContext,
  assetId: string,
  axis: SliceAxisName,
  index: number,
): Promise<Record<string, unknown>> {
  const resp = await request.get(
    `/api/render-assets/${assetId}/slice-analysis?axis=${axis}&index=${index}`,
  )
  expect(resp.ok()).toBe(true)
  const analysis = await resp.json()
  expect(analysis.statistics.valid_count + analysis.statistics.nodata_count).toBe(
    analysis.statistics.total_count,
  )
  return analysis.statistics
}

// ---------------------------------------------------------------------------
// 控件驱动（工具栏真实交互）
// ---------------------------------------------------------------------------

export async function clickSliderRunwayAt(page: Page, testId: string, fraction: number): Promise<void> {
  const runway = page.getByTestId(testId).locator('.el-slider__runway')
  const box = await runway.boundingBox()
  if (!box) throw new Error(`${testId} 滑轨不可见`)
  await page.mouse.click(box.x + box.width * fraction, box.y + box.height / 2)
}

export async function selectPalette(page: Page, palette: string): Promise<void> {
  await page.getByTestId('palette-select').click()
  await page.locator(`.el-select-dropdown__item:has-text("${palette}")`).first().click()
}

// ---------------------------------------------------------------------------
// ZIP 读取与剖面分析包校验
// ---------------------------------------------------------------------------

/** 最小 ZIP 读取（中央目录 + 本地头；stored/deflate），返回条目名 → 内容。 */
export function readZipEntries(buf: Buffer): Map<string, Buffer> {
  const EOCD_SIG = 0x06054b50
  const CD_SIG = 0x02014b50
  const LH_SIG = 0x04034b50
  let eocd = -1
  for (let i = buf.length - 22; i >= Math.max(0, buf.length - 22 - 0xffff); i--) {
    if (buf.readUInt32LE(i) === EOCD_SIG) {
      eocd = i
      break
    }
  }
  if (eocd < 0) throw new Error('ZIP 结束记录（EOCD）未找到')
  const count = buf.readUInt16LE(eocd + 10)
  let offset = buf.readUInt32LE(eocd + 16)
  const out = new Map<string, Buffer>()
  for (let n = 0; n < count; n++) {
    if (buf.readUInt32LE(offset) !== CD_SIG) throw new Error('ZIP 中央目录损坏')
    const method = buf.readUInt16LE(offset + 10)
    const compSize = buf.readUInt32LE(offset + 20)
    const nameLen = buf.readUInt16LE(offset + 28)
    const extraLen = buf.readUInt16LE(offset + 30)
    const commentLen = buf.readUInt16LE(offset + 32)
    const name = buf.subarray(offset + 46, offset + 46 + nameLen).toString('utf8')
    const localOffset = buf.readUInt32LE(offset + 42)
    if (buf.readUInt32LE(localOffset) !== LH_SIG) throw new Error('ZIP 本地头损坏')
    const lNameLen = buf.readUInt16LE(localOffset + 26)
    const lExtraLen = buf.readUInt16LE(localOffset + 28)
    const dataStart = localOffset + 30 + lNameLen + lExtraLen
    const raw = buf.subarray(dataStart, dataStart + compSize)
    out.set(name, method === 0 ? Buffer.from(raw) : inflateRawSync(raw))
    offset += 46 + nameLen + extraLen + commentLen
  }
  return out
}

function sha256(buf: Buffer): string {
  return createHash('sha256').update(buf).digest('hex')
}

/**
 * Python str(float) 文本等价（服务端 CSV 由 Python f-string 写出）：
 * 整数值浮点带 `.0` 后缀；其余用 JS 最短往返表示（与 CPython repr 同口径，
 * 本合同坐标/值域范围内一致）。
 */
function pyFloatText(v: unknown): string {
  const n = Number(v)
  if (Number.isInteger(n)) return `${n}.0`
  return String(n)
}

export interface SliceZipExpectation {
  /** 同一 axis/index 的 slice-analysis API 响应 */
  analysis: any
  /** 已渲染身份（asset/grid/NetCDF 必须与渲染一致） */
  identity: { assetId: string; gridSha256: string; netcdfSha256: string }
}

/**
 * 权威剖面 ZIP 校验：恰好四文件；CSV 真实轴坐标与 API 逐格一致；
 * statistics.json 与 API 一致；manifest 身份/哈希/剖面坐标一致；
 * PNG 字节 SHA 与 manifest 一致且 provenance=client_echarts_canvas；
 * 全部文本条目无盘符/UNC/.runtime/凭据字样。返回 manifest 供证据记录。
 */
export function verifySliceAnalysisZip(
  zipBuf: Buffer,
  exp: SliceZipExpectation,
): Record<string, unknown> {
  expect(zipBuf.subarray(0, 2).toString()).toBe('PK')
  const entries = readZipEntries(zipBuf)
  expect([...entries.keys()].sort()).toEqual([
    'manifest.json',
    'slice.csv',
    'slice.png',
    'statistics.json',
  ])
  const analysis = exp.analysis

  // statistics.json 与 API 完全一致
  const stats = JSON.parse(entries.get('statistics.json')!.toString('utf8'))
  expect(stats).toEqual(analysis.statistics)

  // CSV：表头真实轴名；行优先逐格坐标/值/掩码与 API 一致
  const csvBytes = entries.get('slice.csv')!
  const csvLines = csvBytes.toString('utf8').split('\n')
  expect(csvLines[0]).toBe('x,y,z,value,is_nodata')
  const s = analysis.slice
  const expectedLines = ['x,y,z,value,is_nodata']
  for (let r = 0; r < s.row_coordinates.length; r += 1) {
    for (let c = 0; c < s.column_coordinates.length; c += 1) {
      const coords: Record<string, unknown> = {
        [s.fixed_axis]: s.coordinate,
        [s.row_axis]: s.row_coordinates[r],
        [s.column_axis]: s.column_coordinates[c],
      }
      const xyz = `${pyFloatText(coords.x)},${pyFloatText(coords.y)},${pyFloatText(coords.z)}`
      expectedLines.push(
        s.nodata_mask[r][c] ? `${xyz},,true` : `${xyz},${pyFloatText(s.values[r][c])},false`,
      )
    }
  }
  expect(csvLines).toEqual([...expectedLines, ''])

  // manifest：格式/身份/剖面/统计/文件哈希
  const manifest = JSON.parse(entries.get('manifest.json')!.toString('utf8'))
  expect(manifest.format_version).toBe('slice-analysis/v1')
  expect(manifest.export_kind).toBe('slice_analysis')
  expect(manifest.image_provenance).toBe('client_echarts_canvas')
  expect(manifest.asset_identity).toEqual({
    asset_id: exp.identity.assetId,
    source_kind: analysis.asset_identity.source_kind,
    source_id: analysis.asset_identity.source_id,
    grid_sha256: exp.identity.gridSha256,
    netcdf_sha256: exp.identity.netcdfSha256,
  })
  expect(manifest.slice).toEqual({
    fixed_axis: s.fixed_axis,
    index: s.index,
    coordinate: s.coordinate,
  })
  expect(manifest.statistics).toEqual(analysis.statistics)
  expect(manifest.statistics_contract.std).toBe('population(ddof=0)')
  const pngBytes = entries.get('slice.png')!
  expect(manifest.files['slice.png'].sha256).toBe(sha256(pngBytes))
  expect(manifest.files['slice.png'].size_bytes).toBe(pngBytes.length)
  expect(manifest.files['slice.csv'].sha256).toBe(sha256(csvBytes))
  expect(manifest.files['statistics.json'].sha256).toBe(
    sha256(entries.get('statistics.json')!),
  )
  expect(pngBytes.subarray(0, 8)).toEqual(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))

  // 泄漏扫描：文本条目绝无盘符/UNC/.runtime/凭据字样
  const allText = ['slice.csv', 'statistics.json', 'manifest.json']
    .map((name) => entries.get(name)!.toString('utf8'))
    .join('\n')
  expect(allText).not.toMatch(/[A-Za-z]:[\\/]/)
  expect(allText).not.toContain('\\\\')
  expect(allText).not.toContain('.runtime')
  expect(allText).not.toMatch(/token|secret|password/i)

  return manifest as Record<string, unknown>
}

// ---------------------------------------------------------------------------
// 三源共用门序列（体积 → X/Y/Z 剖面 → 等值面 → 控件 → 统计不变性 → 导出）
// ---------------------------------------------------------------------------

export interface V070GateParams {
  page: Page
  request: APIRequestContext
  frame: Frame
  /** volume-frame 元素截图（完整帧，含离轴剖面） */
  shot: () => Promise<Buffer>
  /** 证据截图落盘（name 不含扩展名） */
  saveShot: (name: string, buf: Buffer) => void
  assetId: string
  identity: { assetId: string; gridSha256: string; netcdfSha256: string }
  valueRange: [number, number]
  /** 权威有效值是否全为正（profile.log_available） */
  logAvailable: boolean
  /** 导出剖面轴/索引；默认 z 中位 */
  exportAxis?: SliceAxisName
  exportIndex?: number
}

export interface V070GateReport {
  noiseDiff: number
  pixelThreshold: number
  baseNonBg: number
  controlDiffs: Record<string, number>
  sliceGates: Record<
    string,
    { quarterIndex: number; threeQuarterIndex: number; quarterNonBg: number; diff: number }
  >
  sliceModeNonBg: number
  contourNonBg: number
  statsInvariant: boolean
  exportManifest: Record<string, unknown>
  timings: Record<string, number>
  unsettledCommands: string[]
}

export async function runV070RenderGates(params: V070GateParams): Promise<V070GateReport> {
  const { page, request, frame, shot, saveShot, assetId, identity, valueRange, logAvailable } = params
  const [vmin, vmax] = valueRange
  const unsettled: string[] = []
  const timings: Record<string, number> = {}
  const controlDiffs: Record<string, number> = {}
  const sliceGates: V070GateReport['sliceGates'] = {}

  // --- 轴元数据（z/0 轻量响应即可拿到三轴长度） ------------------------------
  const axesResp = await request.get(`/api/render-assets/${assetId}/slice-analysis?axis=z&index=0`)
  expect(axesResp.ok()).toBe(true)
  const axesMeta = (await axesResp.json()).axes as Record<
    SliceAxisName,
    { length: number; coordinates: number[]; unit: string }
  >
  const mid = (a: SliceAxisName) => Math.floor((axesMeta[a].length - 1) / 2)
  const quarter = (a: SliceAxisName) => Math.floor((axesMeta[a].length - 1) / 4)
  const threeQuarter = (a: SliceAxisName) => Math.floor((3 * (axesMeta[a].length - 1)) / 4)

  // --- 静帧噪声基线 + 基准非背景 ---------------------------------------------
  const noiseShot1 = await shot()
  await waitFrames(frame, 10)
  const noiseShot2 = await shot()
  const noiseDiff = await countDiff(page, noiseShot1, noiseShot2)
  const pixelThreshold = Math.max(200, noiseDiff * 3 + 50)
  const controlThreshold = Math.max(80, noiseDiff * 2 + 20)

  let previous = noiseShot2
  const baseStats = await countNonBg(page, previous)
  expect(baseStats.nonBg).toBeGreaterThan(2000)
  saveShot('volume', previous)

  // 统计参照：渲染控件绝不改变权威统计（服务端从原始网格重算）
  const statsBefore = await captureSliceStatistics(request, assetId, 'z', mid('z'))

  const command = async (name: string, act: () => Promise<void>, gateDiff = true) => {
    const result = await runLiveCommand(page, shot, noiseDiff, act)
    if (!result.settled) unsettled.push(name)
    timings[name] = result.totalMs
    if (gateDiff) {
      const diff = await countDiff(page, previous, result.shot)
      controlDiffs[name] = diff
      expect(diff, `${name} 必须有超过静帧噪声的像素响应`).toBeGreaterThan(controlThreshold)
    }
    previous = result.shot
    return result
  }

  // --- X/Y/Z 剖面门 -----------------------------------------------------------
  const sliceEntry = await runLiveCommand(page, shot, noiseDiff, () =>
    page.getByTestId('mode-slice').click(),
  )
  timings['slice-mode'] = sliceEntry.totalMs
  if (!sliceEntry.settled) unsettled.push('slice-mode')
  previous = sliceEntry.shot

  const bootstrap = await waitSliceApplied(page, request, frame, assetId, 'z', mid('z'))
  expect(bootstrap.axes.z.length).toBe(axesMeta.z.length)
  await expect(page.getByTestId('slice-heatmap')).toBeVisible()
  await expect(page.getByTestId('slice-valid-count')).toContainText(/有效 [1-9]/)
  const sliceModeStats = await countNonBg(page, previous)
  expect(sliceModeStats.nonBg, '剖面模式必须有非背景体数据像素').toBeGreaterThan(500)

  for (const axis of ['x', 'y', 'z'] as const) {
    await selectSliceAxis(page, axis)
    await waitSliceApplied(page, request, frame, assetId, axis, mid(axis))

    await setSliceIndex(page, quarter(axis))
    await waitSliceApplied(page, request, frame, assetId, axis, quarter(axis))
    await expect(page.getByTestId('slice-valid-count')).toContainText(/有效 [1-9]/)
    const shotQuarter = await shot()
    const quarterStats = await countNonBg(page, shotQuarter)
    expect(quarterStats.nonBg, `${axis} 剖面必须有非背景体数据像素`).toBeGreaterThan(500)
    saveShot(`slice-${axis}-q${quarter(axis)}`, shotQuarter)

    await setSliceIndex(page, threeQuarter(axis))
    await waitSliceApplied(page, request, frame, assetId, axis, threeQuarter(axis))
    const shotThreeQuarter = await shot()
    saveShot(`slice-${axis}-q${threeQuarter(axis)}`, shotThreeQuarter)
    const diff = await countDiff(page, shotQuarter, shotThreeQuarter)
    expect(diff, `${axis} 两个索引之间必须有超过噪声的像素响应`).toBeGreaterThan(pixelThreshold)
    sliceGates[axis] = {
      quarterIndex: quarter(axis),
      threeQuarterIndex: threeQuarter(axis),
      quarterNonBg: quarterStats.nonBg,
      diff,
    }
    previous = shotThreeQuarter
  }

  // --- 等值面门 ---------------------------------------------------------------
  const preContour = previous
  await command('contour', () => page.getByTestId('mode-contour').click(), false)
  const contourStats = await countNonBg(page, previous)
  expect(contourStats.nonBg, '等值面必须有非背景像素').toBeGreaterThan(500)
  controlDiffs['contour'] = await countDiff(page, preContour, previous)
  expect(controlDiffs['contour'], '等值面与剖面之间必须有超过噪声的像素差异').toBeGreaterThan(
    pixelThreshold,
  )
  saveShot('contour', previous)

  // --- 回体积模式：光照/渐变透明度/包围盒只在本模式验收 ------------------------
  await command('restore-volume', () => page.getByTestId('mode-volume').click(), false)

  await command('palette-turbo', () => selectPalette(page, 'turbo'))
  if (logAvailable) {
    // 单选组点击「已是当前值」的选项不发射事件：先读 UI 真实选中态再决定顺序
    // （Element Plus 2.14 el-radio-button 激活类为 is-active）
    const logChecked = await page
      .getByTestId('log-scale')
      .evaluate((el) => el.classList.contains('is-active'))
    if (logChecked) {
      await command('scale-linear', () => page.getByTestId('linear-scale').click())
      await command('scale-log', () => page.getByTestId('log-scale').click())
    } else {
      await command('scale-log', () => page.getByTestId('log-scale').click())
      await command('scale-linear', () => page.getByTestId('linear-scale').click())
    }
  } else {
    await expect(page.getByTestId('log-scale')).toHaveClass(/is-disabled/)
  }
  const filterMin = vmin + (vmax - vmin) * 0.55
  await command('filter', async () => {
    await page.getByTestId('filter-min').fill(filterMin.toFixed(6))
    await page.getByTestId('filter-max').fill(vmax.toFixed(6))
    await page.getByTestId('filter-apply').click()
  })
  await command('opacity', () => clickSliderRunwayAt(page, 'opacity-slider', 0.5))
  await command('lighting-off', () => page.getByTestId('lighting-toggle').click())
  await command('gradient-off', () => page.getByTestId('gradient-opacity-toggle').click())
  await command('bounding-box-off', () => page.getByTestId('bounding-box-toggle').click())

  // 统计不变性：palette/log/linear/filter/opacity/lighting/gradient/bbox 之后
  const statsAfter = await captureSliceStatistics(request, assetId, 'z', mid('z'))
  expect(statsAfter).toEqual(statsBefore)

  // 恢复默认渲染状态（滤波全值域/不透明/光照/渐变/包围盒）；
  // 不透明度恢复用键盘 End（el-slider 的 Home/End 键盘处理在 button-wrapper 上，
  // 不在根元素）；可访问交互，确定性到最大值
  await command('filter-restore', async () => {
    await page.getByTestId('filter-min').fill(String(vmin))
    await page.getByTestId('filter-max').fill(String(vmax))
    await page.getByTestId('filter-apply').click()
  }, false)
  await command(
    'opacity-restore',
    () => page.getByTestId('opacity-slider').locator('.el-slider__button-wrapper').press('End'),
    false,
  )
  await command('lighting-on', () => page.getByTestId('lighting-toggle').click(), false)
  await command('gradient-on', () => page.getByTestId('gradient-opacity-toggle').click(), false)
  await command('bounding-box-on', () => page.getByTestId('bounding-box-toggle').click(), false)

  // --- 剖面分析包导出（每源一份，真实浏览器下载事件） --------------------------
  const exportAxis = params.exportAxis ?? 'z'
  const exportIdx = params.exportIndex ?? mid(exportAxis)
  const reenter = await runLiveCommand(page, shot, noiseDiff, () =>
    page.getByTestId('mode-slice').click(),
  )
  timings['slice-reenter'] = reenter.totalMs
  previous = reenter.shot
  const analysis = await waitSliceApplied(page, request, frame, assetId, exportAxis, exportIdx)
  await expect(page.getByTestId('export-slice')).toBeEnabled()
  const downloadPromise = page.waitForEvent('download', { timeout: 60_000 })
  await page.getByTestId('export-slice').click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe('slice-analysis.zip')
  const zipBuf = await readFile(await download.path())
  const exportManifest = verifySliceAnalysisZip(zipBuf, { analysis, identity })

  // 收尾回体积模式
  await command('restore-volume-final', () => page.getByTestId('mode-volume').click(), false)

  return {
    noiseDiff,
    pixelThreshold,
    baseNonBg: baseStats.nonBg,
    controlDiffs,
    sliceGates,
    sliceModeNonBg: sliceModeStats.nonBg,
    contourNonBg: contourStats.nonBg,
    statsInvariant: true,
    exportManifest,
    timings,
    unsettledCommands: unsettled,
  }
}
