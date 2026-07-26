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

  // 6. 打开成果：完整场 + X/Y/Z 切片（真实坐标标签为数值）
  await page.getByTestId('open-result').first().click()
  await expect(page).toHaveURL(/#\/results\/[0-9a-f-]+/)
  await expect(page.getByTestId('preview-count')).toContainText(/\d+ \/ \d+/, { timeout: 30_000 })
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

    // 8. 成果：完整场 + X/Y/Z 切片（真实坐标标签为数值）
    await page.getByTestId('open-result').first().click()
    await expect(page).toHaveURL(/#\/results\/[0-9a-f-]+/)
    await expect(page.getByTestId('preview-count')).toContainText(/\d+ \/ \d+/, { timeout: 30_000 })
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
