import { expect, test } from '@playwright/test'
import { installMockApi } from '../src/mocks/platformDemo'

// v0.6.1 Task 11：mock 产品流程浏览器测试。
// 验证：路由加载、显式物化/资产创建（POST）、iframe 协议握手、控件命令、切片 tab、
// 无 /volume-demo 链接。iframe 由本文件的协议 mock 页面扮演（无 SuperMap3D SDK），
// 本测试只证明协议与产品接线正确，绝不宣称真实渲染。

// 协议 mock 子帧：与 web/public/supermap-volume-frame/app.js 同一份
// gmp-supermap-volume/v1 信封纪律（request_id 关联、目标 origin 恒为本源），
// 但不做任何 SDK 调用；INIT 后按 asset 回 RENDER_STATE，并记录全部父级命令供断言。
const MOCK_FRAME_HTML = `<!doctype html>
<html><head><meta charset="utf-8"></head><body>
<script>
(function () {
  var PROTOCOL = 'gmp-supermap-volume/v1'
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
    }
  })
  post({ type: 'FRAME_READY', sdkVersion: 'mock-frame/0', contextType: 2 })
})()
</script>
</body></html>`

interface PostedRequest {
  path: string
  body: unknown
}

interface MockFrameMessage {
  type: string
  layer?: Record<string, unknown>
}

test('3D 成果工作台：显式物化 + 原生体渲染面板 + 协议握手 + 控件与切片', async ({ page }) => {
  const posts: PostedRequest[] = []
  page.on('request', (req) => {
    if (req.method() !== 'POST') return
    let body: unknown = null
    try {
      body = req.postDataJSON()
    } catch {
      // 非 JSON 请求体不记录
    }
    posts.push({ path: new URL(req.url()).pathname, body })
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
  expect((await frameMessages()).map((m) => m.type)).toContain('INIT')

  // 控件：rendered 后启用，命令经桥发送
  await expect(page.getByTestId('mode-slice')).toBeEnabled()
  await page.getByTestId('mode-slice').click()
  await page.getByTestId('filter-min').fill('10')
  await page.getByTestId('filter-max').fill('50')
  await page.getByTestId('filter-apply').click()
  await page.getByTestId('opacity-slider').fill('0.5')
  // 辅助采样点默认关闭，打开后发送 visible=true 的点层
  await expect(page.getByTestId('aux-points-toggle')).not.toBeChecked()
  await page.getByTestId('aux-points-toggle').check()

  // 命令经 postMessage 异步到达子帧：最后发送的是 visible=true 点层，
  // 轮询直至其到齐（此前命令必然已全部到达）
  await expect
    .poll(async () => {
      const layers = (await frameMessages()).filter((m) => m.type === 'SET_POINT_LAYER')
      return layers.at(-1)?.layer
    })
    .toMatchObject({ id: 'grid-samples', role: 'auxiliary', visible: true, coordinates: 'local' })

  const received = await frameMessages()
  const types = received.map((m) => m.type)
  expect(types).toContain('INIT')
  expect(types).toContain('SET_MODE')
  expect(types).toContain('SET_FILTER')
  expect(types).toContain('SET_OPACITY')
  expect(types).toContain('SET_POINT_LAYER')

  // 正式选择/导出/专业分析控件保留
  await expect(page.getByTestId('professional-entry')).toBeVisible()
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
