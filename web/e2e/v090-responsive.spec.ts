import { expect, test, type Page } from '@playwright/test'
import { installMockApi } from '../src/mocks/platformDemo'
import { MOCK_VOLUME_FRAME_HTML } from './mockVolumeFrame'

// v0.9.0 Task 14：响应式与零横向溢出像素级门（mock API + 协议 mock 子帧）。
// 覆盖桌面大屏/普通笔记本/平板/手机四档视口；任何档位出现横向溢出、
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

test('手机视口：摘要优先顺序 + 全屏三维入口有效', async ({ page }) => {
  test.setTimeout(90_000)
  await installMockApi(page)
  await installFrameMock(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')

  // 首屏顺序：案例选择（紧凑轨）→ 案例摘要（场景头部，含唯一主动作）→
  // 关键发现 → 证据带 → 全屏三维入口；内嵌三维画面不得先于发现出现
  await expect(page.getByTestId('case-rail')).toBeVisible()
  await expect(page.getByTestId('command-center-scene')).toBeVisible()
  await expect(page.getByTestId('home-findings')).toBeVisible()
  await expect(page.getByTestId('home-evidence-dock')).toBeVisible()
  const order = await page.evaluate(() => {
    const top = (testId: string) =>
      document.querySelector(`[data-test="${testId}"]`)?.getBoundingClientRect().top ?? -1
    return {
      rail: top('case-rail'),
      summary: top('command-center-scene'),
      findings: top('home-findings'),
      evidence: top('home-evidence-dock'),
      entry: top('phone-scene-entry'),
    }
  })
  expect(order.rail).toBeGreaterThanOrEqual(0)
  expect(order.rail).toBeLessThan(order.summary)
  expect(order.summary).toBeLessThan(order.findings)
  expect(order.findings).toBeLessThan(order.evidence)
  expect(order.evidence).toBeLessThan(order.entry)

  // 内嵌三维画布在手机档默认不渲染（不占首屏）
  const frameCount = await page.getByTestId('volume-frame').count()
  let frameHidden = true
  if (frameCount > 0) {
    const box = await page.getByTestId('volume-frame').boundingBox()
    frameHidden = !box || box.height === 0
  }
  expect(frameHidden).toBe(true)

  // 全屏三维入口：打开 → 场景全屏覆盖 → 关闭恢复
  const openBtn = page.getByTestId('phone-open-scene')
  await openBtn.scrollIntoViewIfNeeded()
  await openBtn.click()
  const openBox = await page.getByTestId('command-center-scene').boundingBox()
  expect(openBox).not.toBeNull()
  expect(openBox!.height).toBeGreaterThanOrEqual(844 * 0.9)
  await expect(page.getByTestId('phone-close-scene')).toBeVisible()
  await page.getByTestId('phone-close-scene').click()
  const closedBox = await page.getByTestId('command-center-scene').boundingBox()
  expect(closedBox!.height).toBeLessThan(844 * 0.9)

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
})
