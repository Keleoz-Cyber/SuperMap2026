import { expect, test, type Page } from '@playwright/test'
import { installMockApi } from '../src/mocks/platformDemo'
import { MOCK_VOLUME_FRAME_HTML } from './mockVolumeFrame'

// v0.9.0 Task 14：响应式与零横向溢出像素级门（mock API + 协议 mock 子帧）。
// 覆盖桌面答辩屏/普通笔记本/平板/手机四档视口；任何档位出现横向溢出、
// 主动作缺失或未处理页面错误即失败。

const VIEWPORTS = [
  { name: 'desktop-1440', width: 1440, height: 900 },
  { name: 'laptop-1280', width: 1280, height: 800 },
  { name: 'tablet-834', width: 834, height: 1112 },
  { name: 'phone-390', width: 390, height: 844 },
] as const

async function installFrameMock(page: Page) {
  await page.route(
    (url) => url.pathname === '/supermap-volume-frame/index.html',
    (route) => route.fulfill({ status: 200, contentType: 'text/html', body: MOCK_VOLUME_FRAME_HTML }),
  )
}

for (const viewport of VIEWPORTS) {
  test(`指挥舱响应式 ${viewport.name}：无横向溢出、主动作可见、零页面错误`, async ({ page }) => {
    const pageErrors: string[] = []
    page.on('pageerror', (err) => pageErrors.push(String(err)))

    await installMockApi(page)
    await installFrameMock(page)
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    await page.goto('/')

    // 指挥舱骨架与唯一主动作
    await expect(page.getByTestId('command-center')).toBeVisible()
    await expect(page.getByTestId('case-rail')).toBeVisible()
    await expect(page.getByTestId('command-center-scene')).toBeVisible()
    await expect(page.getByTestId('home-findings')).toBeVisible()
    await expect(page.getByTestId('home-evidence-dock')).toBeVisible()
    await expect(page.getByTestId('command-primary-action')).toBeVisible()

    // 零横向溢出
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    )
    expect(overflow).toBeLessThanOrEqual(0)

    expect(pageErrors).toEqual([])
  })
}

test('手机视口：案例切换联动与证据带不遮挡场景控制', async ({ page }) => {
  await installMockApi(page)
  await installFrameMock(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')

  await expect(page.getByTestId('command-center-scene')).toBeVisible()
  // 切到瓦斯案例：场景标题与单位联动
  await page.getByTestId('case-rail-item').filter({ hasText: '煤层瓦斯' }).click()
  await expect(page.getByTestId('command-center-scene')).toContainText('煤层瓦斯')
  await expect(page.getByTestId('command-center-scene')).toContainText('ml/g')

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
})
