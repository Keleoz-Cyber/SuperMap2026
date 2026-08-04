import { expect, test } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  FIXTURE_COUNTS,
  microseismicUploadPayloads,
  prepareMicroseismicLiveFixture,
} from './fixtures/microseismicBundle'

// Live E2E：真实 FastAPI + 独立临时 SQLite + 真实建模 Worker。
// 不使用 Mock API、iServer、私有资料或本机绝对路径。

const HERE = path.dirname(fileURLToPath(import.meta.url))
const DEMO_CSV = path.resolve(HERE, '../../demo/platform_demo_3d.csv')

function assertIsolatedDataDir() {
  const dir = process.env.GEOMODELING_DATA_DIR
  if (!dir) {
    throw new Error('Live E2E 要求调用环境提供唯一的 GEOMODELING_DATA_DIR')
  }
  const normalized = dir.replace(/\\/g, '/')
  if (normalized.endsWith('var/geomodeling') || normalized.endsWith('var/demo_v041')) {
    throw new Error(`Live E2E 不得使用默认/演示数据目录：${dir}`)
  }
}

// 最小 ZIP 中央目录解析（Python zipfile 产物）：只取条目名，核对导出包内容身份。
function listZipEntryNames(buf: Buffer): string[] {
  const EOCD_SIG = 0x06054b50
  const CD_SIG = 0x02014b50
  let eocd = -1
  for (let i = buf.length - 22; i >= Math.max(0, buf.length - 22 - 0xffff); i--) {
    if (buf.readUInt32LE(i) === EOCD_SIG) {
      eocd = i
      break
    }
  }
  if (eocd < 0) throw new Error('ZIP 结束记录（EOCD）未找到')
  const count = buf.readUInt16LE(eocd + 10)
  let offset = buf.readUInt32LE(eocd + 16)
  const names: string[] = []
  for (let n = 0; n < count; n++) {
    if (buf.readUInt32LE(offset) !== CD_SIG) throw new Error('ZIP 中央目录损坏')
    const nameLen = buf.readUInt16LE(offset + 28)
    const extraLen = buf.readUInt16LE(offset + 30)
    const commentLen = buf.readUInt16LE(offset + 32)
    names.push(buf.subarray(offset + 46, offset + 46 + nameLen).toString('utf8'))
    offset += 46 + nameLen + extraLen + commentLen
  }
  return names
}

test.beforeAll(() => {
  assertIsolatedDataDir()
})

test('真实链路：上传 → 映射 → 质量 → IDW → 排行榜 → 成果切片 → 选择 → 导出 → 首页', async ({
  page,
  request,
}) => {
  // 1. 真实健康检查（非 Mock）
  const health = await request.get('/api/health')
  expect(health.ok()).toBe(true)
  const healthBody = await health.json()
  expect(healthBody.status).toBe('ok')
  expect(healthBody.version).toMatch(/^\d+\.\d+\.\d+/)

  const caseName = `Live 演示 ${Date.now()}`

  // 2. 首页创建案例
  await page.goto('/')
  await page.getByTestId('create-case-card').click()
  await page.getByTestId('case-name').fill(caseName)
  await page.getByTestId('case-file').setInputFiles(DEMO_CSV)
  await page.getByTestId('case-submit').click()
  await expect(page).toHaveURL(/#\/cases\/[0-9a-f-]+\/datasets\/[0-9a-f-]+\/prepare/)

  // 3. 映射 + 质量门禁
  await expect(page.getByTestId('step-file')).toContainText('platform_demo_3d.csv')
  await page.getByTestId('mapping-value-name').fill('电阻率（演示）')
  await page.getByTestId('mapping-submit').click()
  await expect(page.getByTestId('quality-banner')).toContainText('质量校验通过', {
    timeout: 30_000,
  })
  await page.getByTestId('start-experiment').click()
  await expect(page).toHaveURL(/#\/cases\/[0-9a-f-]+\/experiments\/new/)

  // 4. 手动 IDW 单组（power=2, neighbor_count=16 默认）
  await page.getByTestId('exp-name').fill('Live IDW')
  await page.getByTestId('exp-submit').click()
  await expect(page).toHaveURL(/#\/experiments\/[0-9a-f-]+/)

  // 5. 有界轮询至成功；排行榜出现公共有效数与有限 RMSE
  await expect(page.getByTestId('run-progress')).toContainText('succeeded', { timeout: 60_000 })
  const board = page.getByTestId('leaderboard')
  await expect(board).toContainText('公共有效点 144', { timeout: 30_000 })
  const firstRow = page.getByTestId('candidate-row').first()
  await expect(firstRow).toContainText(/\d+\.\d{3}/)

  // 6. 打开成果：完整场（NetCDF 原生体渲染面板）+ X/Y/Z 切片（真实坐标标签为数值）
  await page.getByTestId('open-result').first().click()
  await expect(page).toHaveURL(/#\/results\/[0-9a-f-]+/)
  await expect(page.getByTestId('native-volume-panel')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTestId('create-asset')).toBeVisible({ timeout: 30_000 })
  await page.getByTestId('tab-slices').click()
  await expect(page.getByTestId('slice-label')).toContainText(/Z = -?\d+(\.\d+)? m/)
  await page.getByTestId('axis-x').click()
  await expect(page.getByTestId('slice-label')).toContainText(/X = -?\d+(\.\d+)? m/)
  await page.getByTestId('axis-y').click()
  await expect(page.getByTestId('slice-label')).toContainText(/Y = -?\d+(\.\d+)? m/)

  // 7. 正式选择（理由必填）并持久化
  const reason = `Live 选择 ${Date.now()}`
  await page.getByTestId('selection-note').fill(reason)
  await page.getByTestId('selection-submit').click()
  await expect(page.getByTestId('formal-selection-panel')).toContainText(reason)
  await page.reload()
  await expect(page.getByTestId('formal-selection-panel')).toContainText(reason, {
    timeout: 30_000,
  })

  // 8. 导出证据 ZIP（下载事件验证真实 ZIP 字节）
  await page.getByTestId('export-button').click()
  const downloadPromise = page.waitForEvent('download', { timeout: 60_000 })
  await page.getByTestId('export-download').click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toMatch(/\.zip$/)
  const zipPath = await download.path()
  const zipBytes = await readFile(zipPath)
  expect(zipBytes.length).toBeGreaterThan(100)
  expect(zipBytes.subarray(0, 2).toString()).toBe('PK')

  // 9. 返回实验 → 返回首页；案例卡持久化可见
  await page.getByTestId('nav-experiment').click()
  await expect(page).toHaveURL(/#\/experiments\/[0-9a-f-]+/)
  await page.getByTestId('nav-home').click()
  await expect(page).toHaveURL(/#\/$/)
  await expect(page.getByText(caseName)).toBeVisible()
})


// ---------------------------------------------------------------------------
// v0.5 微震第二案例：真实 FastAPI + 隔离 SQLite + 运行时生成的合成 22-DAT 包。
// 微震合同配置由 GEOMODELING_MICROSEISMIC_CONFIG 指向隔离目录内的夹具配置；
// 服务器按请求读取配置，beforeAll 在首个导入请求前完成两遍标定即可。
// ---------------------------------------------------------------------------
test.describe('v0.5 微震第二案例（真实链路）', () => {
  test.beforeAll(() => {
    prepareMicroseismicLiveFixture()
  })

  test('创建 → 22 DAT 导入 → 派生核验 → 质量 → IDW(z_scale=1) → 全场/切片 → 选择 → 领域证据 ZIP → 首页', async ({
    page,
    request,
  }) => {
    // 1. 真实健康检查（非 Mock）
    const health = await request.get('/api/health')
    expect(health.ok()).toBe(true)

    const caseName = `Live 微震 ${Date.now()}`

    // 2. 首页微震卡 → 预设创建（只要名称）
    await page.goto('/')
    await page.getByTestId('enter-microseismic').click()
    await expect(page).toHaveURL(/#\/cases\/new\?preset=microseismic/)
    await page.getByTestId('case-name').fill(caseName)
    await page.getByTestId('case-submit').click()
    await expect(page).toHaveURL(/#\/cases\/[0-9a-f-]+\/microseismic\/import/)

    // 3. 22 DAT 选择并上传：字节由便携夹具生成器现造
    await page.getByTestId('micro-dat-files').setInputFiles(microseismicUploadPayloads())
    await expect(page.getByTestId('micro-file-count')).toContainText('已选择 22 个 DAT')
    await page.getByTestId('micro-import-submit').click()

    // 4. 原始数据核验：22 文件清单 + 夹具计数（非私有 2,006/1,925）
    await expect(page.getByTestId('source-manifest')).toContainText('W1.dat', { timeout: 30_000 })
    await expect(page.getByTestId('source-manifest')).toContainText('WD27-Vx.dat')
    await expect(page.getByTestId('step-verify')).toContainText(
      `共 ${FIXTURE_COUNTS.datFiles} 个文件 · 源记录 ${FIXTURE_COUNTS.sourceRecords} · 有限记录 ${FIXTURE_COUNTS.finiteRecords}`,
    )
    await page.getByTestId('micro-continue-derivation').click()

    // 5. 派生摘要：黄金比对通过 + 计数内嵌的工件逻辑名
    await expect(page.getByTestId('golden-status')).toContainText('黄金比对通过')
    await expect(page.getByTestId('layer-counts')).toContainText(`${FIXTURE_COUNTS.sourceRecords}`)
    await expect(page.getByTestId('artifact-list')).toContainText(
      `accepted_modeling_${FIXTURE_COUNTS.acceptedModeling}.csv`,
    )
    await expect(page.getByTestId('step-derivation')).not.toContainText('2006')
    await expect(page.getByTestId('step-derivation')).not.toContainText('1925')
    await page.getByTestId('micro-continue-modeling').click()

    // 6. 质量门禁 → 建模入口
    await expect(page.getByTestId('quality-banner')).toContainText('质量校验通过', {
      timeout: 30_000,
    })
    await expect(page.getByTestId('step-modeling')).toContainText(
      `总行 ${FIXTURE_COUNTS.aggregatedNodes}`,
    )
    await page.getByTestId('enter-modeling').click()
    await expect(page).toHaveURL(/#\/cases\/[0-9a-f-]+\/experiments\/new\?dataset=[0-9a-f-]+/)

    // 7. 轻量 3D IDW：微震预设 z_scale 默认 1，网格自动 11 节点/轴（1331 图元，秒级完成）
    await expect(page.getByTestId('z-scale-manual')).toHaveValue('1')
    await page.getByTestId('exp-name').fill('Live 微震 IDW')
    await page.getByTestId('exp-submit').click()
    await expect(page).toHaveURL(/#\/experiments\/[0-9a-f-]+/)
    await expect(page.getByTestId('run-progress')).toContainText('succeeded', { timeout: 60_000 })
    await expect(page.getByTestId('leaderboard')).toContainText(
      `公共有效点 ${FIXTURE_COUNTS.aggregatedNodes}`,
      { timeout: 30_000 },
    )

    // 8. 成果：完整场（NetCDF 原生体渲染面板）+ X/Y/Z 切片（真实坐标标签为数值）
    await page.getByTestId('open-result').first().click()
    await expect(page).toHaveURL(/#\/results\/[0-9a-f-]+/)
    await expect(page.getByTestId('native-volume-panel')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByTestId('create-asset')).toBeVisible({ timeout: 30_000 })
    await page.getByTestId('tab-slices').click()
    await expect(page.getByTestId('slice-label')).toContainText(/Z = -?\d+(\.\d+)? m/)
    await page.getByTestId('axis-x').click()
    await expect(page.getByTestId('slice-label')).toContainText(/X = -?\d+(\.\d+)? m/)
    await page.getByTestId('axis-y').click()
    await expect(page.getByTestId('slice-label')).toContainText(/Y = -?\d+(\.\d+)? m/)

    // 9. 正式选择（理由必填）
    const reason = `Live 微震选择 ${Date.now()}`
    await page.getByTestId('selection-note').fill(reason)
    await page.getByTestId('selection-submit').click()
    await expect(page.getByTestId('formal-selection-panel')).toContainText(reason)

    // 10. 导出证据 ZIP：下载真实字节并核对通用文件与领域证据条目名
    await page.getByTestId('export-button').click()
    const downloadPromise = page.waitForEvent('download', { timeout: 60_000 })
    await page.getByTestId('export-download').click()
    const download = await downloadPromise
    expect(download.suggestedFilename()).toMatch(/\.zip$/)
    const zipBytes = await readFile(await download.path())
    expect(zipBytes.length).toBeGreaterThan(100)
    expect(zipBytes.subarray(0, 2).toString()).toBe('PK')
    const entries = listZipEntryNames(zipBytes)
    for (const required of [
      'manifest.json',
      'metadata.json',
      'grid.csv',
      'domain_evidence/source_manifest.json',
      'domain_evidence/derivation_report.json',
      `domain_evidence/source_records_${FIXTURE_COUNTS.sourceRecords}.csv`,
      `domain_evidence/invalid_records_${FIXTURE_COUNTS.invalidRecords}.csv`,
      `domain_evidence/rejected_3sigma_${FIXTURE_COUNTS.rejected3sigma}.csv`,
      `domain_evidence/accepted_modeling_${FIXTURE_COUNTS.acceptedModeling}.csv`,
      `domain_evidence/aggregated_nodes_${FIXTURE_COUNTS.aggregatedNodes}.csv`,
    ]) {
      expect(entries).toContain(required)
    }

    // 11. 返回实验 → 返回首页；案例卡持久化可见
    await page.getByTestId('nav-experiment').click()
    await expect(page).toHaveURL(/#\/experiments\/[0-9a-f-]+/)
    await page.getByTestId('nav-home').click()
    await expect(page).toHaveURL(/#\/$/)
    await expect(page.getByText(caseName)).toBeVisible()
  })
})

// ---------------------------------------------------------------------------
// v0.6 专业建模流程（真实链路）：真实 FastAPI + 隔离 SQLite v5 + 真实 Worker。
// 合成 CSV 字节由下面的确定性生成器在测试内现造（沿 30° 拉长、垂直方向快
// 变的光滑场），绝不提交生成的运行时 CSV；全程不派生任何子进程，uvicorn
// 生命周期由 Playwright webServer 管理（测试结束即回收，无进程残留）。
// ---------------------------------------------------------------------------

// 确定性合成 2D 各向异性场：主方向 30° 慢变（长变程）、垂直方向快变。
function professionalSyntheticCsv(): Buffer {
  const rows: string[] = ['x,y,value']
  const az = (30 * Math.PI) / 180
  const cos = Math.cos(az)
  const sin = Math.sin(az)
  for (let i = 0; i < 26; i += 1) {
    for (let j = 0; j < 26; j += 1) {
      const x = i * 5
      const y = j * 5
      const u = x * cos + y * sin
      const v = -x * sin + y * cos
      const value = 100 + 18 * Math.sin(u / 45) + 6 * Math.cos(v / 8) + 2 * Math.sin((x + y) / 30)
      rows.push(`${x},${y},${value.toFixed(6)}`)
    }
  }
  return Buffer.from(`${rows.join('\n')}\n`, 'utf8')
}

test.describe('v0.6 专业建模流程（真实链路）', () => {
  test('上传合成 CSV → 质量门禁 → 诊断 → 确认 → 专业 Kriging 实验 → 折分/不确定性/异常/比较 → 导出 professional/ 证据', async ({
    page,
    request,
  }) => {
    // 1. 真实健康检查（非 Mock）
    const health = await request.get('/api/health')
    expect(health.ok()).toBe(true)

    const caseName = `Live 专业 ${Date.now()}`

    // 2. 首页创建案例 + 上传合成 CSV
    await page.goto('/')
    await page.getByTestId('create-case-card').click()
    await page.getByTestId('case-name').fill(caseName)
    await page.getByTestId('case-file').setInputFiles({
      name: 'synthetic_professional_2d.csv',
      mimeType: 'text/csv',
      buffer: professionalSyntheticCsv(),
    })
    await page.getByTestId('case-submit').click()
    await expect(page).toHaveURL(/#\/cases\/[0-9a-f-]+\/datasets\/[0-9a-f-]+\/prepare/)

    // 3. 映射 + 质量门禁
    await page.getByTestId('mapping-value-name').fill('合成属性')
    await page.getByTestId('mapping-submit').click()
    await expect(page.getByTestId('quality-banner')).toContainText('质量校验通过', {
      timeout: 30_000,
    })

    // 4. 诊断入口（质量门禁通过后才可用）
    await page.getByTestId('start-experiment').click()
    await expect(page).toHaveURL(/#\/cases\/[0-9a-f-]+\/experiments\/new\?dataset=[0-9a-f-]+/)
    await page.getByTestId('professional-entry').click()
    await expect(page).toHaveURL(/#\/datasets\/[0-9a-f-]+\/professional-diagnosis\?case=[0-9a-f-]+/)

    // 5. 诊断：提交 → 有界轮询 → 证据（候选恒为诊断建议）
    await page.getByTestId('start-diagnosis').click()
    await expect(page.getByTestId('job-status')).toBeVisible()
    await expect(page.getByTestId('variogram-panel')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByTestId('suggestion-label')).toContainText('诊断建议，需人工确认')
    await expect(page.getByTestId('candidate-evidence').first()).toBeVisible()

    // 6. 人工确认：显式选择模型 + 写入人工几何先验（az 30 / 主次比 3），note 必填，快照不可变
    await page.getByTestId('confirm-model').selectOption('spherical')
    await page.getByTestId('manual-azimuth').fill('30')
    await page.getByTestId('manual-ratio-minor').fill('3')
    await page.getByTestId('confirm-note').fill('人工确认合成场主方向（Live 夹具）')
    await page.getByTestId('confirm-submit').click()
    await expect(page.getByTestId('confirmation-snapshot')).toBeVisible({ timeout: 30_000 })
    await page.getByTestId('goto-experiment').click()
    await expect(page).toHaveURL(/experiments\/new\?dataset=[0-9a-f-]+&confirmation=[0-9a-f-]+/)

    // 7. 专业 Kriging 实验：网格搜索 spherical × 邻点 {16, 24} → 两个成功候选
    await page.getByTestId('professional-toggle').check()
    await page.getByTestId('algo-kriging').check()
    await expect(page.getByTestId('professional-confirmation')).toBeVisible()
    await page.getByTestId('mode-grid').check()
    await expect(page.getByTestId('count-preview')).toContainText('2 个候选组合')
    await page.getByTestId('exp-name').fill('Live 专业 Kriging')
    await page.getByTestId('exp-submit').click()
    await expect(page).toHaveURL(/#\/experiments\/[0-9a-f-]+/)
    await expect(page.getByTestId('run-progress')).toContainText('succeeded', { timeout: 90_000 })
    await expect(page.getByTestId('candidate-row')).toHaveCount(2, { timeout: 30_000 })

    // 8. 成果工作台 → 专业分析台（真实物化：值场 + 原生标准差 + 经验误差尺度）
    await page.getByTestId('open-result').first().click()
    await expect(page).toHaveURL(/#\/results\/[0-9a-f-]+/)
    const resultUrl = page.url()
    await page.getByTestId('professional-entry').click()
    await expect(page).toHaveURL(/#\/results\/[0-9a-f-]+\/professional/)
    await expect(page.getByTestId('summary-algorithm')).toContainText('ordinary_kriging', {
      timeout: 30_000,
    })
    await expect(page.getByTestId('capability-native-kriging-std')).toContainText('supported')

    // 9. 折分检查 + 不确定性图层切换（真实折证据与不确定性格网）
    await expect(page.getByTestId('fold-inspector')).toBeVisible()
    await expect(page.getByTestId('leakage-badge')).toContainText('未检测到泄漏')
    await expect(page.getByTestId('layer-title')).toContainText('预测值')
    await page.getByTestId('layer-tab-empirical').click()
    await expect(page.getByTestId('layer-title')).toContainText('经验误差尺度')
    await page.getByTestId('layer-tab-kriging-std').click()
    await expect(page.getByTestId('layer-title')).toContainText('Kriging 标准差')

    // 10. 异常：阈值 → 保存 → 有界轮询 → 连通区（数量由真实服务端计算，只断言非零）
    await page.getByTestId('anomaly-threshold').fill('100')
    await expect(page.getByTestId('anomaly-preview-count')).toContainText('预计合格节点')
    await page.getByTestId('anomaly-save').click()
    await expect(page.getByTestId('extraction-identity')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByTestId('component-count')).toContainText(/连通区 [1-9]\d* \/ [1-9]\d* 个/)

    // 11. 兼容比较：同实验第二候选 → 服务端判定兼容并给出成对公共指标差
    await page.locator('[data-test^="comparison-second-"]').first().click()
    await page.getByTestId('comparison-run').click()
    await expect(page.getByTestId('comparison-compatible')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByTestId('common-valid-count')).toContainText(
      /成对公共有效节点 [1-9]\d* 个/,
    )

    // 12. 回成果工作台导出证据 ZIP：真实字节 + professional/ 逻辑名核对
    await page.goto(resultUrl)
    await page.getByTestId('export-button').click()
    const downloadPromise = page.waitForEvent('download', { timeout: 60_000 })
    await page.getByTestId('export-download').click()
    const download = await downloadPromise
    expect(download.suggestedFilename()).toMatch(/\.zip$/)
    const zipBytes = await readFile(await download.path())
    expect(zipBytes.subarray(0, 2).toString()).toBe('PK')
    const entries = listZipEntryNames(zipBytes)
    for (const required of [
      'manifest.json',
      'metadata.json',
      'grid.csv',
      'professional/manifest.json',
      'professional/diagnosis.json',
      'professional/fitted_models.json',
      'professional/variogram_omnidirectional.csv',
      'professional/variogram_directional.csv',
      'professional/anisotropy_confirmation.json',
      'professional/neighborhood.json',
      'professional/fold_assignments.csv',
      'professional/out_of_fold_predictions.csv',
      'professional/residual_summary.json',
      'professional/empirical_error_scale_metadata.json',
      'professional/kriging_standard_deviation_metadata.json',
    ]) {
      expect(entries).toContain(required)
    }
    // 已保存异常提取随导出（提取 ID 为服务端身份，只断言逻辑目录存在组件表）
    expect(
      entries.some(
        (name) =>
          name.startsWith('professional/anomaly_extractions/') && name.endsWith('/components.csv'),
      ),
    ).toBe(true)

    // 13. 返回首页；案例卡持久化可见
    await page.getByTestId('nav-home').click()
    await expect(page).toHaveURL(/#\/$/)
    await expect(page.getByText(caseName)).toBeVisible()
  })
})
