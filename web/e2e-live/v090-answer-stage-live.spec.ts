import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  analyzeVolumePixels,
  expectVolumeContent,
  installLiveProbe,
  probeMessages,
} from './v070RenderGates'
import {
  V090EvidenceWriter,
  assertV090CleanRuntime,
  createV090Record,
  installV090Observers,
  newRunId,
  sha256File,
  type V090EvidenceRecord,
} from './v090VisualGates'

/**
 * v0.9.0 Task 15：答辩级视觉产品真实 SDK live 门。
 *
 * 真实链路：隔离 GEOMODELING_DATA_DIR → preset_cli seed-resistivity /
 * seed-microseismic / seed-gas（example_data 内置源，无外部私有依赖）→
 * 显式 POST 创建三个官方成果的 NetCDF 渲染资产并轮询 ready →
 * 真实 Chromium + 本机 SuperMap3D SDK（RTX GPU）：
 *
 *   1. 指挥舱三案例切换：每案例官方成果真实 rendered（体积像素门）+
 *      变量/单位/辅助色联动 + 截图；
 *   2. 成果页图表→三维联动：趋势剖面图点击驱动正交切片（坐标标签出现），
 *      切片前后画面像素差异真实存在；
 *   3. 答辩模式：六章节导航，电阻率章节场景真实渲染，Escape 退出；
 *   4. 手机 390×844：无横向溢出 + 主动作可见 + 案例切换渲染；
 *
 * 黑屏/Logo-only/背景单色/协议超时/空资产标 ready 一律判失败。
 * GEOMODELING_DATA_DIR 缺失时 beforeAll 直接失败，不静默跳过。
 * 证据写入 docs/evidence/v0.9.0/<run-id>/。
 */

const HERE = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(HERE, '../..')
const SDK_DIST_PATH = path.join(REPO_ROOT, 'web', 'dist', 'SuperMap3D-2026', 'SuperMap3D.js')
const EVIDENCE_ROOT = path.join(REPO_ROOT, 'docs', 'evidence', 'v0.9.0')
const LIVE_PORT = Number(process.env.GEOMODELING_LIVE_PORT ?? 5201)
const BASE = process.env.GEOMODELING_E2E_URL ?? `http://127.0.0.1:${LIVE_PORT}`
const RENDERED_GATE_MS = 90_000
const DESKTOP = { width: 1440, height: 900 }
const PHONE = { width: 390, height: 844 }

const CASES = [
  { caseId: 'resistivity', title: '地下电阻率', unit: 'Ω·m', accent: 'gold' },
  { caseId: 'builtin-microseismic-vx-1911', title: '微震速度', unit: 'km/s', accent: 'violet' },
  { caseId: 'gas', title: '煤层瓦斯', unit: 'ml/g', accent: 'jade' },
] as const

function assertIsolatedDataDir(): string {
  const dir = process.env.GEOMODELING_DATA_DIR
  if (!dir) {
    throw new Error('Live E2E 要求调用环境提供唯一的 GEOMODELING_DATA_DIR')
  }
  const normalized = dir.replace(/\\/g, '/')
  if (normalized.endsWith('var/geomodeling') || normalized.endsWith('var/demo_v041')) {
    throw new Error(`Live E2E 不得使用默认/演示数据目录：${dir}`)
  }
  return dir
}

function seedPreset(dataDir: string, preset: string): void {
  execFileSync(
    'python',
    ['-m', 'geomodeling.preset_cli', `seed-${preset}`, '--data-dir', dataDir],
    {
      cwd: REPO_ROOT,
      env: { ...process.env, PYTHONPATH: path.join(REPO_ROOT, 'src') },
      stdio: ['ignore', 'pipe', 'pipe'],
      timeout: 600_000,
    },
  )
}

interface OfficialIdentity {
  caseId: string
  resultId: string
  assetId: string
  gridSha256: string
  netcdfSha256: string
}

async function ensureOfficialAsset(
  request: APIRequestContext,
  caseId: string,
): Promise<OfficialIdentity> {
  const wsResp = await request.get(`${BASE}/api/cases/${caseId}/workspace`)
  expect(wsResp.ok(), `${caseId} 工作台必须可用`).toBe(true)
  const ws = await wsResp.json()
  const resultId: string | undefined = ws.official_result?.result_id
  expect(resultId, `${caseId} 必须有官方成果`).toBeTruthy()

  const post = await request.post(`${BASE}/api/results/${resultId}/render-assets/netcdf`, {
    data: {},
  })
  expect([200, 201, 409]).toContain(post.status())
  const deadline = Date.now() + 300_000
  for (;;) {
    const get = await request.get(`${BASE}/api/results/${resultId}/render-assets/netcdf`)
    if (get.ok()) {
      const asset = await get.json()
      if (asset.status === 'ready' && asset.id && asset.netcdf_sha256) {
        return {
          caseId,
          resultId: resultId!,
          assetId: asset.id,
          gridSha256: asset.grid_sha256,
          netcdfSha256: asset.netcdf_sha256,
        }
      }
      if (asset.status === 'failed') {
        throw new Error(`${caseId} 渲染资产失败：${JSON.stringify(asset.error)}`)
      }
    }
    if (Date.now() > deadline) throw new Error(`${caseId} 渲染资产等待 ready 超时`)
    await new Promise((r) => setTimeout(r, 2000))
  }
}

const runId = newRunId()
const writer = new V090EvidenceWriter(EVIDENCE_ROOT, runId)
let record: V090EvidenceRecord
const identities: OfficialIdentity[] = []

test.beforeAll(async ({ request }) => {
  test.setTimeout(900_000)
  const dataDir = assertIsolatedDataDir()
  seedPreset(dataDir, 'resistivity')
  seedPreset(dataDir, 'microseismic')
  seedPreset(dataDir, 'gas')
  for (const c of CASES) {
    identities.push(await ensureOfficialAsset(request, c.caseId))
  }
  const gitCommit = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: REPO_ROOT })
    .toString()
    .trim()
  record = createV090Record({
    runId,
    gitCommit,
    sdkSha256: sha256File(SDK_DIST_PATH),
    browserVersion: '',
    viewport: DESKTOP,
    baseUrl: BASE,
  })
})

test.afterAll(async ({ browser }) => {
  record.browser_version = browser.version()
  record.extra.official_identities = identities
  writer.writeJson(record)
})

// worker 进程被回收/拆分运行时，每个实例也保有自己场景的部分记录
test.afterEach(() => {
  if (record) writer.writeJson(record)
})

// fail-closed：每个用例结束时断言累计网络失败/控制台错误/页面错误全为零
// （仅允许「ERR_ABORTED 且同路径随后 200」的可证明恢复条目；断言前等待
// 在途请求结算，避免把尚未记录的恢复误判为失败）
test.afterEach(async () => {
  if (!record) return
  await new Promise((r) => setTimeout(r, 800))
  assertV090CleanRuntime(record)
})

async function waitSceneRendered(page: Page, tag: string) {
  const phase = page.getByTestId('volume-phase')
  await expect(phase, `${tag}：相位必须到达已渲染`).toHaveText('已渲染', {
    timeout: RENDERED_GATE_MS,
  })
  const messages = await probeMessages(page)
  expect(messages.filter((m) => m.type === 'ERROR'), `${tag}：不得有协议错误`).toEqual([])
}

test('指挥舱三案例切换真实渲染（桌面 1440×900）', async ({ page }) => {
  test.setTimeout(600_000)
  await page.setViewportSize(DESKTOP)
  installV090Observers(record, page)
  await installLiveProbe(page)
  await page.goto('/')
  await expect(page.getByTestId('command-center')).toBeVisible()

  for (const c of CASES) {
    const tag = `home-${c.caseId}`
    await page.getByTestId('case-rail-item').filter({ hasText: c.title }).click()
    const scene = page.getByTestId('command-center-scene')
    await expect(scene).toContainText(c.title)
    await expect(scene).toContainText(c.unit)
    await expect(page.getByTestId('command-center')).toHaveAttribute('data-case-accent', c.accent)
    await waitSceneRendered(page, tag)

    const metrics = await analyzeVolumePixels(page, await page.getByTestId('volume-frame').screenshot())
    expectVolumeContent(metrics, `${tag} Volume`, { minNonBg: 2000, minCoverage: 0.15 })
    await expect(page.getByTestId('home-findings')).toContainText('有效数据')
    await expect(page.getByTestId('home-evidence-dock')).toContainText('溯源')

    const pageShot = await writer.savePageShot(page, tag)
    const frameShot = await writer.saveFrameShot(page, tag)
    record.scenes.push({
      tag,
      viewport: DESKTOP,
      pageShot: path.basename(pageShot),
      frameShot: path.basename(frameShot),
      pixel: metrics as unknown as Record<string, unknown>,
      identity: identities.find((x) => x.caseId === c.caseId) as unknown as Record<string, unknown>,
      notes: [],
    })
  }
})

test('成果页图表→三维联动：趋势点击驱动切片', async ({ page }) => {
  test.setTimeout(300_000)
  const gas = identities.find((x) => x.caseId === 'gas')!
  await page.setViewportSize(DESKTOP)
  installV090Observers(record, page)
  await installLiveProbe(page)
  await page.goto(`/#/results/${gas.resultId}`)
  await waitSceneRendered(page, 'linkage-gas')

  // 证据带切到趋势剖面并点击中段分箱点
  await page.getByTestId('dock-tab-trends').click()
  const chart = page.getByTestId('axis-trend-chart')
  await expect(chart).toBeVisible()
  const before = await page.getByTestId('volume-frame').screenshot()
  const box = await chart.boundingBox()
  expect(box).toBeTruthy()
  await page.mouse.click(box!.x + box!.width * 0.5, box!.y + box!.height * 0.5)
  // 切片坐标标签出现（模式切换为 slice 并应用权威剖面）
  await expect(page.getByTestId('slice-coordinate-label')).toBeVisible({ timeout: 60_000 })
  await page.waitForTimeout(1200)
  const after = await page.getByTestId('volume-frame').screenshot()
  expect(Buffer.compare(before, after)).not.toBe(0)
  record.extra.linkage = { result_id: gas.resultId, pixel_diff: !before.equals(after) }
  await writer.savePageShot(page, 'linkage-gas')
})

test('答辩模式：六章节与案例章节真实场景', async ({ page }) => {
  test.setTimeout(600_000)
  await page.setViewportSize(DESKTOP)
  installV090Observers(record, page)
  await installLiveProbe(page)
  await page.goto('/#/presentation')
  await expect(page.getByTestId('presentation-overlay')).toBeVisible()
  // 答辩全屏：全局头与编辑/危险入口不可见；服务状态保留在控制层
  await expect(page.getByTestId('app-global-header')).toHaveCount(0)
  await expect(page.getByTestId('global-create-case')).toHaveCount(0)
  await expect(page.getByTestId('shell-trash-link')).toHaveCount(0)
  await expect(page.getByTestId('presentation-service-status')).toBeVisible()
  await expect(page.getByTestId('chapter-overview')).toContainText('数据接入')

  const chapterTitles = ['地下电阻率', '微震速度', '煤层瓦斯含量', '自定义数据', '创新点与已知边界']
  for (const title of chapterTitles) {
    await page.keyboard.press('ArrowRight')
    await expect(page.getByTestId('presentation-title')).toContainText(title)
  }
  // 电阻率章节真实渲染门
  await page.getByTestId('presentation-chapter-resistivity').click()
  await waitSceneRendered(page, 'presentation-resistivity')
  const metrics = await analyzeVolumePixels(page, await page.getByTestId('volume-frame').screenshot())
  expectVolumeContent(metrics, '答辩电阻率章节 Volume', { minNonBg: 2000, minCoverage: 0.15 })
  await writer.savePageShot(page, 'presentation-resistivity')

  await page.keyboard.press('Escape')
  await expect(page.getByTestId('command-center')).toBeVisible()
})

test('手机 390×844：摘要优先顺序 + 全屏三维入口 + 案例切换渲染', async ({ page }) => {
  test.setTimeout(300_000)
  await page.setViewportSize(PHONE)
  installV090Observers(record, page)
  await installLiveProbe(page)
  await page.goto('/')
  await expect(page.getByTestId('command-center')).toBeVisible()
  await expect(page.getByTestId('command-primary-action')).toBeVisible()
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)

  // 首屏顺序：案例选择 → 案例摘要 → 关键发现 → 证据带 → 全屏三维入口
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
  // 关键发现首屏区可见（不等打开三维）
  await expect(page.getByTestId('home-findings')).toContainText('有效数据')
  // 摘要优先顺序证据截图（打开全屏三维之前）
  await writer.savePageShot(page, 'phone-summary-first')

  // 切换瓦斯并打开全屏三维（同一面板转为视口覆盖，iframe 不重建）
  await page.getByTestId('case-rail-item').filter({ hasText: '煤层瓦斯' }).click()
  await expect(page.getByTestId('command-center-scene')).toContainText('ml/g')
  await page.getByTestId('phone-open-scene').scrollIntoViewIfNeeded()
  await page.getByTestId('phone-open-scene').click()
  await expect(page.getByTestId('phone-close-scene')).toBeVisible()
  await waitSceneRendered(page, 'phone-gas')
  const metrics = await analyzeVolumePixels(page, await page.getByTestId('volume-frame').screenshot())
  expectVolumeContent(metrics, '手机瓦斯 Volume', { minNonBg: 800, minCoverage: 0.08 })
  await writer.savePageShot(page, 'phone-gas')
  // 关闭恢复摘要布局
  await page.getByTestId('phone-close-scene').click()
  const closedBox = await page.getByTestId('command-center-scene').boundingBox()
  expect(closedBox!.height).toBeLessThan(PHONE.height * 0.9)
})
