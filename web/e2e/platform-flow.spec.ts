import { expect, test } from '@playwright/test'
import { installMockApi } from '../src/mocks/platformDemo'

// 浏览器冒烟：完整 v0.4 流程，全程 mock API，不需要 iServer。

test.describe('v0.4 通用建模流程（mock API）', () => {
  test('案例创建 → 向导 → 实验 → 排行榜 → 成果切片 → 选择 → 导出', async ({ page }) => {
    await installMockApi(page)

    // 首页 → 新建案例
    await page.goto('/')
    await expect(page.getByText('v0.4 建模平台')).toBeVisible()
    await page.getByTestId('create-case-card').click()

    // 创建案例 + 上传
    await page.getByTestId('case-name').fill('E2E 案例')
    await page.getByTestId('case-file').setInputFiles({
      name: 'platform_demo_3d.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from('x,y,z,rho\n-50,300,-50,67.05\n'),
    })
    await page.getByTestId('case-submit').click()
    await expect(page).toHaveURL(/#\/cases\/case-e2e\/datasets\/ds-e2e\/prepare/)

    // 向导：文件信息 → 映射 → 质量 → 开始实验
    await expect(page.getByTestId('step-file')).toContainText('platform_demo_3d.csv')
    await page.getByTestId('mapping-value-name').fill('电阻率')
    await page.getByTestId('mapping-submit').click()
    await expect(page.getByTestId('quality-banner')).toContainText('质量校验通过')
    await page.getByTestId('start-experiment').click()
    await expect(page).toHaveURL(/#\/cases\/case-e2e\/experiments\/new/)

    // 实验：默认 IDW 手动 → 提交 → 自动跳详情并轮询到终态
    await expect(page.getByTestId('param-editor')).toBeVisible()
    await page.getByTestId('exp-submit').click()
    await expect(page).toHaveURL(/#\/experiments\/exp-e2e/)
    await expect(page.getByTestId('run-progress')).toBeVisible()
    await expect(page.getByTestId('leaderboard')).toContainText('1.200', { timeout: 15000 })

    // 成果工作台：切片三方向 + 坐标标签
    await page.getByTestId('open-result').first().click()
    await expect(page).toHaveURL(/#\/results\/cand-1/)
    await page.getByTestId('tab-slices').click()
    await expect(page.getByTestId('slice-label')).toContainText('Z = -800 m')
    await page.getByTestId('axis-x').click()
    await expect(page.getByTestId('slice-label')).toContainText('X = -150 m')
    await page.getByTestId('axis-y').click()
    await expect(page.getByTestId('slice-label')).toContainText('Y = 260 m')

    // 正式选择（理由必填）与导出/发布状态分离
    await page.getByTestId('selection-submit').click()
    await expect(page.getByTestId('selection-error')).toBeVisible()
    await page.getByTestId('selection-note').fill('公共验证 RMSE 最低')
    await page.getByTestId('selection-submit').click()
    await expect(page.getByTestId('formal-selection-panel')).toContainText('公共验证 RMSE 最低')

    await expect(page.getByTestId('publication-status')).toContainText('未请求')
    await page.getByTestId('export-button').click()
    await expect(page.getByTestId('export-file').first()).toContainText('manifest.json')
    await expect(page.getByTestId('publication-status')).toContainText('未请求')
    await page.getByTestId('publish-button').click()
    await expect(page.getByTestId('publication-status')).toContainText('manual_required')
  })
})
