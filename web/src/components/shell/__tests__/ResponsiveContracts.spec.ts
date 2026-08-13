import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import * as client from '../../../api/client'
import type { CaseSummary } from '../../../api/types'
import AppShell from '../AppShell.vue'
import HomeView from '../../../views/HomeView.vue'
import { readFileSync, readdirSync } from 'node:fs'

// vitest 的 CSS ?raw 导入会被裁剪为空串；样式规则断言直接读文件（vitest 以 web/ 为 cwd）
const motionCss = String(readFileSync('src/styles/motion.css'))
const tokensCss = String(readFileSync('src/styles/tokens.css'))
const globalCss = String(readFileSync('src/styles/index.css'))
const caseRailSource = String(readFileSync('src/components/shell/CaseRail.vue'))
const appShellSource = String(readFileSync('src/components/shell/AppShell.vue'))
const resultWorkbenchSource = String(readFileSync('src/views/ResultWorkbenchView.vue'))

// v0.9.0 Task 14：响应式/无障碍/动效合同（静态契约层；
// 真实视口像素级门在 web/e2e/v090-responsive.spec.ts）。

vi.mock('../../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../api/client')>()
  return {
    ...actual,
    fetchHealth: vi.fn(),
    fetchCases: vi.fn(),
    fetchCaseWorkspace: vi.fn(),
    fetchAnalysisSummary: vi.fn(),
    fetchResultRenderCapability: vi.fn(),
    fetchResultRenderAsset: vi.fn(),
    createResultRenderAsset: vi.fn(),
    trashCase: vi.fn(),
  }
})

const PRESET: CaseSummary = {
  case_id: 'gas',
  title: '煤层瓦斯',
  status: 'active',
  workspace_kind: 'builtin_preset',
  capabilities: { data_summary: true, experiments: true, official_result: true, native_volume: true },
  official_result: { result_id: 'gas-r', url: '/results/gas-r', materialized: true },
  provenance_summary: {
    badge: '散点预置 · 官方基线成果',
    data_form: '标准化散点 · 58 个合格样品',
    fields: ['X', 'Y', 'Z', 'CH4_content'],
    value_unit: 'ml/g',
    coordinate_kind: 'local_linear',
  },
  links: { detail: null, publish_status: null },
}

async function mountHome() {
  vi.mocked(client.fetchHealth).mockResolvedValue({
    status: 'ok',
    version: '0.9.0',
    time: '2026-08-10T00:00:00+00:00',
  })
  vi.mocked(client.fetchCases).mockResolvedValue({ cases: [PRESET] })
  vi.mocked(client.fetchCaseWorkspace).mockResolvedValue({
    ...PRESET,
    workspace_kind: 'builtin_preset',
    capabilities: PRESET.capabilities!,
    primary_dataset: null,
    official_result: PRESET.official_result!,
    provenance_summary: PRESET.provenance_summary!,
    links: PRESET.links,
  } as never)
  vi.mocked(client.fetchResultRenderCapability).mockRejectedValue(new Error('skip'))
  const stub = { template: '<div />' }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: HomeView },
      { path: '/trash', name: 'trash', component: stub },
      { path: '/cases/new', name: 'case-create', component: stub },
      { path: '/cases/:caseId', name: 'case-workspace', component: stub },
      { path: '/results/:resultId', name: 'result-workbench', component: stub },
    ],
  })
  await router.push('/')
  const wrapper = mount(AppShell, {
    global: { plugins: [router, ElementPlus] },
    attachTo: document.body,
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  document.body.innerHTML = ''
  vi.clearAllMocks()
})

describe('responsive & accessibility contracts', () => {
  it('uses one home entry instead of duplicating home and cases navigation', () => {
    const source = String(readFileSync('src/components/shell/AppHeader.vue'))
    expect(source).toContain('data-test="shell-home-link"')
    expect(source).not.toContain('data-test="shell-nav-cases"')
    expect(source).not.toContain("query: { focus: 'cases' }")
  })

  it('places the Chinese platform title at the geometric center of the global header', () => {
    const source = String(readFileSync('src/components/shell/AppHeader.vue'))
    expect(source).toContain('地质属性三维建模与空间分析平台')
    expect(source).toMatch(/\.platform-title\s*\{[^}]*position:\s*absolute;[^}]*left:\s*50%;[^}]*transform:\s*translateX\(-50%\);/s)
  })

  it('uses a readable global type scale and shared product-page grid', () => {
    expect(tokensCss).toContain('--s1-font-xs: 12px')
    expect(tokensCss).toContain('--s1-font-md: 14px')
    expect(tokensCss).toContain('--s1-page-standard: 1440px')
    expect(globalCss).toContain('.product-page')
  })

  it('only locks the immersive result workbench when the desktop viewport is tall enough', () => {
    const tallDesktopQuery = '@media (min-width: 1200px) and (min-height: 820px)'
    expect(appShellSource).toContain(tallDesktopQuery)
    expect(resultWorkbenchSource).toContain(tallDesktopQuery)
    const queryIndex = appShellSource.indexOf(tallDesktopQuery)
    const overflowLockIndex = appShellSource.indexOf('overflow: hidden', queryIndex)
    expect(overflowLockIndex).toBeGreaterThan(queryIndex)
    expect(resultWorkbenchSource).not.toContain('@media (min-width: 1200px) {')
  })

  it('locks the desktop command center to one viewport while keeping narrower layouts in document flow', () => {
    expect(appShellSource).toContain("route.name === 'home'")
    expect(appShellSource).toMatch(
      /@media \(min-width: 961px\)[\s\S]*?\.app-shell\.command-center-route\s*\{[^}]*height:\s*100dvh;[^}]*overflow:\s*hidden;/s,
    )
  })

  it('reduces shared page padding on short laptop screens without changing browser zoom', () => {
    expect(globalCss).toContain('@media (max-height: 819px) and (min-width: 901px)')
    expect(globalCss).toMatch(/@media \(max-height: 819px\)[\s\S]*?\.product-page\s*\{[^}]*padding-block:/s)
  })

  it('user-facing comparison pages consistently say 模型比较', () => {
    const sources = [
      'src/views/CandidateComparisonView.vue',
      'src/components/analysis/analysisTypes.ts',
      'src/components/analysis/ModelComparisonPanel.vue',
    ].map((path) => String(readFileSync(path)))
    for (const source of sources) expect(source).not.toContain('模型对比')
  })

  it('mobile case actions keep clear space below the sticky global header', () => {
    expect(caseRailSource).toContain('scroll-margin-top: 72px')
  })

  it('browser flows do not reference retired v6 navigation hooks', () => {
    const specFiles = ['e2e', 'e2e-live'].flatMap((dir) =>
      readdirSync(dir)
        .filter((name) => name.endsWith('.spec.ts'))
        .map((name) => `${dir}/${name}`),
    )
    for (const path of specFiles) {
      const source = String(readFileSync(path))
      for (const retiredId of ['v6-nav-experiment', 'v6-nav-home']) {
        expect(source, `${path} 仍引用退役导航 ${retiredId}`).not.toContain(retiredId)
      }
    }
  })

  it('mobile header collapses utilities instead of stacking the primary action vertically', () => {
    const headerSource = String(readFileSync('src/components/shell/AppHeader.vue'))
    expect(headerSource).toContain('data-test="shell-mobile-menu"')
    expect(headerSource).not.toContain('.action.primary {\n    padding: 6px 10px')
  })

  it('keeps the new AI settings action compact on laptop-width screens', () => {
    const headerSource = String(readFileSync('src/components/shell/AppHeader.vue'))
    expect(headerSource).toContain('class="ai-settings-label"')
    expect(headerSource).toMatch(/@media \(max-width: 1200px\)[\s\S]*\.ai-settings-label\s*\{[\s\S]*display:\s*none/)
  })

  it('app shell exposes exactly one main landmark', async () => {
    const wrapper = await mountHome()
    expect(wrapper.findAll('main')).toHaveLength(1)
    expect(wrapper.get('main').attributes('id')).toBe('main-content')
    wrapper.unmount()
  })

  it('home shows exactly one primary action for the selected case', async () => {
    const wrapper = await mountHome()
    expect(wrapper.findAll('[data-primary-action="true"]')).toHaveLength(1)
    wrapper.unmount()
  })

  it('all header buttons/links have accessible names', async () => {
    const wrapper = await mountHome()
    const header = wrapper.get('header')
    const controls = [
      ...header.findAll('button'),
      ...header.findAll('a'),
    ]
    expect(controls.length).toBeGreaterThan(0)
    for (const el of controls) {
      const name = el.text().trim() || el.attributes('aria-label') || el.attributes('title')
      expect(name).toBeTruthy()
    }
    wrapper.unmount()
  })

  it('reduced motion zeroes nonessential animation via tokens', () => {
    expect(motionCss).toContain('prefers-reduced-motion: reduce')
    expect(motionCss).toContain('animation-duration: 1ms !important')
    expect(motionCss).toContain('transition-duration: 1ms !important')
  })

  it('defines restrained global feedback for actions, disclosures, and page entry', () => {
    expect(motionCss).toContain('.gmp-route-enter')
    expect(motionCss).toContain('details > :not(summary)')
    expect(motionCss).toContain(':where(button, .gmp-btn, .el-button)')
    expect(motionCss).not.toContain('transition: all')
  })

  it('native interactive elements receive a shared visible keyboard focus treatment', () => {
    expect(globalCss).toContain(':where(a, button, input, select, textarea, summary):focus-visible')
    expect(globalCss).toContain('outline: 2px solid var(--s1-cyan-strong)')
  })

  it('design tokens define the four case accents and elevation levels', () => {
    for (const accent of ['--s1-accent-gold', '--s1-accent-violet', '--s1-accent-jade', '--s1-accent-cyan']) {
      expect(tokensCss).toContain(accent)
    }
    for (const level of ['--s1-elevation-1', '--s1-elevation-2', '--s1-elevation-3']) {
      expect(tokensCss).toContain(level)
    }
  })

  it('faint/dim text tokens meet 4.5:1 contrast on all dark surfaces (projection readability)', () => {
    const hexOf = (name: string) => {
      const m = tokensCss.match(new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})`))
      expect(m, `token ${name} 必须存在`).toBeTruthy()
      return m![1]
    }
    const lum = (hex: string) => {
      const channels = [0, 2, 4].map((i) => {
        const c = parseInt(hex.slice(1).slice(i, i + 2), 16) / 255
        return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
      })
      return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
    }
    const contrast = (fg: string, bg: string) => {
      const [l1, l2] = [lum(fg), lum(bg)].sort((a, b) => b - a)
      return (l1 + 0.05) / (l2 + 0.05)
    }
    const surfaces = ['--s1-canvas', '--s1-surface-1', '--s1-surface-2'].map(hexOf)
    for (const textToken of ['--s1-text-faint', '--s1-text-dim', '--s1-text']) {
      const fg = hexOf(textToken)
      for (const bg of surfaces) {
        expect(
          contrast(fg, bg),
          `${textToken}(${fg}) 在 ${bg} 上对比度必须 ≥ 4.5`,
        ).toBeGreaterThanOrEqual(4.5)
      }
    }
  })
})
