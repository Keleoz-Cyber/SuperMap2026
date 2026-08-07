import { expect, test } from '@playwright/test'
import { installMockApi } from '../src/mocks/platformDemo'

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
    // v0.7.0：向导完成 → 统一工作台 → 显式「新建实验」命令
    await page.getByTestId('enter-workspace').click()
    await expect(page).toHaveURL(/#\/cases\/case-e2e$/)
    await expect(page.getByTestId('case-workspace-header')).toContainText('E2E 案例')
    await page.getByTestId('new-experiment').click()
    await expect(page).toHaveURL(/#\/cases\/case-e2e\/experiments\/new\?dataset=ds-e2e/)

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
    await page.getByTestId('crumb-experiment').click()
    await expect(page).toHaveURL(/#\/experiments\/exp-e2e/)
    await page.getByTestId('crumb-home').click()
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
    await page.getByTestId('crumb-home').click()
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
    await page.getByTestId('enter-workspace').click()
    await expect(page).toHaveURL(/#\/cases\/case-e2e$/)
    await page.getByTestId('reanalyze-btn').click()
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
      /#\/cases\/case-e2e\/experiments\/new\?dataset=ds-e2e&professional_confirmation=conf-pro-1/,
    )

    // 专业 Kriging 实验：网格搜索两组邻点数 → 两个成功候选
    await expect(page.getByTestId('professional-confirmation')).toContainText('conf-pro-1')
    await page.getByTestId('mode-grid').check()
    await page.getByTestId('exp-submit').click()
    await expect(page).toHaveURL(/#\/experiments\/exp-pro/)
    await expect(page.getByTestId('run-progress')).toContainText('succeeded', { timeout: 15000 })
    await expect(page.getByTestId('candidate-row')).toHaveCount(2)

    // 成果工作台 → 专业分析台
    await page.getByTestId('open-result').first().click()
    await expect(page).toHaveURL(/#\/results\/cand-pro-1/)
    await page.getByTestId('model-evaluation-entry').click()
    await expect(page).toHaveURL(/#\/results\/cand-pro-1\/evaluation/)
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

// ---------------------------------------------------------------------------
// v0.6.1 体积基准卡直达成果（mock API）：featured_result 主入口与新建实验
// 次操作分离，点击主入口进入真实成果工作台路由。
// ---------------------------------------------------------------------------
test.describe('v0.6.1 体积基准卡直达成果（mock API）', () => {
  test('首页基准卡：查看体渲染成果主入口 + 新建实验次操作', async ({ page }) => {
    await installMockApi(page)

    await page.goto('/')
    // 主入口与次操作同时存在、文案不混淆
    const primary = page.getByTestId('open-featured-result')
    await expect(primary).toBeVisible()
    await expect(primary).toContainText('查看体渲染成果')
    const secondary = page.getByTestId('new-experiment')
    await expect(secondary).toBeVisible()
    await expect(secondary).toContainText('新建实验')

    // 次操作：新建实验 → 实验创建页（与查看已有成果互不混淆）
    await secondary.click()
    await expect(page).toHaveURL(/#\/cases\/case-bench-32\/experiments\/new/)

    // 主入口：查看体渲染成果 → 成果工作台真实加载（复用 cand-1 演示成果夹具）
    await page.goto('/')
    await primary.click()
    await expect(page).toHaveURL(/#\/results\/cand-1/)
    await expect(page.getByTestId('tab-slices')).toBeVisible()
  })
})

// ---------------------------------------------------------------------------
// v0.6.1 实验成果状态区（mock API）：运行 succeeded 只表述为验证完成；
// 物化 / NetCDF 资产 / 浏览器渲染是后续独立阶段，状态区给出分层状态与
// 显式动作入口，主按钮按排行榜首名候选直达成果工作台。
// ---------------------------------------------------------------------------
test.describe('v0.6.1 实验成果状态区（mock API）', () => {
  test('深链实验页 → 运行终态 → 分层状态 → 显式物化/资产 → 查看成果直达成果页', async ({ page }) => {
    await installMockApi(page)

    // 深链进入（等价刷新恢复）：实验页自行轮询到终态
    await page.goto('/#/experiments/exp-e2e')
    await expect(page.getByTestId('run-progress')).toContainText('succeeded', { timeout: 15000 })

    // 成果状态区：四阶段分层，succeeded 不被表述为已渲染
    const panel = page.getByTestId('result-status')
    await expect(panel).toBeVisible()
    await expect(page.getByTestId('stage-validation')).toContainText('验证完成')
    await expect(page.getByTestId('stage-materialize')).toContainText('未物化')
    await expect(page.getByTestId('stage-netcdf')).toContainText('待规则网格物化后进行')
    await expect(page.getByTestId('stage-render')).toContainText('成果工作台')
    await expect(panel).not.toContainText('已渲染')

    // 显式物化：动作入口就位于状态区，成功后进入 NetCDF 阶段
    await page.getByTestId('materialize-result').click()
    await expect(page.getByTestId('stage-materialize')).toContainText('已物化')
    await expect(page.getByTestId('stage-netcdf')).toContainText('未生成')

    // 显式创建 NetCDF 资产：状态机到 ready（仍不等于浏览器渲染）
    await page.getByTestId('create-netcdf-asset').click()
    await expect(page.getByTestId('stage-netcdf')).toContainText('已生成')
    await expect(panel).not.toContainText('已渲染')

    // 主入口：多候选取排行榜首名（cand-1，RMSE 1.2 < 2.4），一键直达成果工作台
    await page.getByTestId('view-result').click()
    await expect(page).toHaveURL(/#\/results\/cand-1/)
    await expect(page.getByTestId('tab-slices')).toBeVisible()
  })
})

// ---------------------------------------------------------------------------
// v0.7.0 batch 3：案例生命周期、数据准备恢复、数据集优先诊断、多候选比较
// （mock API）。每个 test 独立 installMockApi，互不依赖。
// ---------------------------------------------------------------------------
test.describe('v0.7 生命周期与比较流程（mock API）', () => {
  test('恢复数据准备：上传 -> 停在映射 -> 工作台恢复 -> 映射/质量 -> 已验证', async ({ page }) => {
    await installMockApi(page)

    // 创建案例 + 上传 -> 停在映射步骤（不提交映射）
    await page.goto('/')
    await page.getByTestId('create-case-card').click()
    await page.getByTestId('case-name').fill('恢复测试')
    await page.getByTestId('case-file').setInputFiles({
      name: 'platform_demo_3d.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from('x,y,z,rho\n-50,300,-50,67.05\n'),
    })
    await page.getByTestId('case-submit').click()
    await expect(page).toHaveURL(/#\/cases\/case-e2e\/datasets\/ds-e2e\/prepare/)

    // 未映射时返回工作台 -> data_preparation 面板显示"继续"
    await page.goto('/#/cases/case-e2e')
    await expect(page.getByTestId('case-workspace-header')).toBeVisible()
    await expect(page.getByTestId('data-preparation-panel')).toBeVisible()
    await expect(page.getByTestId('prep-action-continue')).toBeVisible()

    // 点击"继续" -> 回到数据准备页 -> 映射 + 质量 -> 已验证
    await page.getByTestId('prep-action-continue').click()
    await expect(page).toHaveURL(/#\/cases\/case-e2e\/datasets\/ds-e2e\/prepare/)
    await page.getByTestId('mapping-value-name').fill('电阻率')
    await page.getByTestId('mapping-submit').click()
    await expect(page.getByTestId('quality-banner')).toContainText('质量校验通过')
    await page.getByTestId('enter-workspace').click()
    await expect(page).toHaveURL(/#\/cases\/case-e2e$/)
    // 验证后工作台显示"新建实验"恢复按钮
    await expect(page.getByTestId('new-experiment')).toBeVisible()
  })

  test('回收与恢复：删除案例 -> 首页消失 -> 回收站可见 -> 恢复 -> 工作台可用', async ({ page }) => {
    await installMockApi(page)

    // 创建案例
    await page.goto('/')
    await page.getByTestId('create-case-card').click()
    await page.getByTestId('case-name').fill('回收测试')
    await page.getByTestId('case-file').setInputFiles({
      name: 'platform_demo_3d.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from('x,y,z,rho\n-50,300,-50,67.05\n'),
    })
    await page.getByTestId('case-submit').click()
    await expect(page).toHaveURL(/#\/cases\/case-e2e\/datasets\/ds-e2e\/prepare/)

    // 首页 -> 移入回收站
    await page.goto('/')
    const caseCard = page.locator('.case-card', { hasText: '回收测试' })
    await caseCard.getByTestId('trash-case-btn').click()
    await page.locator('.el-dropdown-menu__item:visible', { hasText: '移入回收站' }).click()

    // 案例从首页消失
    await expect(page.locator('.case-card', { hasText: '回收测试' })).toHaveCount(0)

    // 回收站 -> 案例可见 -> 恢复
    await page.goto('/#/trash')
    await expect(page.getByTestId('trash-list')).toBeVisible()
    await expect(page.getByText('回收测试')).toBeVisible()
    await page.getByTestId('restore-case').click()
    await expect(page.getByText('回收测试')).toHaveCount(0)

    // 恢复后工作台可用
    await page.goto('/#/cases/case-e2e')
    await expect(page.getByTestId('case-workspace-header')).toContainText('回收测试')
  })

  test('永久删除：回收 -> 输入精确名称 -> 删除 -> 深链返回未找到', async ({ page }) => {
    await installMockApi(page)

    // 创建案例
    await page.goto('/')
    await page.getByTestId('create-case-card').click()
    await page.getByTestId('case-name').fill('永久删除测试')
    await page.getByTestId('case-file').setInputFiles({
      name: 'platform_demo_3d.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from('x,y,z,rho\n-50,300,-50,67.05\n'),
    })
    await page.getByTestId('case-submit').click()

    // 首页 -> 移入回收站
    await page.goto('/')
    const caseCard = page.locator('.case-card', { hasText: '永久删除测试' })
    await caseCard.getByTestId('trash-case-btn').click()
    await page.locator('.el-dropdown-menu__item:visible', { hasText: '移入回收站' }).click()

    // 回收站 -> 永久删除
    await page.goto('/#/trash')
    await expect(page.getByText('永久删除测试')).toBeVisible()
    await page.getByTestId('purge-case-open').click()
    await expect(page.getByTestId('purge-dialog')).toBeVisible()
    await page.getByTestId('purge-name-input').fill('永久删除测试')
    await page.getByTestId('purge-confirm-btn').click()

    // 案例从回收站消失
    await expect(page.getByText('永久删除测试')).toHaveCount(0)

    // 深链工作台 -> 未找到
    await page.goto('/#/cases/case-e2e')
    await expect(page.getByTestId('workspace-load-error')).toBeVisible()
  })

  test('数据集优先诊断：验证 -> 诊断 -> 确认 -> 应用到 Kriging 实验', async ({ page }) => {
    await installMockApi(page)

    // 创建案例 + 上传 + 映射 + 质量 -> 已验证
    await page.goto('/')
    await page.getByTestId('create-case-card').click()
    await page.getByTestId('case-name').fill('诊断优先测试')
    await page.getByTestId('case-file').setInputFiles({
      name: 'platform_demo_3d.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from('x,y,z,rho\n-50,300,-50,67.05\n'),
    })
    await page.getByTestId('case-submit').click()
    await page.getByTestId('mapping-value-name').fill('电阻率')
    await page.getByTestId('mapping-submit').click()
    await expect(page.getByTestId('quality-banner')).toContainText('质量校验通过')
    await page.getByTestId('enter-workspace').click()
    await expect(page).toHaveURL(/#\/cases\/case-e2e$/)

    // 工作台 -> 已验证数据集区 -> 专业诊断入口
    await expect(page.getByTestId('validated-datasets')).toBeVisible()
    await page.getByTestId('diagnosis-detail-btn').click()
    await expect(page).toHaveURL(/#\/datasets\/ds-e2e\/professional-diagnosis/)

    // 诊断已成功：变异函数证据 + 已有确认快照
    await expect(page.getByTestId('variogram-panel')).toBeVisible({ timeout: 15000 })
    await expect(page.getByTestId('confirmation-snapshot')).toBeVisible()

    // 应用到 Kriging 实验
    await page.getByTestId('apply-confirmation').click()
    await expect(page).toHaveURL(/professional_confirmation=conf-pro-1/)
    await expect(page.getByTestId('professional-confirmation')).toContainText('conf-pro-1')
    await page.getByTestId('exp-submit').click()
    await expect(page).toHaveURL(/#\/experiments\/exp-pro/)
  })

  test('候选比较：跨实验选择 -> 排名；然后不兼容字段', async ({ page }) => {
    await installMockApi(page)

    await page.goto('/#/datasets/ds-e2e/candidate-comparison')
    await expect(page.getByTestId('candidate-comparison-view')).toBeVisible()
    await expect(page.getByTestId('candidate-table')).toBeVisible()

    // 从两个实验各选一个候选
    const checkboxes = page.getByTestId('candidate-checkbox')
    await checkboxes.nth(0).click()
    await checkboxes.nth(2).click()
    await expect(page.getByTestId('selection-info')).toContainText('已选 2')

    // 比较 -> 可排名
    await page.getByTestId('compare-btn').click()
    await expect(page.getByTestId('ranking-result')).toBeVisible()
    await expect(page.getByTestId('ranking-row-0')).toBeVisible()

    // 更换选择 -> 再比较 -> 不兼容字段
    await checkboxes.nth(0).click()
    await expect(page.getByTestId('ranking-result')).toHaveCount(0)
    await checkboxes.nth(1).click()
    await page.getByTestId('compare-btn').click()
    await expect(page.getByTestId('mismatch-list')).toBeVisible()
  })

  test('移动端 390x844：VariogramPanel 无横向溢出', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await installMockApi(page)

    // Navigate through mapping flow to get validated dataset
    await page.goto('/#/cases/case-e2e/datasets/ds-e2e/prepare')
    await page.getByTestId('mapping-value-name').fill('电阻率')
    await page.getByTestId('mapping-submit').click()
    await expect(page.getByTestId('quality-banner')).toContainText('质量校验通过', { timeout: 5000 })
    await page.getByTestId('enter-workspace').click()
    await expect(page).toHaveURL(/#\/cases\/case-e2e$/)

    // Enter professional diagnosis from workspace
    await page.getByTestId('reanalyze-btn').click()
    await expect(page.getByTestId('diagnosis-config')).toBeVisible()
    await page.getByTestId('start-diagnosis').click()
    await expect(page.getByTestId('variogram-panel')).toBeVisible({ timeout: 15000 })

    // Wait for chart to render
    await page.waitForTimeout(500)

    // Assert no horizontal overflow at 390px viewport
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth)
    expect(scrollWidth).toBeLessThanOrEqual(390)

    // Assert panel fits within viewport
    const panelBox = await page.getByTestId('variogram-panel').boundingBox()
    expect(panelBox).not.toBeNull()
    expect(panelBox!.width).toBeLessThanOrEqual(390)

    // Check sampling info is visible (not clipped)
    await expect(page.getByTestId('sampling-mode')).toBeVisible()
    await expect(page.getByTestId('sampling-pairs')).toBeVisible()

    // Check bins table container doesn't overflow page
    const tableWrap = page.locator('.bins-table-wrap')
    if (await tableWrap.isVisible()) {
      const wrapBox = await tableWrap.boundingBox()
      expect(wrapBox!.width).toBeLessThanOrEqual(390)
    }

    // Screenshot for visual verification
    await page.screenshot({
      path: 'test-results/variogram-mobile-390x844.png',
      fullPage: true,
    })
  })
})
