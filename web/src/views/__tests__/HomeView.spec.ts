import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import * as client from '../../api/client'
import type { CaseSummary } from '../../api/types'
import HomeView from '../HomeView.vue'
import homeViewSource from '../HomeView.vue?raw'

// v0.6.1：首页上传案例卡的主打成果入口（featured_result）组件级回归。

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    fetchCases: vi.fn(),
    fetchRhoPublishStatus: vi.fn(),
    fetchTrashCases: vi.fn(),
    trashCase: vi.fn(),
  }
})

const BENCH_CASE: CaseSummary = {
  case_id: 'case-bench-32',
  title: '体积基准 32³',
  status: 'active',
  source_kind: 'upload',
  case_type: 'generic',
  created_at: '2026-08-01T00:00:00+00:00',
  featured_result: {
    result_id: 'cand-bench-32',
    url: '/results/cand-bench-32',
    materialized: true,
  },
  links: { detail: '/api/cases/case-bench-32', publish_status: null },
}

const PLAIN_UPLOAD_CASE: CaseSummary = {
  case_id: 'case-plain',
  title: '普通上传案例',
  status: 'active',
  source_kind: 'upload',
  case_type: 'generic',
  created_at: '2026-08-01T00:00:00+00:00',
  featured_result: null,
  links: { detail: '/api/cases/case-plain', publish_status: null },
}

// v0.7.0：微震 CSV 预置卡（builtin_preset 工作台身份）
const PRESET_CASE: CaseSummary = {
  case_id: 'builtin-microseismic-vx-1911',
  title: '微震速度',
  status: 'active',
  workspace_kind: 'builtin_preset',
  capabilities: {
    data_summary: true,
    experiments: true,
    official_result: true,
    native_volume: true,
  },
  official_result: { result_id: 'r-1', url: '/results/r-1', materialized: true },
  provenance_summary: {
    badge: 'CSV 预置 · 官方普通克里金成果',
    data_form: '三维 X/Y/Z/Vx（局部测线坐标）',
    value_unit: 'km/s',
    coordinate_kind: 'local_linear',
  },
  links: { detail: null, publish_status: null },
}

const RESISTIVITY_CARD: CaseSummary = {
  case_id: 'resistivity',
  title: '地下电阻率',
  data_form: '三维 X/Y/Z/RHO（局部工程坐标）',
  status: 'active',
  coordinate: '局部工程坐标，EPSG 未确认',
  unit_note: 'RHO 单位待来源确认',
  source_kind: 'builtin_legacy',
  workspace_kind: 'builtin_legacy',
  capabilities: {
    data_summary: true,
    experiments: false,
    official_result: false,
    native_volume: true,
  },
  links: { detail: '/api/cases/resistivity', publish_status: null },
}

async function mountHome(cases: CaseSummary[]) {
  vi.mocked(client.fetchCases).mockResolvedValue({ cases })
  vi.mocked(client.fetchRhoPublishStatus).mockRejectedValue(new Error('iServer offline'))
  vi.mocked(client.fetchTrashCases).mockResolvedValue({ cases: [] })
  vi.mocked(client.trashCase).mockResolvedValue({})
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: HomeView },
      { path: '/trash', name: 'trash', component: { template: '<div />' } },
      { path: '/results/:resultId', name: 'result-workbench', component: { template: '<div />' } },
      { path: '/cases/:caseId', name: 'case-workspace', component: { template: '<div />' } },
      {
        path: '/cases/:caseId/experiments/new',
        name: 'experiment-create',
        component: { template: '<div />' },
      },
      { path: '/cases/new', name: 'case-create', component: { template: '<div />' } },
    ],
  })
  await router.push('/')
  const wrapper = mount(HomeView, {
    global: { plugins: [router, ElementPlus] },
    attachTo: document.body,
  })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  document.body.innerHTML = ''
  vi.clearAllMocks()
})

describe('HomeView featured_result 入口', () => {
  it('有 featured_result 的上传卡：主入口直达成果页，新建实验为次操作', async () => {
    const { wrapper, router } = await mountHome([BENCH_CASE])

    const primary = wrapper.find('[data-test="open-featured-result"]')
    expect(primary.exists()).toBe(true)
    expect(primary.text()).toContain('查看体渲染成果')
    // 次级操作保留且不与主入口混淆
    const secondary = wrapper.find('[data-test="new-experiment"]')
    expect(secondary.exists()).toBe(true)
    expect(secondary.text()).toContain('新建实验')
    // 不再显示「进入调参实验室」主按钮
    expect(wrapper.text()).not.toContain('进入调参实验室')

    // 主入口导航到 featured_result.url，且不触发卡片点击的实验创建导航
    await primary.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/results/cand-bench-32')
  })

  it('新建实验次操作仍进入实验创建页', async () => {
    const { wrapper, router } = await mountHome([BENCH_CASE])

    await wrapper.find('[data-test="new-experiment"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/cases/case-bench-32/experiments/new')
  })

  it('无 featured_result 的上传卡：主入口进入统一工作台（不再有调参实验室语义）', async () => {
    const { wrapper, router } = await mountHome([PLAIN_UPLOAD_CASE])

    expect(wrapper.find('[data-test="open-featured-result"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="new-experiment"]').exists()).toBe(false)
    // v0.7.0：不再出现「进入调参实验室」产品语义
    expect(wrapper.text()).not.toContain('进入调参实验室')

    // 主命令：进入统一工作台
    const primary = wrapper.find('[data-test="enter-case-workspace"]')
    expect(primary.exists()).toBe(true)
    await primary.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/cases/case-plain')
  })

  it('有 featured_result 的上传卡：卡片点击也进入统一工作台', async () => {
    const { wrapper, router } = await mountHome([BENCH_CASE])

    // 按钮行为不回归：主入口直达成果、次操作新建实验
    expect(wrapper.find('[data-test="open-featured-result"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="new-experiment"]').exists()).toBe(true)

    // 卡片点击（非按钮区）→ 统一工作台
    await wrapper.find('.case-card').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/cases/case-bench-32')
  })
})

describe('HomeView v0.7.0 工作台入口', () => {
  it('routes every enterable card to its workspace and gives a preset an official-result shortcut', async () => {
    const { wrapper, router } = await mountHome([PRESET_CASE, RESISTIVITY_CARD])

    // 无 DAT 文案；预置徽标为 CSV 预置说明
    expect(wrapper.text()).not.toContain('导入微震 DAT')
    expect(wrapper.text()).toContain('CSV 预置 · 官方普通克里金成果')

    // 预置卡主命令：进入工作台
    const buttons = wrapper.findAll('[data-test="enter-case-workspace"]')
    expect(buttons.length).toBe(2)
    await buttons[0].trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe(`/cases/${PRESET_CASE.case_id}`)

    // 预置卡次命令：官方成果直达
    await router.push('/')
    const official = wrapper.find('[data-test="open-official-result"]')
    expect(official.exists()).toBe(true)
    await official.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/results/r-1')
  })

  it('卡片点击同样进入统一工作台（预置）', async () => {
    const { wrapper, router } = await mountHome([PRESET_CASE])
    await wrapper.find('.case-card').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe(`/cases/${PRESET_CASE.case_id}`)
  })
})

// ---------------------------------------------------------------------------
// v0.8.0：电阻率迁移为 builtin_preset 散点预置后的首页卡片语义。
// 卡片文案逐字来自后端 DTO provenance_summary，前端不按 case_id 硬编码分支；
// 旧 legacy/S3M/DAT 语样与旧 legacy 页链接不得出现，入口统一为 /cases/resistivity。
// ---------------------------------------------------------------------------

// 已 seed 的电阻率预置卡（workspace_case_card 形态）
const RESISTIVITY_PRESET_CARD: CaseSummary = {
  case_id: 'resistivity',
  title: '地下电阻率',
  status: 'active',
  source_kind: 'builtin_preset',
  workspace_kind: 'builtin_preset',
  capabilities: {
    data_summary: true,
    experiments: true,
    official_result: true,
    native_volume: true,
  },
  official_result: { result_id: 'rho-official-1', url: '/results/rho-official-1', materialized: true },
  provenance_summary: {
    badge: '散点预置 · 官方普通克里金成果',
    data_form: '标准化散点 · 17,549 个节点',
    fields: ['X', 'Y', 'Z', 'RHO'],
    value_unit: 'RHO 单位待来源确认',
    coordinate_kind: 'local_linear',
  },
  links: { detail: '/api/cases/resistivity', publish_status: null },
}

// 未 seed 的电阻率预置描述卡（resistivity_preset_workspace_card 形态）
const RESISTIVITY_DESCRIPTOR_CARD: CaseSummary = {
  case_id: 'resistivity',
  title: '地下电阻率',
  status: 'initialization_required',
  source_kind: 'builtin_preset',
  workspace_kind: 'builtin_preset',
  capabilities: {
    data_summary: false,
    experiments: false,
    official_result: false,
    native_volume: false,
  },
  official_result: null,
  provenance_summary: {
    badge: '散点预置 · 官方普通克里金成果',
    data_form: '标准化散点 · 17,549 个节点',
    fields: ['X', 'Y', 'Z', 'RHO'],
    value_unit: 'RHO 单位待来源确认',
    coordinate_kind: 'local_linear',
  },
  links: { detail: null, publish_status: null },
}

function fieldRows(wrapper: ReturnType<typeof mount>) {
  return wrapper
    .findAll('.case-body p')
    .filter((p) => p.find('span').exists() && p.find('span').text() === '字段')
}

describe('HomeView v0.8.0 电阻率散点预置卡', () => {
  it('已 seed 电阻率预置卡：统一文案与操作，无 legacy/S3M/DAT 语样与绝对路径', async () => {
    const { wrapper, router } = await mountHome([RESISTIVITY_PRESET_CARD])

    const text = wrapper.text()
    expect(text).toContain('散点预置 · 官方普通克里金成果')
    expect(text).toContain('标准化散点 · 17,549 个节点')
    expect(text).toContain('RHO 单位待来源确认')
    // 已 seed 卡同样渲染字段行（设计 §5 统一口径，逐字来自 DTO fields 键）
    const rows = fieldRows(wrapper)
    expect(rows.length).toBe(1)
    expect(rows[0].text()).toContain('X/Y/Z/RHO')
    expect(text).not.toContain('S3M')
    expect(text).not.toContain('DAT')
    expect(text).not.toContain('v0.3.1')
    expect(text).not.toContain('调参实验室')
    expect(text).not.toMatch(/[A-Za-z]:\\/)
    expect(text).not.toContain('/home/')
    expect(text).not.toContain('/Users/')

    // 主命令：进入统一工作台（旧 legacy 电阻率页不再是入口）
    await wrapper.find('[data-test="enter-case-workspace"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/cases/resistivity')

    // 次命令：查看官方成果直达
    await router.push('/')
    await flushPromises()
    const official = wrapper.find('[data-test="open-official-result"]')
    expect(official.exists()).toBe(true)
    expect(official.text()).toContain('查看官方成果')
    await official.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/results/rho-official-1')
  })

  it('未 seed 描述卡：标准化散点 · 17,549 个节点与字段行来自 DTO', async () => {
    const { wrapper } = await mountHome([RESISTIVITY_DESCRIPTOR_CARD])

    const text = wrapper.text()
    expect(text).toContain('标准化散点 · 17,549 个节点')
    expect(text).toContain('散点预置 · 官方普通克里金成果')
    expect(text).toContain('RHO 单位待来源确认')
    const rows = fieldRows(wrapper)
    expect(rows.length).toBe(1)
    expect(rows[0].text()).toContain('X/Y/Z/RHO')

    // featured_result 无态：无官方成果直达，仅保留进入工作台主命令
    expect(wrapper.find('[data-test="open-official-result"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="enter-case-workspace"]').exists()).toBe(true)
  })

  it('微震预置卡显示不变：无 fields 键时不渲染字段行', async () => {
    const { wrapper } = await mountHome([PRESET_CASE])

    expect(wrapper.text()).toContain('CSV 预置 · 官方普通克里金成果')
    expect(wrapper.text()).toContain('三维 X/Y/Z/Vx（局部测线坐标）')
    expect(fieldRows(wrapper).length).toBe(0)
    expect(wrapper.find('[data-test="open-official-result"]').exists()).toBe(true)
  })

  it('电阻率预置卡按钮均有可访问名称', async () => {
    const { wrapper } = await mountHome([RESISTIVITY_PRESET_CARD])
    const buttons = wrapper.findAll('button')
    expect(buttons.length).toBeGreaterThan(0)
    for (const btn of buttons) {
      const name = btn.text().trim() || btn.attributes('aria-label') || btn.attributes('title')
      expect(name).toBeTruthy()
    }
  })

  it('390x844 移动端：首页携带窄屏响应式规则（像素级门在 e2e-live）', () => {
    // 单元层锁定响应式规则存在；真实 390x844 无横向溢出断言沿用
    // web/e2e 的 Playwright 模式（setViewportSize + scrollWidth ≤ 390）。
    expect(homeViewSource).toContain('@media (max-width: 480px)')
  })
})
