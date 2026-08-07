import { expect, test } from '@playwright/test'
import { installMockApi } from '../src/mocks/platformDemo'

// v0.6.1 Task 11 → v0.7.0 第二批 Task 11：mock 产品流程浏览器测试。
// 验证：路由加载、显式物化/资产创建（POST）、iframe v2 协议握手、常驻工具栏
// 完整渲染状态命令、X/Y/Z 正交切片（3D slice 只来自权威剖面响应）、等值面
// 输入、multipart 剖面导出、切片 tab、无 /volume-demo 链接。
// iframe 由本文件的协议 mock 页面扮演（无 SuperMap3D SDK），本测试只证明
// 协议与产品接线正确，绝不宣称真实渲染。

// 协议 mock 子帧：与 web/public/supermap-volume-frame/app.js 同一份
// gmp-supermap-volume/v2 信封纪律（request_id 关联、目标 origin 恒为本源），
// 但不做任何 SDK 调用；INIT 后按 asset 回 RENDER_STATE，命令回 STATE_APPLIED /
// COMMAND_APPLIED，并记录全部父级消息供断言。
const MOCK_FRAME_HTML = `<!doctype html>
<html><head><meta charset="utf-8"></head><body>
<script>
(function () {
  var PROTOCOL = 'gmp-supermap-volume/v2'
  var requestId = new URLSearchParams(window.location.search).get('request_id') || ''
  var received = []
  window.__GMP_MOCK_FRAME__ = { requestId: requestId, received: received }
  function post(msg) {
    var out = { protocol: PROTOCOL, requestId: requestId }
    for (var k in msg) out[k] = msg[k]
    window.parent.postMessage(out, window.location.origin)
  }
  window.addEventListener('message', function (event) {
    var msg = event.data
    if (!msg || msg.protocol !== PROTOCOL || msg.requestId !== requestId) return
    received.push(msg)
    if (msg.type === 'INIT') {
      var asset = msg.asset
      post({
        type: 'RENDER_STATE',
        phase: asset ? 'rendered' : 'unsupported',
        identity: asset
          ? {
              sourceKind: asset.source_kind,
              sourceId: asset.source_id,
              gridSha256: asset.grid_sha256,
              netcdfSha256: asset.netcdf_sha256,
            }
          : null,
      })
    } else if (msg.type === 'APPLY_RENDER_STATE') {
      post({
        type: 'STATE_APPLIED',
        commandId: msg.commandId,
        revision: msg.state.revision,
        appliedState: msg.state,
      })
    } else if (msg.type === 'SET_POINT_LAYER' || msg.type === 'RESET_VIEW') {
      post({ type: 'COMMAND_APPLIED', commandId: msg.commandId, commandType: msg.type })
    }
  })
  post({
    type: 'FRAME_READY',
    sdkVersion: 'mock-frame/0',
    contextType: 2,
    capabilities: {
      singleAxisSlice: true,
      lighting: true,
      gradientOpacity: true,
      boundingBox: true,
      transferFunction: true,
    },
  })
})()
</script>
</body></html>`

interface PostedRequest {
  path: string
  body: unknown
}

interface MockRenderState {
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

interface MockFrameMessage {
  type: string
  layer?: Record<string, unknown>
  state?: MockRenderState
}

test('3D 成果工作台：物化 + 原生体渲染 + 工具栏完整状态 + 正交切片与剖面导出', async ({ page }) => {
  const posts: PostedRequest[] = []
  const sliceExportPosts: { contentType: string }[] = []
  page.on('request', (req) => {
    if (req.method() !== 'POST') return
    const path = new URL(req.url()).pathname
    if (path.includes('slice-exports')) {
      sliceExportPosts.push({ contentType: req.headers()['content-type'] ?? '' })
      return
    }
    let body: unknown = null
    try {
      body = req.postDataJSON()
    } catch {
      // 非 JSON 请求体不记录
    }
    posts.push({ path, body })
  })

  await installMockApi(page)
  // 协议 mock 子帧：同源路由拦截，不加载任何专有 SDK
  await page.route(
    (url) => url.pathname === '/supermap-volume-frame/index.html',
    (route) => route.fulfill({ status: 200, contentType: 'text/html', body: MOCK_FRAME_HTML }),
  )

  // 路由加载：深链直达成果工作台
  await page.goto('/#/results/cand-1')
  await expect(page.getByTestId('native-volume-panel')).toBeVisible()
  await expect(page.getByTestId('create-asset')).toBeVisible()

  // 显式物化恰好一次；创建前绝不隐式 POST 渲染资产
  expect(posts.filter((p) => p.path === '/api/results/cand-1/materialize')).toHaveLength(1)
  expect(posts.filter((p) => p.path.includes('render-assets'))).toHaveLength(0)

  // 显式资产创建：唯一一次 POST，retry_failed=false
  await page.getByTestId('create-asset').click()
  await expect(page.getByTestId('volume-phase')).toContainText('已渲染')
  const assetPosts = posts.filter((p) => p.path === '/api/results/cand-1/render-assets/netcdf')
  expect(assetPosts).toHaveLength(1)
  expect(assetPosts[0].body).toEqual({ retry_failed: false })

  // 协议握手：mock 子帧 FRAME_READY → INIT → RENDER_STATE rendered
  await expect(page.getByTestId('asset-identity')).toContainText('supermap_voxelgrid_netcdf')
  const frame = page.frames().find((f) => f.url().includes('/supermap-volume-frame/index.html'))
  expect(frame).toBeTruthy()
  const frameMessages = async () =>
    (await frame!.evaluate(
      () => (window as unknown as { __GMP_MOCK_FRAME__: { received: MockFrameMessage[] } }).__GMP_MOCK_FRAME__
        .received,
    )) as MockFrameMessage[]
  const appliedStates = async () =>
    (await frameMessages())
      .filter((m) => m.type === 'APPLY_RENDER_STATE' && m.state)
      .map((m) => m.state!)
  expect((await frameMessages()).map((m) => m.type)).toContain('INIT')

  // ------------------------------------------------------------ 常驻工具栏
  // 光照/渐变透明度/包围盒运行时切换
  await page.getByTestId('lighting-toggle').click()
  await page.getByTestId('gradient-opacity-toggle').click()
  await page.getByTestId('bounding-box-toggle').click()
  // 滤波
  await page.getByTestId('filter-min').fill('20')
  await page.getByTestId('filter-max').fill('50')
  await page.getByTestId('filter-apply').click()
  // 色带 → turbo；标度 → 对数
  await page.getByTestId('palette-select').click()
  await page.locator('.el-select-dropdown__item:has-text("turbo")').first().click()
  await page.getByTestId('log-scale').click()
  // 不透明度：点击滑轨中部（真实指针交互，el-slider 按比例取值）
  const runway = page.getByTestId('opacity-slider').locator('.el-slider__runway')
  const runwayBox = await runway.boundingBox()
  expect(runwayBox).toBeTruthy()
  await page.mouse.click(
    runwayBox!.x + runwayBox!.width * 0.5,
    runwayBox!.y + runwayBox!.height / 2,
  )

  // 等值面输入只在 contour 模式显示；值进入状态
  await expect(page.getByTestId('contour-value')).toHaveCount(0)
  await page.getByTestId('mode-contour').click()
  await expect(page.getByTestId('contour-value')).toBeVisible()
  await page.getByTestId('contour-value').fill('30')
  await page.getByTestId('contour-apply').click()

  // 最后一条完整状态命令：全部字段齐备（revision 递增、滤波/色带/标度/开关生效）
  await expect
    .poll(async () => (await appliedStates()).at(-1))
    .toMatchObject({
      mode: 'contour',
      contourValue: 30,
      filter: { min: 20, max: 50 },
      lighting: false,
      gradientOpacity: false,
      boundingBox: false,
    })
  const lastComplete = (await appliedStates()).at(-1)!
  expect(lastComplete.revision).toBeGreaterThan(1)
  expect(lastComplete.opacity).toBeLessThan(1)
  expect(lastComplete.colorTransferFunction).toHaveLength(5)
  expect(lastComplete.colorTransferFunction[0].color).toBe('#30123b') // turbo 端点
  // log 标度几何间隔
  expect(lastComplete.colorTransferFunction[2].value).toBeCloseTo(Math.sqrt(20 * 50))

  // ------------------------------------------------------------ 正交切片
  await page.getByTestId('mode-slice').click()
  // z 中位索引（z 长度 5 → 2）引导加载；剖面坐标标签来自权威响应
  await expect(page.getByTestId('slice-coordinate-label')).toContainText('Z = -400')
  await expect(page.getByTestId('slice-controls')).toBeVisible()
  await expect(page.getByTestId('slice-statistics')).toContainText('有效 11 / NoData 1')

  // X/Y/Z 轴选择：3D slice 状态带权威 relativePosition
  await page.getByTestId('axis-x').click()
  await expect(page.getByTestId('slice-coordinate-label')).toContainText('X = -141')
  await expect
    .poll(async () => (await appliedStates()).at(-1)?.slice)
    .toMatchObject({ axis: 'x', index: 1, coordinate: -141, relativePosition: 0.5 })

  await page.getByTestId('axis-y').click()
  await expect(page.getByTestId('slice-coordinate-label')).toContainText('Y = 292')
  await expect
    .poll(async () => (await appliedStates()).at(-1)?.slice)
    .toMatchObject({ axis: 'y', index: 1, coordinate: 292, relativePosition: 1 / 3 })

  await page.getByTestId('axis-z').click()
  await expect(page.getByTestId('slice-coordinate-label')).toContainText('Z = -400')
  // 步进到下一层：commit 立即生效
  await page.getByTestId('slice-next').click()
  await expect(page.getByTestId('slice-coordinate-label')).toContainText('Z = -200')
  await expect
    .poll(async () => (await appliedStates()).at(-1)?.slice)
    .toMatchObject({ axis: 'z', index: 3, coordinate: -200, relativePosition: 0.75 })

  // 离开切片模式：切片控件与剖面分析消失；等值面输入也不可见
  await page.getByTestId('mode-volume').click()
  await expect(page.getByTestId('slice-controls')).toHaveCount(0)
  await expect(page.getByTestId('slice-analysis')).toHaveCount(0)
  await expect(page.getByTestId('contour-value')).toHaveCount(0)

  // 辅助采样点默认关闭，打开后发送 visible=true 的点层
  await expect(page.getByTestId('aux-points-toggle')).not.toBeChecked()
  await page.getByTestId('aux-points-toggle').check()
  await expect
    .poll(async () => {
      const layers = (await frameMessages()).filter((m) => m.type === 'SET_POINT_LAYER')
      return layers.at(-1)?.layer
    })
    .toMatchObject({ id: 'grid-samples', role: 'auxiliary', visible: true, coordinates: 'local' })

  // 剖面导出：multipart POST（axis/index/image），保持在最后（触发下载语义）
  await page.getByTestId('mode-slice').click()
  await expect(page.getByTestId('slice-coordinate-label')).toContainText('Z = -400')
  await page.getByTestId('export-slice').click()
  await expect.poll(() => sliceExportPosts.length).toBe(1)
  expect(sliceExportPosts[0].contentType).toContain('multipart/form-data')

  // 正式选择/导出控件保留；专业分析对 IDW 成果禁用
  await expect(page.getByTestId('professional-disabled')).toBeVisible()
  await expect(page.getByTestId('selection-submit')).toBeVisible()
  await expect(page.getByTestId('export-button')).toBeVisible()

  // 切片 tab 保留既有行为
  await page.getByTestId('tab-slices').click()
  await expect(page.getByTestId('slice-label')).toContainText('Z = -800 m')

  // 无 /volume-demo 链接（旧自定义渲染入口已移除）
  expect(await page.locator('a[href*="volume-demo"]').count()).toBe(0)
  await page.goto('/')
  expect(await page.locator('a[href*="volume-demo"]').count()).toBe(0)
})

test('内置电阻率：产品内导入权威规则网格 → 生成 NetCDF 资产 → 原生渲染', async ({ page }) => {
  // v0.6.1：全新运行时未登记 legacy 渲染源 → 页内显式导入入口（multipart CSV）→
  // 登记成功后面板翻转为可生成资产 → 显式创建 → 协议握手渲染。
  const importPosts: { contentType: string }[] = []
  page.on('request', (req) => {
    if (req.method() === 'POST' && new URL(req.url()).pathname.includes('render-sources/import')) {
      importPosts.push({ contentType: req.headers()['content-type'] ?? '' })
    }
  })

  await installMockApi(page)
  await page.route(
    (url) => url.pathname === '/supermap-volume-frame/index.html',
    (route) => route.fulfill({ status: 200, contentType: 'text/html', body: MOCK_FRAME_HTML }),
  )

  await page.goto('/#/case/resistivity')

  // 未登记：稳定原因码 + 显式导入入口；绝无创建资产入口
  await expect(page.getByTestId('unsupported-reason')).toContainText(
    'LEGACY_RENDER_SOURCE_NOT_REGISTERED',
  )
  await expect(page.getByTestId('legacy-import')).toBeVisible()
  await expect(page.getByTestId('legacy-import-submit')).toBeDisabled()
  await expect(page.getByTestId('create-asset')).toHaveCount(0)

  // 上传权威规则网格 CSV（X,Y,Z,RHO）并显式导入
  await page.getByTestId('legacy-import-file').setInputFiles({
    name: 'grid.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('X,Y,Z,RHO\n0,0,0,1\n10,0,0,2\n'),
  })
  await page.getByTestId('legacy-import-submit').click()
  expect(importPosts).toHaveLength(1)
  expect(importPosts[0].contentType).toContain('multipart/form-data')

  // 登记身份展示，导入入口不再显示；面板转为可生成资产
  await expect(page.getByTestId('legacy-import-identity')).toBeVisible()
  await expect(page.getByTestId('legacy-import')).toHaveCount(0)
  await expect(page.getByTestId('create-asset')).toBeVisible()

  // 既有 NativeVolumePanel 流程：显式创建 → 握手 → 渲染
  await page.getByTestId('create-asset').click()
  await expect(page.getByTestId('volume-phase')).toContainText('已渲染')
  await expect(page.getByTestId('asset-identity')).toContainText('supermap_voxelgrid_netcdf')
})
