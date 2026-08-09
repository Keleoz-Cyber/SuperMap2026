import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import * as client from '../../api/client'
import type { CaseSummary, CaseWorkspaceSummary, RenderAssetRecord, RenderCapability } from '../../api/types'
import HomeView from '../HomeView.vue'
import homeViewSource from '../HomeView.vue?raw'

// v0.9.0：首页综合指挥舱形态下的入口合同回归。
// 入口 data-test 与 v0.8 保持一致（case-card/enter-case-workspace/
// open-official-result/open-featured-result/new-experiment/create-case-card/
// trash-case-btn/download-demo-data），交互模型改为「点击选中 + 显式按钮进入」。

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    fetchCases: vi.fn(),
    fetchCaseWorkspace: vi.fn(),
    fetchAnalysisSummary: vi.fn(),
    fetchResultRenderCapability: vi.fn(),
    fetchResultRenderAsset: vi.fn(),
    createResultRenderAsset: vi.fn(),
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

const RESISTIVITY_PRESET_CARD: CaseSummary = {
  case_id: 'resistivity',
  title: '地下电阻率',
  status: 'active',
  source_kind: 'builtin_preset',
  workspace_kind: 'builtin_preset',
  capabilities: { data_summary: true, experiments: true, official_result: true, native_volume: true },
  official_result: { result_id: 'rho-official-1', url: '/results/rho-official-1', materialized: true },
  provenance_summary: {
    badge: '散点预置 · 官方普通克里金成果',
    data_form: '标准化散点 · 17,549 个节点',
    fields: ['X', 'Y', 'Z', 'RHO'],
    value_unit: 'Ω·m',
    coordinate_kind: 'local_linear',
  },
  links: { detail: '/api/cases/resistivity', publish_status: null },
}

const GAS_PRESET_CARD: CaseSummary = {
  case_id: 'gas',
  title: '煤层瓦斯',
  status: 'active',
  source_kind: 'builtin_preset',
  workspace_kind: 'builtin_preset',
  capabilities: { data_summary: true, experiments: true, official_result: true, native_volume: true },
  official_result: { result_id: 'gas-official-1', url: '/results/gas-official-1', materialized: true },
  provenance_summary: {
    badge: '散点预置 · 官方基线成果',
    data_form: '标准化散点 · 58 个合格样品',
    fields: ['X', 'Y', 'Z', 'CH4_content'],
    value_unit: 'ml/g',
    coordinate_kind: 'local_linear',
  },
  links: { detail: '/api/cases/gas', publish_status: null },
}

const GAS_DESCRIPTOR_CARD: CaseSummary = {
  case_id: 'gas',
  title: '煤层瓦斯',
  status: 'initialization_required',
  source_kind: 'builtin_preset',
  workspace_kind: 'builtin_preset',
  capabilities: { data_summary: false, experiments: false, official_result: false, native_volume: false },
  official_result: null,
  provenance_summary: {
    badge: '散点预置 · 官方基线成果',
    data_form: '标准化散点 · 58 个合格样品',
    fields: ['X', 'Y', 'Z', 'CH4_content'],
    value_unit: 'ml/g',
    coordinate_kind: 'local_linear',
    coordinate_unit: 'm',
  },
  links: { detail: null, publish_status: null },
}

const CAPABILITY: RenderCapability = {
  source_kind: 'candidate_result',
  source_id: 'x',
  supported: true,
  reason_code: null,
  reason: null,
  dimension: '3d',
  grid_kind: 'regular',
  property_name: 'RHO',
  units: 'Ω·m',
  geolocation_status: 'display_anchor_only',
  display_transform: null,
  render_profile: null,
}

const ASSET: RenderAssetRecord = {
  id: `nc-${'a'.repeat(32)}`,
  source_kind: 'candidate_result',
  source_id: 'x',
  renderer: 'supermap_voxelgrid_netcdf',
  status: 'ready',
  grid_sha256: 'g'.repeat(64),
  netcdf_sha256: 'n'.repeat(64),
  manifest_url: '/api/render-assets/x/manifest',
  netcdf_url: '/api/render-assets/x/volume.nc',
  error: null,
}

function workspaceOf(c: CaseSummary): CaseWorkspaceSummary {
  return {
    ...c,
    workspace_kind: (c.workspace_kind ?? 'user_upload') as CaseWorkspaceSummary['workspace_kind'],
    capabilities: (c.capabilities ?? {
      data_summary: true,
      experiments: true,
      official_result: true,
      native_volume: true,
    }) as CaseWorkspaceSummary['capabilities'],
    primary_dataset: null,
    official_result: c.official_result ?? null,
    provenance_summary: c.provenance_summary ?? {},
    links: c.links,
  } as CaseWorkspaceSummary
}

async function mountHome(cases: CaseSummary[]) {
  vi.mocked(client.fetchCases).mockResolvedValue({ cases })
  vi.mocked(client.fetchCaseWorkspace).mockImplementation(async (caseId) => {
    const found = cases.find((c) => c.case_id === caseId)
    if (!found) throw new Error('CASE_NOT_FOUND')
    return workspaceOf(found)
  })
  vi.mocked(client.fetchAnalysisSummary).mockRejectedValue(new Error('DATASET_NOT_VALIDATED'))
  vi.mocked(client.fetchResultRenderCapability).mockResolvedValue(CAPABILITY)
  vi.mocked(client.fetchResultRenderAsset).mockResolvedValue(ASSET)
  vi.mocked(client.createResultRenderAsset).mockResolvedValue(ASSET)
  vi.mocked(client.trashCase).mockResolvedValue({})

  const stub = { template: '<div />' }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: HomeView },
      { path: '/trash', name: 'trash', component: stub },
      { path: '/cases/new', name: 'case-create', component: stub },
      { path: '/cases/:caseId', name: 'case-workspace', component: stub },
      { path: '/cases/:caseId/experiments/new', name: 'experiment-create', component: stub },
      { path: '/results/:resultId', name: 'result-workbench', component: stub },
      { path: '/:pathMatch(.*)*', component: stub },
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

describe('HomeView 指挥舱骨架', () => {
  it('案例轨、三维主舞台、关键发现与证据带同屏出现', async () => {
    const { wrapper } = await mountHome([RESISTIVITY_PRESET_CARD])
    expect(wrapper.find('[data-test="case-rail"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="command-center-scene"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="home-findings"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="home-evidence-dock"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="create-case-card"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="download-demo-data"]').exists()).toBe(true)
  })

  it('案例列表加载失败显示统一错误状态', async () => {
    vi.mocked(client.fetchCases).mockRejectedValue(new Error('network down'))
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', name: 'home', component: HomeView }],
    })
    await router.push('/')
    const wrapper = mount(HomeView, { global: { plugins: [router, ElementPlus] } })
    await flushPromises()
    expect(wrapper.text()).toContain('案例列表加载失败')
    expect(wrapper.get('[role="status"]').attributes('data-state')).toBe('error')
  })
})

describe('HomeView 用户项目入口', () => {
  it('有 featured_result：主入口直达成果页，新建实验为次操作', async () => {
    const { wrapper, router } = await mountHome([BENCH_CASE])

    const primary = wrapper.find('[data-test="open-featured-result"]')
    expect(primary.exists()).toBe(true)
    expect(primary.text()).toContain('查看体渲染成果')
    const secondary = wrapper.find('[data-test="new-experiment"]')
    expect(secondary.exists()).toBe(true)
    expect(secondary.text()).toContain('新建实验')
    expect(wrapper.text()).not.toContain('进入调参实验室')

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

  it('无 featured_result：继续建模进入统一工作台', async () => {
    const { wrapper, router } = await mountHome([PLAIN_UPLOAD_CASE])
    expect(wrapper.find('[data-test="open-featured-result"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="new-experiment"]').exists()).toBe(false)

    const primary = wrapper.find('[data-test="enter-case-workspace"]')
    expect(primary.exists()).toBe(true)
    await primary.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/cases/case-plain')
  })

  it('轨条目点击只切换选中案例，不离开首页', async () => {
    const { wrapper, router } = await mountHome([BENCH_CASE])
    await wrapper.find('[data-test="case-rail-item"][data-case-id="case-bench-32"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/')
    expect(wrapper.get('[data-test="command-center-scene"]').text()).toContain('体积基准 32³')
  })
})

describe('HomeView 官方案例入口', () => {
  it('预置卡徽标/单位来自 DTO；主命令进入案例分析，次命令直达官方成果', async () => {
    const { wrapper, router } = await mountHome([PRESET_CASE, RESISTIVITY_PRESET_CARD])

    expect(wrapper.text()).not.toContain('导入微震 DAT')
    expect(wrapper.text()).toContain('CSV 预置 · 官方普通克里金成果')

    const buttons = wrapper.findAll('[data-test="enter-case-workspace"]')
    expect(buttons.length).toBe(2)
    await buttons[0].trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe(`/cases/${PRESET_CASE.case_id}`)

    await router.push('/')
    const official = wrapper.find('[data-test="open-official-result"]')
    expect(official.exists()).toBe(true)
    expect(official.text()).toContain('查看官方成果')
    await official.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/results/r-1')
  })

  it('电阻率预置卡：统一文案与字段行逐字来自 DTO，无 legacy/S3M/DAT 语样与绝对路径', async () => {
    const { wrapper } = await mountHome([RESISTIVITY_PRESET_CARD])
    const text = wrapper.text()
    expect(text).toContain('散点预置 · 官方普通克里金成果')
    expect(text).toContain('标准化散点 · 17,549 个节点')
    expect(text).toContain('Ω·m')
    expect(text).toContain('X/Y/Z/RHO')
    expect(text).not.toContain('S3M')
    expect(text).not.toContain('DAT')
    expect(text).not.toContain('v0.3.1')
    expect(text).not.toContain('调参实验室')
    expect(text).not.toMatch(/[A-Za-z]:\\/)
    expect(text).not.toContain('/home/')
    expect(text).not.toContain('/Users/')
  })

  it('瓦斯预置卡：徽标、字段行、ml/g 来自 DTO，无暂缓/legacy 文案', async () => {
    const { wrapper, router } = await mountHome([GAS_PRESET_CARD])
    const text = wrapper.text()
    expect(text).toContain('散点预置 · 官方基线成果')
    expect(text).toContain('标准化散点 · 58 个合格样品')
    expect(text).toContain('ml/g')
    expect(text).toContain('X/Y/Z/CH4_content')
    expect(text).not.toContain('暂缓')
    expect(text).not.toContain('parked')
    expect(text).not.toContain('DAT')
    expect(text).not.toContain('legacy')
    expect(text).not.toContain('Legacy')
    expect(text).not.toMatch(/[A-Za-z]:\\/)

    await wrapper.find('[data-test="enter-case-workspace"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/cases/gas')
  })

  it('未 seed 瓦斯描述卡：无官方成果直达，仅保留进入案例分析', async () => {
    const { wrapper } = await mountHome([GAS_DESCRIPTOR_CARD])
    expect(wrapper.text()).toContain('标准化散点 · 58 个合格样品')
    expect(wrapper.find('[data-test="open-official-result"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="enter-case-workspace"]').exists()).toBe(true)
  })

  it('按钮均有可访问名称', async () => {
    const { wrapper } = await mountHome([RESISTIVITY_PRESET_CARD])
    const buttons = wrapper.findAll('button')
    expect(buttons.length).toBeGreaterThan(0)
    for (const btn of buttons) {
      const name = btn.text().trim() || btn.attributes('aria-label') || btn.attributes('title')
      expect(name).toBeTruthy()
    }
  })
})

describe('HomeView 回收站', () => {
  it('用户项目可移入回收站并刷新列表', async () => {
    const { wrapper } = await mountHome([PLAIN_UPLOAD_CASE])
    const dropdown = wrapper.get('[data-test="trash-case-btn"]')
    // el-dropdown command 事件（等效点击「移入回收站」菜单项）
    await dropdown.trigger('command')
    // 直接触发组件命令回调
    const dropdownVm = wrapper.findComponent({ name: 'ElDropdown' })
    dropdownVm.vm.$emit('command')
    await flushPromises()
    expect(vi.mocked(client.trashCase)).toHaveBeenCalledWith('case-plain')
    expect(vi.mocked(client.fetchCases).mock.calls.length).toBeGreaterThanOrEqual(2)
  })
})

describe('HomeView 视觉系统', () => {
  it('首页携带窄屏响应式规则（像素级门在 e2e）', () => {
    expect(homeViewSource).toContain('@media (max-width: 480px)')
  })

  it('首页源码无 case_id 硬编码分支与「暂缓」残留', () => {
    expect(homeViewSource).not.toContain('暂缓')
    expect(homeViewSource).not.toContain("case_id === 'gas'")
  })
})
