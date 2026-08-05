import { expect, test } from '@playwright/test'
import { installMockApi } from '../src/mocks/platformDemo'

// v0.7.0 Task 9：微震 CSV 预置案例的统一工作台流程（mock API）。
// 预置卡 → 工作台 → 官方成果直达成果页（NetCDF 原生体渲染面板）；
// 用户新建实验是独立次要入口，与官方成果链互不干扰。

const PRESET_CARD = '.case-card:has-text("微震速度")'

test.describe('v0.7.0 微震预置案例（mock API）', () => {
  test('首页预置卡 → 工作台 → 官方成果 → 原生体渲染面板', async ({ page }) => {
    await installMockApi(page)

    // 首页：预置徽标取代 DAT 文案；全页无 DAT 导入入口
    await page.goto('/')
    await expect(page.locator(PRESET_CARD)).toContainText('CSV 预置 · 官方普通克里金成果')
    await expect(page.getByText('导入微震 DAT')).toHaveCount(0)

    // 预置卡主命令：进入统一工作台
    await page.locator(PRESET_CARD).getByTestId('enter-case-workspace').click()
    await expect(page).toHaveURL(/#\/cases\/builtin-microseismic-vx-1911/)

    // 工作台四区同构 + 官方/用户两条命令
    await expect(page.getByTestId('case-workspace-header')).toContainText('微震速度')
    await expect(page.getByTestId('workspace-overview')).toBeVisible()
    await expect(page.getByTestId('workspace-data')).toBeVisible()
    await expect(page.getByTestId('workspace-experiments')).toBeVisible()
    await expect(page.getByTestId('workspace-results')).toBeVisible()
    await expect(page.getByTestId('workspace-data')).toContainText('Vx')

    // 官方成果直达 → 成果页 NetCDF 原生体渲染面板
    await page.getByTestId('open-official-result').click()
    await expect(page).toHaveURL(/#\/results\/cand-1/)
    await expect(page.getByTestId('native-volume-panel')).toBeVisible()
  })

  test('工作台「新建实验」是独立入口：进入通用实验创建页（不影响官方成果）', async ({ page }) => {
    await installMockApi(page)
    await page.goto('/#/cases/builtin-microseismic-vx-1911')

    await expect(page.getByTestId('case-workspace-header')).toContainText('微震速度')
    await page.getByTestId('new-experiment').click()
    await expect(page).toHaveURL(
      /#\/cases\/builtin-microseismic-vx-1911\/experiments\/new/,
    )
    await expect(page.getByTestId('param-editor')).toBeVisible()
  })

  test('预置卡次命令「查看官方成果」从首页直达成果页', async ({ page }) => {
    await installMockApi(page)
    await page.goto('/')
    await page.locator(PRESET_CARD).getByTestId('open-official-result').click()
    await expect(page).toHaveURL(/#\/results\/cand-1/)
    await expect(page.getByTestId('native-volume-panel')).toBeVisible()
  })
})
