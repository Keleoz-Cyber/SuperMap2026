import { expect, test, type Locator, type Page } from '@playwright/test'
import { installMockApi } from '../src/mocks/platformDemo'
import { MOCK_VOLUME_FRAME_HTML, MOCK_VOLUME_FRAME_PATH } from './mockVolumeFrame'

// v0.8.0 第三批 Task 9：瓦斯含量预置案例的统一产品流程（mock API）。
// 首页三案例卡（gas active + builtin_preset 徽标，无暂缓/DAT/legacy 文案）→
// gas 统一工作台（builtin_preset：validated 58 行 X/Y/Z -> CH4_content、官方
// 成果已物化）→ 官方成果页（算法 ordinary_kriging、网格 151×333×12、NetCDF
// 面板显式创建资产 → 已渲染、X/Y/Z 正交剖面控件、剖面分析入口）→ 统计与
// 空间分析中心（gas_content 徽标、ml/g、含量分布、高/低含量区域）→ 390×844
// 无页面级横向溢出。
// iframe 由 mockVolumeFrame.ts 的协议 mock 子帧扮演（无 SuperMap3D SDK）：
// 本规格只证明产品接线与协议正确，真实像素验收在
// e2e-live/gas-preset-live.spec.ts。数值全部来自 platformDemo.ts 的确定性
// 演示合成夹具与入库公开合同，绝不冒充真实证据。

const GAS_CARD = '.case-card:has-text("煤层瓦斯")'

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

test.describe('v0.8.0 第三批瓦斯含量预置（mock API）', () => {
  test('首页三案例卡 → gas 工作台 → 官方成果页（NetCDF 面板 + X/Y/Z 控件）', async ({ page }) => {
    await installMockApi(page)
    await installVolumeFrameMock(page)

    // ---- 首页：三个预置案例卡同在；gas 为 active + builtin_preset ----
    await page.goto('/')
    await expect(page.locator('.case-card:has-text("地下电阻率")')).toHaveCount(1)
    await expect(page.locator('.case-card:has-text("微震速度")')).toHaveCount(1)
    const card = page.locator(GAS_CARD)
    await expect(card).toHaveCount(1)
    await expect(card).not.toHaveClass(/disabled/)
    await expect(card).toContainText('散点预置 · 官方基线成果')
    await expect(card).toContainText('标准化散点 · 58 个合格样品')
    await expect(card).toContainText('局部线性米制坐标')
    await expect(card).toContainText('ml/g')
    // 旧 legacy 瓦斯卡与旧流程语样绝不出现
    await expect(card).not.toContainText('暂缓')
    await expect(card).not.toContainText('DAT')
    await expect(card).not.toContainText('legacy')
    await expect(page.locator('body')).not.toContainText('暂缓')
    await expect(page.getByText('导入微震 DAT')).toHaveCount(0)

    // ---- gas 统一案例工作台（builtin_preset 四区同构）----
    await card.getByTestId('enter-case-workspace').click()
    await expect(page).toHaveURL(/#\/cases\/gas$/)
    await expect(page.getByTestId('case-workspace-header')).toContainText('煤层瓦斯')
    await expect(page.getByTestId('case-workspace-header')).toContainText('CSV 预置')
    await expect(page.getByTestId('workspace-overview')).toBeVisible()
    // 数据摘要：主阅读层使用用户语言，不暴露状态枚举或字段映射实现。
    await expect(page.getByTestId('workspace-data')).toContainText('质量检查通过')
    await expect(page.getByTestId('workspace-data')).toContainText('58')
    await expect(page.getByTestId('workspace-data')).toContainText('瓦斯含量')
    await expect(page.getByTestId('workspace-data')).toContainText('ml/g')
    // 官方成果与新建实验两条命令并存
    await expect(page.getByTestId('open-official-result')).toContainText('查看官方成果')
    await page.getByTestId('stage-nav-experiments').click()
    await expect(page.getByTestId('workspace-experiments')).toBeVisible()
    await expect(page.getByTestId('new-experiment')).toBeVisible()
    await page.getByTestId('stage-nav-results').click()
    await expect(page.getByTestId('workspace-results')).toContainText('官方成果已就绪')
    // 旧 legacy 页面嵌入块与导入入口不存在
    await expect(page.getByTestId('workspace-rho-block')).toHaveCount(0)
    await expect(page.getByTestId('legacy-import')).toHaveCount(0)

    // ---- 官方成果页：算法身份 + 显式资产 → 渲染状态 ----
    await page.getByTestId('open-official-result').click()
    await expect(page).toHaveURL(/#\/results\/cand-gas-official/)
    await expect(page.getByTestId('v6-result-summary')).toContainText('普通克里金')
    await expect(page.getByTestId('v6-result-summary')).toContainText('三维')
    await expect(page.getByTestId('v6-result-summary')).toContainText('151 × 333 × 12')
    await expect(page.getByTestId('native-volume-panel')).toBeVisible()
    // NetCDF 资产懒创建：显式创建入口 → 已渲染
    await page.getByTestId('create-asset').click()
    await expect(page.getByTestId('volume-phase')).toContainText('已渲染')
    await page.getByTestId('ge-tab-provenance').click()
    await expect(page.getByTestId('ge-asset-identity')).toContainText('supermap_voxelgrid_netcdf')
    await page.getByTestId('ge-tab-overview').click()

    // ---- X/Y/Z 正交剖面控件（坐标标签只来自权威剖面响应）----
    await page.getByTestId('mode-slice').click()
    await expect(page.getByTestId('slice-controls')).toBeVisible()
    await expect(page.getByTestId('slice-coordinate-label')).toContainText('Z = -400')
    await page.getByTestId('axis-x').click()
    await expect(page.getByTestId('slice-coordinate-label')).toContainText('X = -141')
    await page.getByTestId('axis-y').click()
    await expect(page.getByTestId('slice-coordinate-label')).toContainText('Y = 292')
    await page.getByTestId('axis-z').click()
    await expect(page.getByTestId('slice-coordinate-label')).toContainText('Z = -400')

    // ---- 剖面分析入口（统计 + 导出命令）----
    await expect(page.getByTestId('slice-analysis')).toBeVisible()
    await expect(page.getByTestId('slice-statistics')).toContainText('有效 11 / NoData 1')
    await expect(page.getByTestId('export-slice')).toBeEnabled()

    // 成果页全程无 legacy/S3M/DAT 语样
    await expect(page.locator('body')).not.toContainText('S3M')
    await expect(page.locator('body')).not.toContainText('暂缓')
  })

  test('gas 分析中心：gas_content 徽标 / ml/g / 含量分布 / 高低含量区域 / 官方候选直达', async ({
    page,
  }) => {
    await installMockApi(page)
    await installVolumeFrameMock(page)

    // ---- 案例工作台 → 统计与空间分析入口 ----
    await page.goto('/#/cases/gas')
    await expect(page.getByTestId('case-workspace-header')).toContainText('煤层瓦斯')
    await page.getByTestId('stage-nav-results').click()
    await page.getByTestId('analysis-center-entry').click()
    await expect(page).toHaveURL(/#\/datasets\/ds-gas\/analysis/)

    // ---- 徽标与案例身份（gas_content / ml/g）----
    await expect(page.getByTestId('analysis-profile-badge')).toContainText('瓦斯含量')
    await expect(page.getByTestId('analysis-quality-badge')).toContainText('数据全部有效')
    await expect(page.getByTestId('analysis-quality-badge')).toContainText('行')
    await expect(page.getByTestId('analysis-variable')).toContainText('瓦斯含量')
    await expect(page.getByTestId('analysis-variable')).not.toContainText('CH4_content')
    await expect(page.getByTestId('analysis-variable')).toContainText('ml/g')

    // ---- 默认主区 = 高/低含量区域（探索性分位口径），echarts 真实渲染非空图 ----
    const spatial = page.getByTestId('spatial-feature-panel')
    await expect(spatial).toBeVisible()
    await expect(spatial.locator('h3')).toContainText('高/低含量区域')
    const legend = page.getByTestId('spatial-anomaly-legend')
    await expect(legend).toContainText('高含量区域')
    await expect(legend).toContainText('低含量区域')
    await expect(legend).toContainText('阈值来源')
    await expectCanvasRendered(page.getByTestId('spatial-chart'))

    // ---- 模块导航：gas 差异化标签；ok 但暂无面板的专属模块不生成占位入口 ----
    await expect(page.getByTestId('module-nav-item-spatial_anomaly')).toContainText('含量区域')
    await expect(page.getByTestId('module-nav-item-distribution')).toContainText('含量分布')
    await expect(page.getByTestId('module-nav-item-profile_slices')).toBeVisible()
    await expect(page.getByTestId('module-nav-item-gradient')).toHaveCount(0)
    await expect(page.getByTestId('module-nav-item-depth_slices')).toHaveCount(0)

    // ---- 切换分布模块：标题「含量分布」+ ml/g 摘要 + 非空图 ----
    await page.getByTestId('module-nav-item-distribution').click()
    const distribution = page.getByTestId('distribution-panel')
    await expect(distribution).toBeVisible()
    await expect(distribution.locator('h3')).toContainText('含量分布')
    await expect(page.getByTestId('distribution-summary')).toContainText('32 分箱')
    await expect(page.getByTestId('distribution-summary')).toContainText('ml/g')
    await expectCanvasRendered(page.getByTestId('distribution-chart'))

    // ---- 模型证据模块：官方普通克里金候选 ----
    await page.getByTestId('module-nav-item-model_comparison').click()
    const comparison = page.getByTestId('model-comparison-panel')
    await expect(comparison.getByTestId('model-candidate-row')).toHaveCount(1)
    await expect(comparison).toContainText('普通克里金')
    await expect(comparison.getByTestId('badge-materialized')).toBeVisible()
    await expect(comparison.getByTestId('badge-formal')).toBeVisible()

    // ---- 点击模型对比候选行 → 官方成果页 ----
    await page.getByTestId('model-candidate-row').first().click()
    await expect(page).toHaveURL(/#\/results\/cand-gas-official/)
  })

  test('预置卡次命令「查看官方成果」从首页直达官方普通克里金成果页', async ({ page }) => {
    await installMockApi(page)
    await installVolumeFrameMock(page)

    await page.goto('/')
    await page.locator(GAS_CARD).getByTestId('open-official-result').click()
    await expect(page).toHaveURL(/#\/results\/cand-gas-official/)
    await expect(page.getByTestId('v6-result-summary')).toContainText('普通克里金')
    await expect(page.getByTestId('v6-result-summary')).toContainText('151 × 333 × 12')
    await expect(page.getByTestId('native-volume-panel')).toBeVisible()
    // NetCDF 资产懒创建：显式创建入口就绪（与电阻率/微震预置官方成果同一形态）
    await expect(page.getByTestId('create-asset')).toBeVisible()
  })

  test('移动端 390×844：首页/工作台/分析中心无页面级横向溢出', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await installMockApi(page)
    await installVolumeFrameMock(page)

    // 首页：瓦斯卡完整可见且无横向溢出（v0.9.0：手机档案例轨为横向紧凑选择条，
    // 点击 chip 选中，主操作在场景头部）
    await page.goto('/')
    const card = page.locator(GAS_CARD)
    await expect(card).toHaveCount(1)
    await page.locator('[data-test="case-rail-item"][data-case-id="gas"]').click()
    await expect(page.getByTestId('command-center-scene')).toContainText('煤层瓦斯')
    await expect(page.getByTestId('command-center-scene')).toContainText('ml/g')
    const homeScrollWidth = await page.evaluate(() => document.documentElement.scrollWidth)
    expect(homeScrollWidth, '首页 390×844 不得有页面级横向溢出').toBeLessThanOrEqual(390)

    // 工作台：数据摘要与官方成果命令可见
    await page.getByTestId('command-primary-action').click()
    await expect(page.getByTestId('case-workspace-header')).toContainText('煤层瓦斯')
    await expect(page.getByTestId('workspace-data')).toContainText('58')
    await expect(page.getByTestId('open-official-result')).toBeVisible()
    const wsScrollWidth = await page.evaluate(() => document.documentElement.scrollWidth)
    expect(wsScrollWidth, '工作台 390×844 不得有页面级横向溢出').toBeLessThanOrEqual(390)

    // 分析中心：徽标/空间异常图非空且图表宽度不超视口
    await page.getByTestId('stage-nav-results').click()
    await page.getByTestId('analysis-center-entry').click()
    await expect(page).toHaveURL(/#\/datasets\/ds-gas\/analysis/)
    await expect(page.getByTestId('analysis-profile-badge')).toContainText('瓦斯含量')
    const spatialChart = page.getByTestId('spatial-chart')
    await expect(spatialChart).toBeVisible()
    await expectCanvasRendered(spatialChart)
    const chartBox = await spatialChart.boundingBox()
    expect(chartBox).not.toBeNull()
    expect(chartBox!.width).toBeLessThanOrEqual(390)
    const analysisScrollWidth = await page.evaluate(() => document.documentElement.scrollWidth)
    expect(analysisScrollWidth, '分析中心 390×844 不得有页面级横向溢出').toBeLessThanOrEqual(390)

    await page.screenshot({ path: 'test-results/gas-preset-390x844.png', fullPage: true })
  })
})
