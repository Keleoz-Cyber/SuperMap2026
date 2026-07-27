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

// ---------------------------------------------------------------------------
// v0.6 专业建模流程（mock API）：质量通过的数据集 → 诊断 → 不可变确认 →
// 专业 Kriging 实验 → 折分检查 → 不确定性图层 → 已保存异常 → 兼容比较。
// 所有计数/身份均来自 platformDemo.ts 的夹具值，不冒充真实计算结果。
// ---------------------------------------------------------------------------
test.describe('v0.6 专业建模流程（mock API）', () => {
  test('质量门禁 → 诊断 → 确认 → 专业实验 → 折分/不确定性/异常/比较', async ({ page }) => {
    await installMockApi(page)

    // 案例 + 上传 → 映射 → 质量门禁通过（数据集进入 validated）
    await page.goto('/')
    await page.getByTestId('create-case-card').click()
    await page.getByTestId('case-name').fill('专业 E2E 案例')
    await page.getByTestId('case-file').setInputFiles({
      name: 'platform_demo_3d.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from('x,y,z,rho\n-50,300,-50,67.05\n'),
    })
    await page.getByTestId('case-submit').click()
    await expect(page).toHaveURL(/#\/cases\/case-e2e\/datasets\/ds-e2e\/prepare/)
    await page.getByTestId('mapping-value-name').fill('电阻率')
    await page.getByTestId('mapping-submit').click()
    await expect(page.getByTestId('quality-banner')).toContainText('质量校验通过')

    // 诊断入口：实验创建页的专业入口（质量门禁通过后才可用）
    await page.getByTestId('start-experiment').click()
    await expect(page).toHaveURL(/#\/cases\/case-e2e\/experiments\/new\?dataset=ds-e2e/)
    await page.getByTestId('professional-entry').click()
    await expect(page).toHaveURL(/#\/datasets\/ds-e2e\/professional-diagnosis\?case=case-e2e/)

    // 诊断：提交 → 任务轮询 → 证据（点对模式/候选建议）
    await expect(page.getByTestId('diagnosis-config')).toBeVisible()
    await page.getByTestId('start-diagnosis').click()
    await expect(page.getByTestId('job-status')).toBeVisible()
    await expect(page.getByTestId('variogram-panel')).toBeVisible({ timeout: 15000 })
    await expect(page.getByTestId('sampling-mode')).toContainText('全量')
    await expect(page.getByTestId('suggestion-label')).toContainText('诊断建议，需人工确认')
    await expect(page.getByTestId('candidate-evidence').first()).toContainText('主方位角 90')

    // 不可变确认：模型必须显式选择，note 必填，快照只创建不修改
    await page.getByTestId('confirm-model').selectOption('spherical')
    await page.getByTestId('confirm-note').fill('采纳诊断候选主方向（mock 夹具）')
    await page.getByTestId('confirm-submit').click()
    await expect(page.getByTestId('confirmation-snapshot')).toBeVisible()
    await expect(page.getByTestId('confirmation-id')).toContainText('conf-pro-1')
    await page.getByTestId('goto-experiment').click()
    await expect(page).toHaveURL(
      /#\/cases\/case-e2e\/experiments\/new\?dataset=ds-e2e&confirmation=conf-pro-1/,
    )

    // 专业 Kriging 实验：网格搜索两组邻点数 → 两个成功候选
    await page.getByTestId('professional-toggle').check()
    await page.getByTestId('algo-kriging').check()
    await expect(page.getByTestId('professional-confirmation')).toContainText('conf-pro-1')
    await page.getByTestId('mode-grid').check()
    await page.getByTestId('exp-submit').click()
    await expect(page).toHaveURL(/#\/experiments\/exp-pro/)
    await expect(page.getByTestId('run-progress')).toContainText('succeeded', { timeout: 15000 })
    await expect(page.getByTestId('candidate-row')).toHaveCount(2)

    // 成果工作台 → 专业分析台
    await page.getByTestId('open-result').first().click()
    await expect(page).toHaveURL(/#\/results\/cand-pro-1/)
    await page.getByTestId('professional-entry').click()
    await expect(page).toHaveURL(/#\/results\/cand-pro-1\/professional/)
    await expect(page.getByTestId('summary-algorithm')).toContainText('ordinary_kriging')
    await expect(page.getByTestId('summary-confirmation')).toContainText('conf-pro-1')
    await expect(page.getByTestId('capability-native-kriging-std')).toContainText('supported')

    // 折分检查：泄漏徽章 + 折切换改变训练/验证计数
    await expect(page.getByTestId('fold-inspector')).toBeVisible()
    await expect(page.getByTestId('leakage-badge')).toContainText('未检测到泄漏')
    await expect(page.getByTestId('fold-training-count')).toContainText('96')
    await page.getByTestId('fold-tab-1').click()
    await expect(page.getByTestId('fold-validation-count')).toContainText('24')

    // 不确定性图层：预测值 / 经验误差尺度 / Kriging 标准差各自标题与值域
    await expect(page.getByTestId('layer-title')).toContainText('预测值')
    await page.getByTestId('layer-tab-empirical').click()
    await expect(page.getByTestId('layer-title')).toContainText('经验误差尺度')
    await expect(page.getByTestId('layer-value-range')).toContainText('0.5')
    await page.getByTestId('layer-tab-kriging-std').click()
    await expect(page.getByTestId('layer-title')).toContainText('Kriging 标准差')
    await expect(page.getByTestId('layer-value-range')).toContainText('0.3')

    // 异常：阈值预览 → 保存 → 任务轮询 → 连通区表与网格高亮
    await page.getByTestId('anomaly-threshold').fill('100')
    await expect(page.getByTestId('anomaly-preview-count')).toContainText('预计合格节点')
    await page.getByTestId('anomaly-save').click()
    await expect(page.getByTestId('extraction-identity')).toContainText('ext-pro-1', {
      timeout: 15000,
    })
    await expect(page.getByTestId('component-count')).toContainText('连通区 2 / 2 个')
    await expect(page.getByTestId('component-row')).toHaveCount(2)
    await expect(page.getByTestId('highlight-count')).toContainText('网格高亮节点')

    // 兼容比较：同实验第二候选 → 成对公共指标差 + 场差摘要
    await page.getByTestId('comparison-second-cand-pro-2').click()
    await page.getByTestId('comparison-run').click()
    await expect(page.getByTestId('comparison-compatible')).toBeVisible()
    await expect(page.getByTestId('common-valid-count')).toContainText('128')
    await expect(page.getByTestId('metric-delta-row').first()).toBeVisible()
    await expect(page.getByTestId('grid-difference')).toContainText('121')
  })
})
