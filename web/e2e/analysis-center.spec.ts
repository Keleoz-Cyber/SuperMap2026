import { expect, test, type Locator, type Page } from '@playwright/test'
import { installMockApi } from '../src/mocks/platformDemo'
import { MOCK_VOLUME_FRAME_HTML, MOCK_VOLUME_FRAME_PATH } from './mockVolumeFrame'

// v0.8.0 第二批 Task 8：统计与空间分析中心 Mock E2E（设计 §7/§9）。
// 覆盖：微震 profile 全流程（徽标/质量徽标/空间异常非空图/模型对比/模块
// 切换/候选行直达成果页）、电阻率 profile（对数分布说明+非正值排除计数/
// 高低阻空间异常/JSON·CSV 导出下载）、generic_3d 降级（通用三维徽标+缺失
// 原因，无专属模块）、空间分箱点击 → 成果页带 axis/x_range/y_range/dataset
// 查询参数、390×844 无页面级横向溢出、1440×900 主区/右栏并存。
// 每个用例断言 echarts canvas 在 mock 环境真实初始化并绘制（非空白像素）。
// 数值全部来自 platformDemo.ts 的确定性演示合成夹具，绝不冒充真实证据。

const MICRO_CASE_URL = '/#/cases/builtin-microseismic-vx-1911'
const RHO_CASE_URL = '/#/cases/resistivity'

async function installVolumeFrameMock(page: Page): Promise<void> {
  await page.route(
    (url) => url.pathname === MOCK_VOLUME_FRAME_PATH,
    (route) =>
      route.fulfill({ status: 200, contentType: 'text/html', body: MOCK_VOLUME_FRAME_HTML }),
  )
}

/** 断言宿主内 echarts canvas 真实绘制（抽样像素 alpha 非零），而非空容器 */
async function expectCanvasRendered(host: Locator): Promise<void> {
  const canvas = host.locator('canvas').first()
  await expect(canvas).toBeVisible()
  await expect
    .poll(async () =>
      canvas.evaluate((node) => {
        const c = node as HTMLCanvasElement
        const ctx = c.getContext('2d')
        if (!ctx || c.width === 0 || c.height === 0) return 0
        const data = ctx.getImageData(0, 0, c.width, c.height).data
        let painted = 0
        for (let i = 3; i < data.length; i += 400) {
          if (data[i] !== 0) painted += 1
        }
        return painted
      }),
    )
    .toBeGreaterThan(5)
}

/** 从工作台进入分析中心并等待主区就绪 */
async function enterAnalysisCenter(page: Page, caseUrl: string, datasetId: string): Promise<void> {
  await page.goto(caseUrl)
  await page.getByTestId('stage-nav-results').click()
  await page.getByTestId('analysis-center-entry').click()
  await expect(page).toHaveURL(new RegExp(`#\\/datasets\\/${datasetId}\\/analysis`))
  await expect(page.getByTestId('analysis-profile-badge')).toBeVisible()
}

test.describe('v0.8.0 第二批：统计与空间分析中心（mock API）', () => {
  test('微震流程：工作台入口 → 徽标/空间异常/模型对比 → 模块切换 → 候选行直达成果页', async ({
    page,
  }) => {
    await installMockApi(page)
    await installVolumeFrameMock(page)

    // ---- 案例工作台 → 统计与空间分析入口 ----
    await page.goto(MICRO_CASE_URL)
    await expect(page.getByTestId('case-workspace-header')).toContainText('微震速度')
    await page.getByTestId('stage-nav-results').click()
    await page.getByTestId('analysis-center-entry').click()
    await expect(page).toHaveURL(/#\/datasets\/ds-preset\/analysis/)

    // ---- 徽标与案例身份 ----
    await expect(page.getByTestId('analysis-profile-badge')).toContainText('微震速度')
    await expect(page.getByTestId('analysis-quality-badge')).toContainText('数据全部有效')
    await expect(page.getByTestId('analysis-variable')).toContainText('微震速度')
    await expect(page.getByTestId('analysis-variable')).toContainText('km/s')

    // ---- 默认主区 = 空间异常（速度高/低值区域），echarts 真实渲染非空图 ----
    const spatial = page.getByTestId('spatial-feature-panel')
    await expect(spatial).toBeVisible()
    await expect(spatial.locator('h3')).toContainText('速度高/低值区域')
    await expect(page.getByTestId('spatial-anomaly-legend')).toContainText('速度高值区域')
    await expect(page.getByTestId('spatial-anomaly-legend')).toContainText('速度低值区域')
    await expectCanvasRendered(page.getByTestId('spatial-chart'))

    // ---- 模型证据为独立模块，不与当前空间结论争夺主阅读区 ----
    await page.getByTestId('module-nav-item-model_comparison').click()
    const comparison = page.getByTestId('model-comparison-panel')
    await expect(comparison.getByTestId('model-candidate-row')).toHaveCount(1)
    await expect(comparison).toContainText('普通克里金')
    await expect(comparison.getByTestId('badge-materialized')).toBeVisible()
    await expect(comparison.getByTestId('badge-formal')).toBeVisible()

    // ---- 切换分布模块 ----
    await page.getByTestId('module-nav-item-distribution').click()
    await expect(page.getByTestId('distribution-panel')).toBeVisible()
    await expectCanvasRendered(page.getByTestId('distribution-chart'))
    await expect(page.getByTestId('distribution-summary')).toContainText('32 分箱')

    // ---- 切换剖面模块（含轴切换）----
    await page.getByTestId('module-nav-item-profile_slices').click()
    await expect(page.getByTestId('profile-analysis-panel')).toBeVisible()
    await expectCanvasRendered(page.getByTestId('profile-chart'))
    await expect(page.getByTestId('profile-summary')).toContainText('X 轴剖面')
    await page.getByTestId('axis-z').check()
    await expect(page.getByTestId('profile-summary')).toContainText('Z 轴剖面')

    // ---- 点击模型对比候选行 → /results/{id} ----
    await page.getByTestId('module-nav-item-model_comparison').click()
    await page.getByTestId('model-candidate-row').first().click()
    await expect(page).toHaveURL(/#\/results\/cand-1/)
  })

  test('电阻率流程：高低阻空间异常图例 / 对数分布说明 / JSON·CSV 导出下载', async ({
    page,
  }) => {
    await installMockApi(page)
    await installVolumeFrameMock(page)

    await page.goto(RHO_CASE_URL)
    await expect(page.getByTestId('case-workspace-header')).toContainText('地下电阻率')
    await page.getByTestId('stage-nav-results').click()
    await page.getByTestId('analysis-center-entry').click()
    await expect(page).toHaveURL(/#\/datasets\/ds-rho\/analysis/)
    await expect(page.getByTestId('analysis-profile-badge')).toContainText('电阻率')

    // ---- 默认主区 = 空间异常（高/低阻区域）+ 图例 + 非空图 ----
    await expect(page.getByTestId('spatial-feature-panel').locator('h3')).toContainText(
      '高/低阻区域',
    )
    const legend = page.getByTestId('spatial-anomaly-legend')
    await expect(legend).toContainText('高阻区域')
    await expect(legend).toContainText('低阻区域')
    await expect(legend).toContainText('阈值来源')
    await expectCanvasRendered(page.getByTestId('spatial-chart'))

    // ---- 分布模块：对数尺度说明 + 非正值排除计数可见 ----
    await page.getByTestId('module-nav-item-distribution').click()
    const logNote = page.getByTestId('distribution-log-note')
    await expect(logNote).toContainText('对数尺度展示')
    await expect(logNote).toContainText('已排除非正值样本 2 个')
    await expectCanvasRendered(page.getByTestId('distribution-chart'))

    // ---- 导出 JSON/CSV：浏览器下载触发，文件名形态与后端一致 ----
    await page.getByTestId('analysis-export-command').click()
    await expect(page.getByTestId('export-command-json')).toBeVisible()
    const [jsonDownload] = await Promise.all([
      page.waitForEvent('download'),
      page.getByTestId('export-command-json').click(),
    ])
    expect(jsonDownload.suggestedFilename()).toBe('analysis-ds-rho-resistivity.json')
    await expect(page.getByTestId('export-status')).toContainText(
      'analysis-ds-rho-resistivity.json',
    )
    const [csvDownload] = await Promise.all([
      page.waitForEvent('download'),
      page.getByTestId('export-command-csv').click(),
    ])
    expect(csvDownload.suggestedFilename()).toBe('analysis-ds-rho-resistivity.csv')
  })

  test('generic 降级：上传案例显示通用三维与缺失原因，无专属模块', async ({ page }) => {
    await installMockApi(page)

    // ---- 驱动通用上传 dataset 到 validated（与 v0.7 移动端用例同一捷径）----
    await page.goto('/#/cases/case-e2e/datasets/ds-e2e/prepare')
    await page.getByTestId('mapping-value-name').fill('电阻率')
    await page.getByTestId('mapping-submit').click()
    await expect(page.getByTestId('quality-banner')).toContainText('质量校验通过')
    await page.getByTestId('enter-workspace').click()
    await expect(page).toHaveURL(/#\/cases\/case-e2e$/)

    // ---- 分析中心：通用三维徽标 + 缺失原因说明 ----
    await page.getByTestId('stage-nav-results').click()
    await page.getByTestId('analysis-center-entry').click()
    await expect(page).toHaveURL(/#\/datasets\/ds-e2e\/analysis/)
    await expect(page.getByTestId('analysis-profile-badge')).toContainText('通用三维')
    const fallback = page.getByTestId('analysis-generic-fallback')
    await expect(fallback).toBeVisible()
    await expect(fallback).toContainText('通用分析模板')
    await expect(fallback).toContainText('尚未识别出')
    await expect(fallback).not.toContainText('generic_3d')
    await expect(fallback).not.toContainText('CH4_content')
    await expect(fallback).not.toContainText('RHO')

    // ---- 通用模块在，专属模块一律不出现 ----
    await expect(page.getByTestId('module-nav-item-spatial_extent')).toBeVisible()
    await expect(page.getByTestId('module-nav-item-distribution')).toBeVisible()
    await expect(page.getByTestId('module-nav-item-profile_slices')).toBeVisible()
    await expect(page.getByTestId('module-nav-item-axis_trends')).toHaveCount(0)
    await expect(page.getByTestId('module-nav-item-gradient')).toHaveCount(0)
    await expect(page.getByTestId('module-nav-item-spatial_anomaly')).toHaveCount(0)
    await expect(page.getByTestId('module-nav-item-depth_slices')).toHaveCount(0)

    // ---- 默认主区 = 空间视图，echarts 真实渲染；模型对比为解释性空状态 ----
    await expect(page.getByTestId('spatial-feature-panel')).toBeVisible()
    await expectCanvasRendered(page.getByTestId('spatial-chart'))
    await page.getByTestId('module-nav-item-model_comparison').click()
    await expect(page.getByTestId('model-comparison-empty')).toBeVisible()
  })

  test('空间分箱点击 → 导航到物化成果页并带 axis/x_range/y_range/dataset 查询参数', async ({
    page,
  }) => {
    await installMockApi(page)
    await installVolumeFrameMock(page)

    await enterAnalysisCenter(page, RHO_CASE_URL, 'ds-rho')
    await expect(page.getByTestId('spatial-chart')).toBeVisible()
    await expectCanvasRendered(page.getByTestId('spatial-chart'))

    // 点击热力图中心分箱 → 类型化 selection → 成果页路由
    const box = await page.getByTestId('spatial-chart').boundingBox()
    expect(box).not.toBeNull()
    await page.mouse.click(box!.x + box!.width / 2, box!.y + box!.height / 2)

    await expect(page).toHaveURL(/#\/results\/cand-rho-official\?/)
    const url = page.url()
    expect(url).toContain('axis=xy')
    expect(url).toMatch(/x_range=[^&]+/)
    expect(url).toMatch(/y_range=[^&]+/)
    expect(url).toContain('dataset=ds-rho')
  })

  test('移动端 390×844：分析中心无页面级横向溢出，主要操作不被遮挡', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await installMockApi(page)
    await installVolumeFrameMock(page)

    await enterAnalysisCenter(page, RHO_CASE_URL, 'ds-rho')
    await expect(page.getByTestId('analysis-profile-badge')).toContainText('电阻率')
    await expect(page.getByTestId('spatial-chart')).toBeVisible()
    await expectCanvasRendered(page.getByTestId('spatial-chart'))

    // 页面级无横向溢出
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth)
    expect(scrollWidth).toBeLessThanOrEqual(390)

    // 主要操作不被遮挡：导出命令、模块导航、分布切换、导出面板命令均可用
    await expect(page.getByTestId('analysis-export-command')).toBeVisible()
    await expect(page.getByTestId('module-nav')).toBeVisible()
    await page.getByTestId('module-nav-item-distribution').click()
    await expect(page.getByTestId('distribution-chart')).toBeVisible()
    const chartBox = await page.getByTestId('distribution-chart').boundingBox()
    expect(chartBox).not.toBeNull()
    expect(chartBox!.width).toBeLessThanOrEqual(390)
    await page.getByTestId('analysis-export-command').click()
    await expect(page.getByTestId('export-command-json')).toBeVisible()

    // 展开导出区后仍无溢出
    const afterExpand = await page.evaluate(() => document.documentElement.scrollWidth)
    expect(afterExpand).toBeLessThanOrEqual(390)

    await page.screenshot({ path: 'test-results/analysis-center-390x844.png', fullPage: true })
  })

  test('桌面 1440×900：当前分析与上下文证据并存且水平不重叠', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await installMockApi(page)
    await installVolumeFrameMock(page)

    await enterAnalysisCenter(page, MICRO_CASE_URL, 'ds-preset')
    await expect(page.getByTestId('analysis-profile-badge')).toContainText('微震速度')

    const primary = page.getByTestId('primary-area')
    const side = page.getByTestId('context-evidence')
    await expect(primary).toBeVisible()
    await expect(side).toBeVisible()
    const primaryBox = await primary.boundingBox()
    const sideBox = await side.boundingBox()
    expect(primaryBox).not.toBeNull()
    expect(sideBox).not.toBeNull()
    // 并存：右栏在主区右侧且水平不重叠
    expect(sideBox!.x).toBeGreaterThanOrEqual(primaryBox!.x + primaryBox!.width - 1)
    expect(sideBox!.width).toBeGreaterThan(200)
    await expectCanvasRendered(page.getByTestId('spatial-chart'))
  })
})
