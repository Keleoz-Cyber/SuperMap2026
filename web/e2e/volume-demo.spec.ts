import { expect, test } from '@playwright/test'
import { installMockApi } from '../src/mocks/platformDemo'

// 真实 Chromium WebGL2 渲染证明：SwiftShader 软渲染参数保证无 GPU 环境也走同一路径。
// 若 Chromium 无法创建 WebGL2，页面会显示明确错误且本测试必须失败——不 skip、不换 mock 渲染器。
test.use({ launchOptions: { args: ['--use-angle=swiftshader'] } })

test('renders a continuous volume and reacts to transfer controls', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text())
  })
  const misses: string[] = []
  page.on('response', (response) => {
    if (response.status() >= 400) misses.push(`${response.status()} ${response.url()}`)
  })
  await installMockApi(page)
  await page.goto('/#/volume-demo')

  await expect(page.getByTestId('source-shape')).toContainText('7 × 21 × 48')
  await expect(page.getByTestId('target-shape')).toContainText('7 × 23 × 42')
  const canvas = page.locator('canvas[data-test="volume-canvas"]')
  await expect(canvas).toBeVisible()

  const before = await canvas.screenshot()
  await page.getByTestId('volume-threshold').evaluate((node) => {
    const input = node as HTMLInputElement
    input.value = '0.62'
    input.dispatchEvent(new Event('input', { bubbles: true }))
    input.dispatchEvent(new Event('change', { bubbles: true }))
  })
  await page.getByTestId('volume-opacity').evaluate((node) => {
    const input = node as HTMLInputElement
    input.value = '0.90'
    input.dispatchEvent(new Event('input', { bubbles: true }))
    input.dispatchEvent(new Event('change', { bubbles: true }))
  })
  await page.waitForTimeout(250)
  const after = await canvas.screenshot()

  expect(before.length).toBeGreaterThan(1000)
  expect(after.length).toBeGreaterThan(1000)
  expect(Buffer.compare(before, after)).not.toBe(0)
  console.log(`pixel evidence: before=${before.length}B after=${after.length}B differ=${Buffer.compare(before, after) !== 0}`)
  console.log(`http>=400: ${JSON.stringify(misses)}`)
  expect(errors).toEqual([])
})
