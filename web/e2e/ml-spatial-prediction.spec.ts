import { expect, test, type Page } from '@playwright/test'
import { installMockApi } from '../src/mocks/platformDemo'
import { MOCK_VOLUME_FRAME_HTML } from './mockVolumeFrame'

async function installMLDemo(page: Page) {
  await installMockApi(page)
  await page.route(
    (url) => url.pathname === '/supermap-volume-frame/index.html',
    (route) => route.fulfill({ status: 200, contentType: 'text/html', body: MOCK_VOLUME_FRAME_HTML }),
  )
}

async function openRandomForestResult(page: Page) {
  await page.goto('/#/cases/resistivity/experiments/new?dataset=ds-rho')
  await expect(page.getByTestId('ml-capability-notice')).toContainText('适用')
  await page.getByTestId('algo-random-forest').check()
  await expect(page.getByTestId('param-editor')).toContainText('模型离散度')
  await page.getByTestId('exp-submit').click()
  await expect(page).toHaveURL(/#\/experiments\/exp-ml-rf/)
  await expect(page.getByTestId('leaderboard')).toContainText('随机森林空间预测', { timeout: 15_000 })
  await page.getByTestId('open-result').click()
  await expect(page).toHaveURL(/#\/results\/cand-ml-rf/)
}

test('随机森林完整链：创建、空间验证、成果证据与多字段渲染', async ({ page }) => {
  await installMLDemo(page)
  await openRandomForestResult(page)

  await page.getByTestId('ge-tab-model').click()
  await expect(page.getByTestId('ml-model-evidence')).toContainText('未优于普通克里金')
  await expect(page.getByTestId('ml-model-evidence')).toContainText('公共有效')
  await expect(page.getByTestId('ml-field-selector')).toBeVisible()

  await page.getByTestId('create-asset').click()
  await expect(page.getByTestId('volume-phase')).toContainText('已渲染')
  await page.getByTestId('ml-field-model_dispersion').click()
  await expect(page.getByTestId('active-ml-field-note')).toContainText('模型离散度')
  await page.getByTestId('create-asset').click()
  await expect(page.getByTestId('volume-phase')).toContainText('已渲染')

  const requests = await page.evaluate(() => performance.getEntriesByType('resource').map((row) => row.name))
  expect(requests.some((url) => url.includes('field=model_dispersion'))).toBe(true)
})

test('数据适用性差异：微震支持机器学习，58 点瓦斯明确不建议', async ({ page }) => {
  await installMLDemo(page)

  await page.goto('/#/cases/builtin-microseismic-vx-1911/experiments/new?dataset=ds-preset')
  await expect(page.getByTestId('ml-capability-notice')).toContainText('1911')
  await expect(page.getByTestId('algo-random-forest')).toBeEnabled()

  await page.goto('/#/cases/gas/experiments/new?dataset=ds-gas')
  await expect(page.getByTestId('ml-capability-notice')).toContainText('58')
  await expect(page.getByTestId('ml-capability-notice')).toContainText('不建议')
  await expect(page.getByTestId('algo-random-forest')).toBeDisabled()
  await expect(page.getByTestId('algo-kriging-rf-residual')).toBeDisabled()
})

test('机器学习与普通克里金使用同一口径比较，较差时不会被推荐', async ({ page }) => {
  await installMLDemo(page)
  await page.goto('/#/datasets/ds-rho/candidate-comparison?case=resistivity')

  await expect(page.getByTestId('candidate-table')).toContainText('普通克里金')
  await expect(page.getByTestId('candidate-table')).toContainText('随机森林空间预测')
  await expect(page.getByTestId('selection-info')).toContainText('已选 2')
  await page.getByTestId('compare-btn').click()
  await expect(page.getByTestId('ranking-result')).toBeVisible()
  await expect(page.getByTestId('ranking-row-0')).toContainText('普通克里金')
  await expect(page.getByTestId('ranking-row-1')).toContainText('随机森林空间预测')
})

for (const viewport of [
  { name: 'large', width: 1920, height: 1080 },
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'phone', width: 390, height: 844 },
] as const) {
  test(`ML 成果工作台 ${viewport.name}：无页面溢出、主场景与字段动作可用`, async ({ page }) => {
    await installMLDemo(page)
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    await page.goto('/#/results/cand-ml-rf')

    await expect(page.getByTestId('result-analysis-workbench')).toBeVisible()
    await expect(page.getByTestId('ml-field-selector')).toBeVisible()
    await expect(page.getByTestId('native-volume-panel')).toBeVisible()
    await expect(page.getByTestId('ml-field-model_dispersion')).toBeVisible()

    const layout = await page.evaluate(() => {
      const selector = document.querySelector('[data-test="ml-field-selector"]')?.getBoundingClientRect()
      const scene = document.querySelector('[data-test="native-volume-panel"]')?.getBoundingClientRect()
      return {
        overflow: document.documentElement.scrollWidth - window.innerWidth,
        selectorBottom: selector?.bottom ?? 0,
        sceneTop: scene?.top ?? 0,
        sceneWidth: scene?.width ?? 0,
      }
    })
    expect(layout.overflow).toBeLessThanOrEqual(1)
    expect(layout.sceneTop).toBeGreaterThanOrEqual(layout.selectorBottom)
    expect(layout.sceneWidth).toBeGreaterThan(viewport.width === 390 ? 330 : 500)
  })
}
