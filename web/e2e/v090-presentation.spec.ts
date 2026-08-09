import { expect, test, type Page } from '@playwright/test'
import { installMockApi } from '../src/mocks/platformDemo'
import { MOCK_VOLUME_FRAME_HTML } from './mockVolumeFrame'

// v0.9.0 Task 15：答辩模式 mock 门。六章节可导航、键盘可用、
// 降级章节显式表达、退出回到指挥舱；零未处理 JS 错误。

async function boot(page: Page) {
  const consoleErrors: string[] = []
  page.on('console', (msg) => {
    if (msg.type() !== 'error') return
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

test('答辩模式：六章节完整巡航与退出', async ({ page }) => {
  const consoleErrors = await boot(page)

  // 从全局头进入答辩模式
  await page.getByTestId('presentation-mode-entry').click()
  await expect(page).toHaveURL(/#\/presentation/)
  await expect(page.getByTestId('presentation-overlay')).toBeVisible()
  await expect(page.getByTestId('presentation-title')).toContainText('平台能力总览')
  await expect(page.getByTestId('chapter-overview')).toContainText('数据接入')

  // 键盘右移逐章推进
  await page.keyboard.press('ArrowRight')
  await expect(page.getByTestId('presentation-title')).toContainText('地下电阻率')
  // 电阻率章节：mock 已 seed，场景与发现真实加载
  await expect(page.getByTestId('chapter-resistivity')).toBeVisible()

  await page.keyboard.press('ArrowRight')
  await expect(page.getByTestId('presentation-title')).toContainText('微震速度')
  await page.keyboard.press('ArrowRight')
  await expect(page.getByTestId('presentation-title')).toContainText('煤层瓦斯含量')
  await page.keyboard.press('ArrowRight')
  await expect(page.getByTestId('presentation-title')).toContainText('自定义数据')
  await expect(page.getByTestId('presentation-demo-download')).toBeVisible()
  await page.keyboard.press('ArrowRight')
  await expect(page.getByTestId('presentation-title')).toContainText('创新点与已知边界')
  await expect(page.getByTestId('chapter-boundaries')).toContainText('局部坐标')

  // 末章再右移不越界
  await page.keyboard.press('ArrowRight')
  await expect(page.getByTestId('presentation-title')).toContainText('创新点与已知边界')

  // 章节目录直达 + Escape 退出回首页
  await page.getByTestId('presentation-chapter-overview').click()
  await expect(page.getByTestId('presentation-title')).toContainText('平台能力总览')
  await page.keyboard.press('Escape')
  await expect(page).toHaveURL(/#\/$/)
  await expect(page.getByTestId('command-center')).toBeVisible()

  expect(consoleErrors).toEqual([])
})

test('答辩模式：编辑与危险操作不出现在章节中', async ({ page }) => {
  await boot(page)
  await page.getByTestId('presentation-mode-entry').click()
  await page.getByTestId('presentation-chapter-resistivity').click()
  await expect(page.getByTestId('chapter-resistivity')).toBeVisible()
  // 只读形态：无新建实验/回收站/上传等写操作
  await expect(page.getByTestId('chapter-resistivity')).not.toContainText('新建实验')
  await expect(page.getByTestId('chapter-resistivity')).not.toContainText('上传')
  await expect(page.locator('[data-test="trash-case-btn"]')).toHaveCount(0)
})
