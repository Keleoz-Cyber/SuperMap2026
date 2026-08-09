// v0.9.0 答辩级视觉门辅助：截图 + 视口 + 控制台 + 网络失败 + 活跃身份 +
// 像素统计 + 交互 diff 的统一记录。与 v070RenderGates 的像素判据配套使用；
// 只记录与断言真实浏览器证据，绝不把协议成功当作视觉成功。

import { createHash, randomUUID } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import type { Page } from '@playwright/test'

export interface V090NetworkEntry {
  method: string
  path: string
  status: number
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
  network_failures: string[]
  console: V090ConsoleEntry[]
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

/** 页面级侦听器安装：网络与控制台全量记录（证据用，不过滤）。 */
export function installV090Observers(record: V090EvidenceRecord, page: Page): void {
  page.on('requestfinished', async (req) => {
    try {
      const resp = await req.response()
      record.network.push({
        method: req.method(),
        path: new URL(req.url()).pathname,
        status: resp ? resp.status() : 0,
      })
    } catch {
      // 导航中断的请求不记录
    }
  })
  page.on('requestfailed', (req) => {
    record.network_failures.push(`${req.method()} ${new URL(req.url()).pathname}`)
  })
  page.on('console', (msg) => {
    record.console.push({ type: msg.type(), text: msg.text().slice(0, 400) })
  })
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
