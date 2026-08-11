import { expect, test } from '@playwright/test'
import { installMockApi } from '../src/mocks/platformDemo'
import { MOCK_VOLUME_FRAME_HTML } from './mockVolumeFrame'

// v0.6.1 Task 11 → v0.7.0 第二批 Task 11：mock 产品流程浏览器测试。
// 验证：路由加载、显式物化/资产创建（POST）、iframe v2 协议握手、常驻工具栏
// 完整渲染状态命令、X/Y/Z 正交切片（3D slice 只来自权威剖面响应）、等值面
// 输入、multipart 剖面导出、切片 tab、无 /volume-demo 链接。
// iframe 由 mockVolumeFrame.ts 的协议 mock 页面扮演（无 SuperMap3D SDK），
// 本测试只证明协议与产品接线正确，绝不宣称真实渲染。
// v0.8.0：内置电阻率 legacy 导入用例随入口 410 退役改写为退役合同断言。

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
    (route) => route.fulfill({ status: 200, contentType: 'text/html', body: MOCK_VOLUME_FRAME_HTML }),
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
  // v0.9.0 V6：资产身份在证据窗「数据溯源」标签
  await page.getByTestId('ge-tab-provenance').click()
  await expect(page.getByTestId('ge-asset-identity')).toContainText('supermap_voxelgrid_netcdf')
  await page.getByTestId('ge-tab-overview').click()
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
  // v0.9.0 V6：INIT 初始状态光照/渐变透明度默认关闭，包围盒默认开启
  const initMsg = (await frameMessages()).find((m) => m.type === 'INIT')
  expect(initMsg?.state).toMatchObject({ lighting: false, gradientOpacity: false, boundingBox: true })
  // 光照/渐变透明度/包围盒运行时切换（默认关 → 打开；包围盒默认开 → 关闭）
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
      lighting: true,
      gradientOpacity: true,
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
  // v0.9.0：导出与发布归入证据与溯源抽屉，先展开再断言
  await expect(page.getByTestId('model-evaluation-entry')).toBeVisible()
  await expect(page.getByTestId('selection-submit')).toBeVisible()
  await page.getByTestId('ge-tab-provenance').click()
  await expect(page.getByTestId('export-button')).toBeVisible()

  // 切片 tab 保留既有行为
  await page.getByTestId('tab-slices').click()
  await expect(page.getByTestId('slice-label')).toContainText('Z = -800 m')

  // 无 /volume-demo 链接（旧自定义渲染入口已移除）
  expect(await page.locator('a[href*="volume-demo"]').count()).toBe(0)
  await page.goto('/')
  expect(await page.locator('a[href*="volume-demo"]').count()).toBe(0)
})

test('内置电阻率：旧 legacy/S3M 渲染入口类型化退役（410），统一工作台无导入入口', async ({ page }) => {
  // v0.8.0 Task 6：电阻率迁移为 builtin_preset 散点预置后，旧 legacy 渲染
  // 注册/资产/体元路由一律 410 LEGACY_RESISTIVITY_RETIRED，绝不返回旧 S3M
  // 数值；/#/case/resistivity 兼容别名重定向到统一案例工作台。
  await installMockApi(page)

  // 退役合同：任何方法/载荷一律 410 + 稳定错误码（页内 fetch 走 mock 路由）
  await page.goto('/')
  const retired: [string, string][] = [
    ['GET', '/api/cases/resistivity/render-capability'],
    ['GET', '/api/cases/resistivity/render-assets/netcdf'],
    ['POST', '/api/cases/resistivity/render-assets/netcdf'],
    ['POST', '/api/cases/resistivity/render-sources/import'],
    ['GET', '/api/cases/resistivity/voxel-cells'],
  ]
  for (const [method, path] of retired) {
    const result = await page.evaluate(
      async ([m, p]) => {
        const resp = await fetch(p as string, { method: m as string })
        return { status: resp.status, body: await resp.json() }
      },
      [method, path],
    )
    expect(result.status, `${method} ${path} 必须 410`).toBe(410)
    expect(result.body.error?.code).toBe('LEGACY_RESISTIVITY_RETIRED')
  }

  // 兼容别名 → 统一工作台（builtin_preset）；旧导入/未注册原因码入口不存在
  await page.goto('/#/case/resistivity')
  await expect(page).toHaveURL(/#\/cases\/resistivity/)
  await expect(page.getByTestId('case-workspace-header')).toContainText('地下电阻率')
  await expect(page.getByTestId('legacy-import')).toHaveCount(0)
  await expect(page.getByTestId('unsupported-reason')).toHaveCount(0)
})
