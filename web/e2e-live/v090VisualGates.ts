// v0.9.0 验收级视觉门辅助：截图 + 视口 + 控制台 + 网络失败 + 活跃身份 +
// 像素统计 + 交互 diff 的统一记录。与 v070RenderGates 的像素判据配套使用；
// 只记录与断言真实浏览器证据，绝不把协议成功当作视觉成功。

import { createHash, randomUUID } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { expect } from '@playwright/test'
import type { Page } from '@playwright/test'

export interface V090NetworkEntry {
  method: string
  path: string
  status: number
  at: number
}

export interface V090NetworkFailure {
  method: string
  url: string
  path: string
  // playwright 底层错误文本（如 net::ERR_ABORTED），断言时必须精确匹配
  errorText: string
  at: number
}

export interface V090ConsoleEntry {
  type: string
  text: string
}

export interface V090SceneEvidence {
  tag: string
  viewport: { width: number; height: number }
  pageShot: string | null
  frameShot: string | null
  pixel: Record<string, unknown> | null
  identity: Record<string, unknown> | null
  notes: string[]
}

export interface V090EvidenceRecord {
  run_id: string
  git_commit: string
  sdk_sha256: string
  browser_version: string
  viewport: { width: number; height: number }
  base_url: string
  scenes: V090SceneEvidence[]
  network: V090NetworkEntry[]
  network_failures: V090NetworkFailure[]
  console: V090ConsoleEntry[]
  page_errors: string[]
  timings: Record<string, number>
  extra: Record<string, unknown>
}

export function newRunId(): string {
  const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\..*/, 'Z')
  return `run-${stamp}-${randomUUID().slice(0, 8)}`
}

export function sha256File(file: string): string {
  return createHash('sha256').update(readFileSync(file)).digest('hex')
}

/** 页面级侦听器安装：网络（含失败 errorText 与时间戳）、控制台、pageerror 全量记录。 */
export function installV090Observers(record: V090EvidenceRecord, page: Page): void {
  page.on('requestfinished', async (req) => {
    try {
      const resp = await req.response()
      record.network.push({
        method: req.method(),
        path: new URL(req.url()).pathname,
        status: resp ? resp.status() : 0,
        at: Date.now(),
      })
    } catch {
      // 导航中断的请求不记录
    }
  })
  page.on('requestfailed', (req) => {
    record.network_failures.push({
      method: req.method(),
      url: req.url(),
      path: new URL(req.url()).pathname,
      errorText: req.failure()?.errorText ?? '',
      at: Date.now(),
    })
  })
  page.on('console', (msg) => {
    record.console.push({ type: msg.type(), text: msg.text().slice(0, 400) })
  })
  page.on('pageerror', (err) => {
    record.page_errors.push(String(err))
  })
}

/**
 * fail-closed 网络/控制台断言。唯一允许的失败白名单：
 * 明确的 net::ERR_ABORTED（iframe 拆除/重挂中止），且同一路径随后
 * 真实 200（证明恢复），同时场景像素门已由调用方单独通过。
 * 其余任何 network failure、console error、pageerror 都判失败。
 */
export function assertV090CleanRuntime(record: V090EvidenceRecord): void {
  const succeeded = record.network.filter((n) => n.status === 200)
  const unhandled = record.network_failures.filter((f) => {
    if (f.errorText !== 'net::ERR_ABORTED') return true
    return !succeeded.some((n) => n.path === f.path && n.at > f.at)
  })
  expect(
    unhandled,
    `存在未解释的网络失败：${JSON.stringify(unhandled)}`,
  ).toEqual([])
  const consoleErrors = record.console.filter((c) => c.type === 'error')
  expect(consoleErrors, `存在未处理的控制台错误：${JSON.stringify(consoleErrors)}`).toEqual([])
  expect(record.page_errors, `存在未处理的页面错误：${JSON.stringify(record.page_errors)}`).toEqual([])
}

export function createV090Record(params: {
  runId: string
  gitCommit: string
  sdkSha256: string
  browserVersion: string
  viewport: { width: number; height: number }
  baseUrl: string
}): V090EvidenceRecord {
  return {
    run_id: params.runId,
    git_commit: params.gitCommit,
    sdk_sha256: params.sdkSha256,
    browser_version: params.browserVersion,
    viewport: params.viewport,
    base_url: params.baseUrl,
    scenes: [],
    network: [],
    network_failures: [],
    console: [],
    page_errors: [],
    timings: {},
    extra: {},
  }
}

export class V090EvidenceWriter {
  readonly dir: string
  private created = false

  constructor(root: string, runId: string) {
    this.dir = path.join(root, runId)
  }

  private ensure(): void {
    if (!this.created) {
      mkdirSync(this.dir, { recursive: true })
      this.created = true
    }
  }

  async savePageShot(page: Page, tag: string): Promise<string> {
    this.ensure()
    const file = path.join(this.dir, `${tag}-page.png`)
    await page.screenshot({ path: file })
    return file
  }

  async saveFrameShot(page: Page, tag: string): Promise<string> {
    this.ensure()
    const file = path.join(this.dir, `${tag}-iframe.png`)
    const buffer = await page.getByTestId('volume-frame').screenshot()
    writeFileSync(file, buffer)
    return file
  }

  writeJson(record: V090EvidenceRecord): string {
    this.ensure()
    const file = path.join(this.dir, 'v090-live-evidence.json')
    writeFileSync(file, JSON.stringify(record, null, 2))
    return file
  }
}
