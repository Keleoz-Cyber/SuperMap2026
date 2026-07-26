import { expect, test } from '@playwright/test'
import { installMockApi } from '../src/mocks/platformDemo'
import { microseismicUploadPayloads } from '../e2e-live/fixtures/microseismicBundle'

// 浏览器冒烟：完整 v0.4 流程，全程 mock API，不需要 iServer。

test.describe('v0.4 通用建模流程（mock API）', () => {
  test('案例创建 → 向导 → 实验 → 排行榜 → 成果切片 → 选择 → 导出', async ({ page }) => {
    await installMockApi(page)

    // 首页 → 新建案例
    await page.goto('/')
    await expect(page.getByText(/v\d+\.\d+\.\d+ 建模平台/)).toBeVisible()
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

    // 导航回归：成果 → 实验 → 首页，无死路
    await page.getByTestId('nav-experiment').click()
    await expect(page).toHaveURL(/#\/experiments\/exp-e2e/)
    await expect(page.getByTestId('nav-new-experiment')).toBeVisible()
    await page.getByTestId('nav-home').click()
    await expect(page).toHaveURL(/#\/$/)
    await expect(page.getByTestId('create-case-card')).toBeVisible()
  })

  test('深链加载失败时仍可从错误页返回首页', async ({ page }) => {
    await installMockApi(page)
    // 最后注册的路由优先生效：让实验详情接口 404
    await page.route('**/api/experiments/exp-missing', (route) =>
      route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({
          error: { code: 'EXPERIMENT_NOT_FOUND', message: '实验不存在', details: {} },
        }),
      }),
    )
    await page.route('**/api/experiments/exp-missing/candidates', (route) =>
      route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({
          error: { code: 'EXPERIMENT_NOT_FOUND', message: '实验不存在', details: {} },
        }),
      }),
    )

    await page.goto('/#/experiments/exp-missing')
    await expect(page.getByText('加载失败')).toBeVisible()
    await page.getByTestId('nav-home').click()
    await expect(page).toHaveURL(/#\/$/)
    await expect(page.getByTestId('create-case-card')).toBeVisible()
  })
})

test.describe('v0.5 微震第二案例（mock API）', () => {
  // 计数全部来自便携夹具口径（45/44/1/0/44/44），绝不在 UI 上冒充私有 2,006/1,925 证据。
  test('首页 → 微震案例创建 → 22 DAT 选择 → 派生摘要 → 质量 → 实验页 → 首页', async ({
    page,
  }) => {
    await installMockApi(page)

    // 首页微震卡 → 预设创建页（只要名称）
    await page.goto('/')
    await expect(page.getByText(/v\d+\.\d+\.\d+ 建模平台/)).toBeVisible()
    await page.getByTestId('enter-microseismic').click()
    await expect(page).toHaveURL(/#\/cases\/new\?preset=microseismic/)
    await page.getByTestId('case-name').fill('微震 E2E 案例')
    await page.getByTestId('case-submit').click()
    await expect(page).toHaveURL(/#\/cases\/case-micro\/microseismic\/import/)

    // 22 DAT 选择：字节由便携夹具生成器在测试时现造
    await page.getByTestId('micro-dat-files').setInputFiles(microseismicUploadPayloads())
    await expect(page.getByTestId('micro-file-count')).toContainText('已选择 22 个 DAT')
    await page.getByTestId('micro-import-submit').click()

    // 原始数据核验：22 文件清单 + 夹具计数
    await expect(page.getByTestId('source-manifest')).toContainText('W1.dat')
    await expect(page.getByTestId('source-manifest')).toContainText('W8.dat')
    await expect(page.getByTestId('source-manifest')).toContainText('WD27-Vx.dat')
    await expect(page.getByTestId('step-verify')).toContainText(
      '共 22 个文件 · 源记录 45 · 有限记录 44',
    )
    await page.getByTestId('micro-continue-derivation').click()

    // 派生摘要：夹具计数（显式排除私有口径）、黄金比对通过、工件逻辑名
    const layerCounts = page.getByTestId('layer-counts')
    await expect(layerCounts).toContainText('源记录')
    await expect(layerCounts).toContainText('45')
    await expect(layerCounts).toContainText('有限记录')
    await expect(layerCounts).toContainText('44')
    const lineCounts = page.getByTestId('line-counts')
    await expect(lineCounts).toContainText('L1')
    await expect(lineCounts).toContainText('19')
    await expect(lineCounts).toContainText('L3')
    await expect(lineCounts).toContainText('8')
    await expect(page.getByTestId('golden-status')).toContainText('黄金比对通过')
    await expect(page.getByTestId('artifact-list')).toContainText('accepted_modeling_44.csv')
    await expect(page.getByTestId('artifact-list')).toContainText('aggregated_nodes_44.csv')
    await expect(page.getByTestId('step-derivation')).not.toContainText('2006')
    await expect(page.getByTestId('step-derivation')).not.toContainText('1925')
    await page.getByTestId('micro-continue-modeling').click()

    // 质量校验 → 建模入口
    await expect(page.getByTestId('quality-banner')).toContainText('质量校验通过')
    await expect(page.getByTestId('step-modeling')).toContainText('总行 44')
    await expect(page.getByTestId('step-modeling')).toContainText('有效 44')
    await page.getByTestId('enter-modeling').click()

    // 实验页：微震预设出现 z_scale 控件（默认 1），随后返回首页
    await expect(page).toHaveURL(/#\/cases\/case-micro\/experiments\/new\?dataset=ds-micro/)
    await expect(page.getByTestId('param-editor')).toBeVisible()
    await expect(page.getByTestId('z-scale-manual')).toHaveValue('1')
    await page.getByTestId('nav-home').click()
    await expect(page).toHaveURL(/#\/$/)
    await expect(page.getByTestId('create-case-card')).toBeVisible()
  })
})
