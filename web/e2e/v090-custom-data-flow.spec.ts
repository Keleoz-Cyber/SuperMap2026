import { expect, test } from '@playwright/test'
import { installMockApi } from '../src/mocks/platformDemo'

// v0.9.0 Task 15：自定义数据全链 mock 门。
// 全局入口 → 新建案例 → 数据接入与准备（四阶段同屏）→ 质量通过 →
// 统一工作台（四阶段导航）→ 实验 → 成果与分析融合工作台。

test('自定义数据完整链：上传 → 映射 → 质量 → 实验 → 成果工作台', async ({ page }) => {
  await installMockApi(page)
  await page.goto('/')

  // 全局固定入口与项目列表入口同时存在
  await expect(page.getByTestId('global-create-case')).toBeVisible()
  await page.getByTestId('create-case-card').click()
  await expect(page).toHaveURL(/#\/cases\/new/)

  // 创建案例 + 上传（统一数据接入工作台）
  await expect(page.locator('body')).toContainText('创建案例并接入数据')
  await page.getByTestId('case-name').fill('v0.9 演示项目')
  await page.getByTestId('case-file').setInputFiles({
    name: 'platform_demo_3d.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('x,y,z,rho\n-50,300,-50,67.05\n'),
  })
  await page.getByTestId('case-submit').click()
  await expect(page).toHaveURL(/#\/cases\/case-e2e\/datasets\/ds-e2e\/prepare/)

  // 数据接入与准备同屏工作台：四阶段 + 文件预览 + 空间预览 + 映射诊断 + 质量摘要
  await expect(page.getByTestId('data-intake-workbench')).toBeVisible()
  await expect(page.getByTestId('intake-stage-file')).toContainText('文件接入')
  await expect(page.getByTestId('intake-stage-mapping')).toContainText('字段映射')
  await expect(page.getByTestId('intake-stage-quality')).toContainText('质量检查')
  await expect(page.getByTestId('intake-stage-confirm')).toContainText('建模确认')
  await expect(page.getByTestId('step-file')).toContainText('platform_demo_3d.csv')
  await expect(page.getByTestId('spatial-preview-panel')).toBeVisible()

  // 映射 → 自动校验
  await page.getByTestId('mapping-value-name').fill('电阻率')
  await page.getByTestId('mapping-submit').click()
  await expect(page.getByTestId('quality-banner')).toContainText('质量校验通过')
  await expect(page.getByTestId('quality-composition')).toBeVisible()

  // 完成 → 统一工作台（四阶段导航 + 唯一主动作）
  await page.getByTestId('enter-workspace').click()
  await expect(page).toHaveURL(/#\/cases\/case-e2e$/)
  await expect(page.getByTestId('case-workspace-header')).toContainText('v0.9 演示项目')
  await expect(page.getByTestId('stage-nav-data')).toContainText('数据概览')
  await expect(page.getByTestId('stage-nav-experiments')).toContainText('建模实验')
  await expect(page.getByTestId('stage-nav-results')).toContainText('成果分析')
  await expect(page.getByTestId('stage-nav-evidence')).toContainText('证据与报告')

  // 新建实验 → 提交 → 运行流水线
  await page.getByTestId('stage-nav-experiments').click()
  await page.getByTestId('new-experiment').click()
  await expect(page).toHaveURL(/#\/cases\/case-e2e\/experiments\/new\?dataset=ds-e2e/)
  await expect(page.getByTestId('lab-layout')).toBeVisible()
  await expect(page.getByTestId('lab-params')).toBeVisible()
  await expect(page.getByTestId('lab-canvas')).toBeVisible()
  await expect(page.getByTestId('lab-summary')).toBeVisible()
  await page.getByTestId('exp-submit').click()
  await expect(page).toHaveURL(/#\/experiments\/exp-e2e/)
  await expect(page.getByTestId('run-pipeline')).toBeVisible()
  await expect(page.getByTestId('leaderboard')).toContainText('1.200', { timeout: 15000 })

  // 成果：融合工作台（场景 + 发现 + 证据带 + 溯源抽屉）
  await page.getByTestId('open-result').first().click()
  await expect(page).toHaveURL(/#\/results\/cand-1/)
  await expect(page.getByTestId('result-analysis-workbench')).toBeVisible()
  await expect(page.getByTestId('result-scene')).toBeVisible()
  await page.getByTestId('workbench-focus-analysis').click()
  await expect(page.getByTestId('result-evidence-dock')).toBeVisible()
  await expect(page.getByTestId('ge-tab-provenance')).toBeVisible()
  await page.getByTestId('ge-tab-provenance').click()
  await expect(page.getByTestId('export-button')).toBeVisible()
})
