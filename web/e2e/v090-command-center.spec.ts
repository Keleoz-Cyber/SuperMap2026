import { expect, test, type Page } from '@playwright/test'
import { installMockApi } from '../src/mocks/platformDemo'
import { MOCK_VOLUME_FRAME_HTML } from './mockVolumeFrame'

// v0.9.0 Task 15：指挥舱 mock 门。三官方案例切换必须整体联动
// （变量/单位/辅助色/结论/成果身份），零未处理控制台错误。

async function boot(page: Page) {
  const consoleErrors: string[] = []
  page.on('console', (msg) => {
    if (msg.type() !== 'error') return
    // 资源级 404（如尚未创建的渲染资产 GET）是类型化流程的一部分，
    // 前端已显式处理；这里的零错误门只统计 JS 级未处理错误
    if (msg.text().includes('Failed to load resource')) return
    consoleErrors.push(msg.text())
  })
  await installMockApi(page)
  await page.route(
    (url) => url.pathname === '/supermap-volume-frame/index.html',
    (route) => route.fulfill({ status: 200, contentType: 'text/html', body: MOCK_VOLUME_FRAME_HTML }),
  )
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/')
  await expect(page.getByTestId('command-center')).toBeVisible()
  return consoleErrors
}

test.describe('v0.9.0 指挥舱（mock API）', () => {
  test('三官方案例切换：变量、单位、辅助色与成果身份整体联动', async ({ page }) => {
    const consoleErrors = await boot(page)

    // 默认电阻率（mock 案例列表首项）
    const scene = page.getByTestId('command-center-scene')
    await expect(scene).toContainText('地下电阻率')
    await expect(scene).toContainText('Ω·m')
    await expect(page.getByTestId('command-center')).toHaveAttribute('data-case-accent', 'gold')

    // 微震：冰紫辅助色 + km/s
    await page.getByTestId('case-rail-item').filter({ hasText: '微震速度' }).click()
    await expect(scene).toContainText('微震速度')
    await expect(scene).toContainText('km/s')
    await expect(scene).not.toContainText('Ω·m')
    await expect(page.getByTestId('command-center')).toHaveAttribute('data-case-accent', 'violet')

    // 瓦斯：翡翠绿 + ml/g + 含量叙事
    await page.getByTestId('case-rail-item').filter({ hasText: '煤层瓦斯' }).click()
    await expect(scene).toContainText('煤层瓦斯')
    await expect(scene).toContainText('ml/g')
    await expect(page.getByTestId('command-center')).toHaveAttribute('data-case-accent', 'jade')

    // 关键发现与证据带真实更新（质量结论来自分析摘要 DTO）
    await expect(page.getByTestId('home-findings')).toContainText('有效数据')
    await expect(page.getByTestId('home-evidence-dock')).toContainText('溯源')

    expect(consoleErrors).toEqual([])
  })

  test('官方案例无上传控件；自定义数据入口持续可见', async ({ page }) => {
    await boot(page)
    const scene = page.getByTestId('command-center-scene')
    await expect(scene).not.toContainText('上传')
    await expect(page.getByTestId('global-create-case')).toBeVisible()
    await expect(page.getByTestId('create-case-card')).toBeVisible()
    await expect(page.getByTestId('download-demo-data')).toBeVisible()
  })

  test('官方卡主命令进入案例分析；官方成果直达成果页', async ({ page }) => {
    await boot(page)
    await page.getByTestId('case-rail-item').filter({ hasText: '煤层瓦斯' }).click()
    await page.getByTestId('command-primary-action').click()
    await expect(page).toHaveURL(/#\/cases\/gas/)

    await page.goto('/')
    const gasCard = page.getByTestId('case-rail-item').filter({ hasText: '煤层瓦斯' }).locator('..')
    await gasCard.getByTestId('open-official-result').click()
    await expect(page).toHaveURL(/#\/results\/cand-gas-official/)
  })
})
