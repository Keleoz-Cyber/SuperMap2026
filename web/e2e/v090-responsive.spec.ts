import { expect, test, type Page } from '@playwright/test'
import { installMockApi } from '../src/mocks/platformDemo'
import { MOCK_VOLUME_FRAME_HTML } from './mockVolumeFrame'

// v0.9.0 Task 14：响应式与零横向溢出像素级门（mock API + 协议 mock 子帧）。
// 覆盖桌面大屏、主流笔记本、平板与手机；短屏业务深页还验证自然滚动
// 和底部功能可达。任何档位出现横向溢出、主动作缺失或页面错误即失败。

const VIEWPORTS = [
  { name: 'desktop-1920', width: 1920, height: 1080 },
  { name: 'laptop-1536', width: 1536, height: 864 },
  { name: 'desktop-1440', width: 1440, height: 900 },
  { name: 'laptop-1366', width: 1366, height: 768 },
  { name: 'laptop-1280', width: 1280, height: 720 },
  { name: 'tablet-834', width: 834, height: 1112 },
  { name: 'phone-390', width: 390, height: 844 },
] as const

async function installFrameMock(page: Page) {
  await page.route(
    (url) => url.pathname === '/supermap-volume-frame/index.html',
    (route) => route.fulfill({ status: 200, contentType: 'text/html', body: MOCK_VOLUME_FRAME_HTML }),
  )
}

for (const viewport of [
  { name: 'laptop-1366', width: 1366, height: 768 },
  { name: 'laptop-1280', width: 1280, height: 720 },
] as const) {
  test(`成果工作台短屏 ${viewport.name}：退出沉浸锁定并可滚动到全部功能`, async ({ page }) => {
    await installMockApi(page)
    await installFrameMock(page)
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    await page.goto('/#/results/cand-1')

    await expect(page.getByTestId('native-volume-panel')).toBeVisible()
    await expect(page.getByTestId('ge-tab-provenance')).toBeAttached()

    await page.getByTestId('workbench-focus-judgement').click()
    await expect(page.getByTestId('result-analysis-workbench')).toHaveClass(/focus-judgement/)
    await expect(page.getByTestId('result-analysis-side')).toBeVisible()
    await expect(page.getByTestId('domain-overview')).toBeVisible()

    const layout = await page.evaluate(() => {
      const shell = document.querySelector<HTMLElement>('.app-shell')
      return {
        shellOverflowY: shell ? getComputedStyle(shell).overflowY : 'missing',
        scrollHeight: document.documentElement.scrollHeight,
        viewportHeight: window.innerHeight,
        horizontalOverflow: document.documentElement.scrollWidth - window.innerWidth,
      }
    })
    expect(layout.shellOverflowY).not.toBe('hidden')
    expect(layout.scrollHeight).toBeGreaterThan(layout.viewportHeight)
    expect(layout.horizontalOverflow).toBeLessThanOrEqual(0)

    await page.getByTestId('workbench-focus-analysis').click()
    await page.getByTestId('ge-tab-provenance').scrollIntoViewIfNeeded()
    await expect(page.getByTestId('ge-tab-provenance')).toBeVisible()
    if (viewport.name === 'laptop-1280') {
      await page.screenshot({ path: 'test-results/responsive-result-1280x720.png', fullPage: true })
    }
  })
}

const SHORT_SCREEN_ROUTES = [
  {
    name: '数据准备',
    url: '/#/cases/case-e2e/datasets/ds-e2e/prepare',
    root: 'data-intake-workbench',
    action: 'abandon-preparation-btn',
  },
  {
    name: '调参实验室',
    url: '/#/cases/resistivity/experiments/new?dataset=ds-rho',
    root: 'param-editor',
    action: 'exp-submit',
  },
  {
    name: '候选比较',
    url: '/#/datasets/ds-rho/candidate-comparison?case=resistivity',
    root: 'candidate-comparison-view',
    action: 'compare-btn',
  },
  {
    name: '分析中心',
    url: '/#/datasets/ds-rho/analysis?case=resistivity',
    root: 'analysis-center-view',
    action: 'lower-area',
  },
] as const

for (const route of SHORT_SCREEN_ROUTES) {
  test(`${route.name} 1280×720：100% 缩放下无横向溢出且底部功能可达`, async ({ page }) => {
    await installMockApi(page)
    await installFrameMock(page)
    await page.setViewportSize({ width: 1280, height: 720 })
    await page.goto(route.url)

    await expect(page.getByTestId(route.root)).toBeVisible()
    const action = page.getByTestId(route.action)
    await expect(action).toBeAttached()
    await action.scrollIntoViewIfNeeded()
    await expect(action).toBeVisible()

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    )
    expect(overflow).toBeLessThanOrEqual(0)
  })
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

    // 桌面/笔记本 100% 浏览器缩放必须直接看到完整指挥舱与底部证据坞，
    // 不允许再依赖用户手工缩放到 75%。平板/手机仍采用自然文档流。
    if (viewport.width > 960) {
      const firstScreen = await page.evaluate(() => {
        const dock = document.querySelector<HTMLElement>('[data-test="home-evidence-dock"]')
        return {
          dockBottom: dock?.getBoundingClientRect().bottom ?? Number.POSITIVE_INFINITY,
          viewportHeight: window.innerHeight,
          documentScrollHeight: document.documentElement.scrollHeight,
        }
      })
      expect(firstScreen.dockBottom).toBeLessThanOrEqual(firstScreen.viewportHeight)
      expect(firstScreen.documentScrollHeight).toBeLessThanOrEqual(firstScreen.viewportHeight + 1)
    }
    if (viewport.width >= 1600 && viewport.height >= 900) {
      const innerPanels = await page.evaluate(() => {
        const measure = (selector: string) => {
          const element = document.querySelector<HTMLElement>(selector)
          return element ? element.scrollHeight - element.clientHeight : Number.POSITIVE_INFINITY
        }
        return {
          caseRailOverflow: measure('[data-test="case-rail"]'),
          findingsOverflow: measure('[data-test="home-findings"]'),
          toolsOverflow: measure('.native-volume-panel.presentation .tools-rail'),
        }
      })
      // Chromium 在固定轨道上可能因子像素/边框舍入报告 2–3px 的伪溢出；
      // 4px 内不产生可操作滚动，也不会隐藏任何正文。
      expect(innerPanels.caseRailOverflow).toBeLessThanOrEqual(4)
      expect(innerPanels.findingsOverflow).toBeLessThanOrEqual(1)
      expect(innerPanels.toolsOverflow).toBeLessThanOrEqual(1)
    }

    // 零横向溢出
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    )
    expect(overflow).toBeLessThanOrEqual(0)

    if (viewport.name === 'laptop-1280') {
      await page.screenshot({ path: 'test-results/responsive-home-1280x720.png', fullPage: true })
    }

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
