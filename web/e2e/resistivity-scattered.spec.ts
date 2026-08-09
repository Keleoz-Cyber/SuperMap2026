import { expect, test, type Page } from '@playwright/test'
import { installMockApi } from '../src/mocks/platformDemo'
import { MOCK_VOLUME_FRAME_HTML, MOCK_VOLUME_FRAME_PATH } from './mockVolumeFrame'

// v0.8.0 Task 9：电阻率标准化散点预置 + DSI-like 的统一产品流程（mock API）。
// 首页预置卡（标准化散点 · 17,549 个节点，无 legacy/S3M/DAT 语样）→ 统一
// 案例工作台（builtin_preset：数据摘要/官方成果/新建实验）→ 新建 DSI-like
// 实验（参数编辑器含免责声明「不等同于 GOCAD DSI」）→ 成功候选 → 成果页
// （算法身份、渲染状态、X/Y/Z 控件、剖面分析入口）。
// iframe 由 mockVolumeFrame.ts 的协议 mock 子帧扮演（无 SuperMap3D SDK）：
// 本规格只证明产品接线与协议正确，真实像素验收在
// e2e-live/resistivity-scattered-live.spec.ts。
// 成果页头部按既有合同展示原始算法标识（dsi_like）；中文算法标签
// 「DSI-like 离散平滑插值」由参数编辑器与工作台算法列承载。

const RHO_CARD = '.case-card:has-text("地下电阻率")'

async function installVolumeFrameMock(page: Page): Promise<void> {
  await page.route(
    (url) => url.pathname === MOCK_VOLUME_FRAME_PATH,
    (route) =>
      route.fulfill({ status: 200, contentType: 'text/html', body: MOCK_VOLUME_FRAME_HTML }),
  )
}

test.describe('v0.8.0 电阻率散点预置与 DSI-like（mock API）', () => {
  test('首页预置卡 → 统一工作台 → DSI-like 实验 → 成功候选 → 成果页渲染链', async ({ page }) => {
    await installMockApi(page)
    await installVolumeFrameMock(page)

    // ---- 首页：电阻率以 builtin_preset 预置卡唯一承载，无旧语样 ----
    await page.goto('/')
    const card = page.locator(RHO_CARD)
    await expect(card).toHaveCount(1)
    await expect(card).toContainText('标准化散点 · 17,549 个节点')
    await expect(card).toContainText('散点预置 · 官方普通克里金成果')
    await expect(card).toContainText('X/Y/Z/RHO')
    await expect(card).toContainText('Ω·m')
    await expect(card).not.toContainText('S3M')
    await expect(card).not.toContainText('DAT')
    await expect(card).not.toContainText('legacy')

    // ---- 统一案例工作台（builtin_preset 四区同构）----
    await card.getByTestId('enter-case-workspace').click()
    await expect(page).toHaveURL(/#\/cases\/resistivity$/)
    await expect(page.getByTestId('case-workspace-header')).toContainText('地下电阻率')
    await expect(page.getByTestId('case-workspace-header')).toContainText('CSV 预置')
    await expect(page.getByTestId('workspace-overview')).toBeVisible()
    // 数据摘要：只读预置数据版本（17,549 行 X/Y/Z -> RHO）
    await expect(page.getByTestId('workspace-data')).toContainText('行数 17549')
    await expect(page.getByTestId('workspace-data')).toContainText('X/Y/Z -> RHO')
    await expect(page.getByTestId('workspace-data')).toContainText('validated')
    // 官方成果与新建实验两条命令并存
    await expect(page.getByTestId('open-official-result')).toContainText('查看官方成果')
    await expect(page.getByTestId('workspace-experiments')).toBeVisible()
    await expect(page.getByTestId('new-experiment')).toBeVisible()
    await expect(page.getByTestId('workspace-results')).toContainText('官方成果')
    await expect(page.getByTestId('workspace-results')).toContainText('已物化')
    // 旧 legacy 页面嵌入块与导入入口不存在
    await expect(page.getByTestId('workspace-rho-block')).toHaveCount(0)
    await expect(page.getByTestId('legacy-import')).toHaveCount(0)

    // ---- 新建 DSI-like 实验：算法标签、免责声明与固定合同 ----
    await page.getByTestId('new-experiment').click()
    await expect(page).toHaveURL(/#\/cases\/resistivity\/experiments\/new\?dataset=ds-rho/)
    await expect(page.getByTestId('param-editor')).toBeVisible()
    await page.getByTestId('algo-dsi-like').check()
    await expect(page.getByTestId('param-editor')).toContainText('DSI-like 离散平滑插值')
    await expect(page.getByTestId('dsi-like-note')).toContainText('不等同于 GOCAD DSI')
    // 硬约束恒开、收敛容差固定（只读展示，不可关闭/编辑）
    await expect(page.getByTestId('dsi-hard-constraints')).toBeVisible()
    await expect(page.getByTestId('dsi-convergence-tolerance')).toBeVisible()
    await page.getByTestId('exp-submit').click()

    // ---- 运行到终态：恰好一个成功候选 ----
    await expect(page).toHaveURL(/#\/experiments\/exp-rho-dsi/)
    await expect(page.getByTestId('run-progress')).toContainText('succeeded', { timeout: 15000 })
    await expect(page.getByTestId('candidate-row')).toHaveCount(1)
    await expect(page.getByTestId('candidate-row')).toContainText('成功')
    await expect(page.getByTestId('candidate-row')).toContainText('neighbor_connectivity')

    // ---- 成果页：算法身份 + 显式资产 → 渲染状态 ----
    await page.getByTestId('open-result').click()
    await expect(page).toHaveURL(/#\/results\/cand-rho-dsi-1/)
    await expect(page.locator('.page-sub')).toContainText('dsi_like')
    await expect(page.locator('.page-sub')).toContainText('7×23×42')
    await expect(page.getByTestId('native-volume-panel')).toBeVisible()
    await page.getByTestId('create-asset').click()
    await expect(page.getByTestId('volume-phase')).toContainText('已渲染')
    await expect(page.getByTestId('asset-identity')).toContainText('supermap_voxelgrid_netcdf')

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
  })

  test('首页预置卡次命令「查看官方成果」直达官方普通克里金成果页', async ({ page }) => {
    await installMockApi(page)
    await installVolumeFrameMock(page)

    await page.goto('/')
    await page.locator(RHO_CARD).getByTestId('open-official-result').click()
    await expect(page).toHaveURL(/#\/results\/cand-rho-official/)
    await expect(page.locator('.page-sub')).toContainText('ordinary_kriging')
    await expect(page.locator('.page-sub')).toContainText('7×23×42')
    await expect(page.getByTestId('native-volume-panel')).toBeVisible()
    // NetCDF 资产懒创建：显式创建入口就绪（与微震预置官方成果同一形态）
    await expect(page.getByTestId('create-asset')).toBeVisible()
  })
})
