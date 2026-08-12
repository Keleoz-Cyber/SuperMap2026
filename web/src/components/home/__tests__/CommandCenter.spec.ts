import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import * as client from '../../../api/client'
import type {
  AnalysisSummaryResponse,
  CaseSummary,
  CaseWorkspaceSummary,
  RenderAssetRecord,
  RenderCapability,
} from '../../../api/types'
import HomeView from '../../../views/HomeView.vue'
import AppShell from '../../shell/AppShell.vue'

// v0.9.0 Task 5：首页综合指挥舱行为合同。
// 案例切换必须整体联动（变量/单位/辅助色/结论/成果身份）；官方案例绝不
// 出现上传控件；用户案例按权威 data_preparation 状态给出唯一主动作。

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
    fetchRenderAssetSliceAnalysis: vi.fn(),
    createRenderAssetSliceExport: vi.fn(),
    trashCase: vi.fn(),
  }
})

const RESISTIVITY_CASE: CaseSummary = {
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

const GAS_CASE: CaseSummary = {
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

const USER_PREP_CASE: CaseSummary = {
  case_id: 'case-user-1',
  title: '我的勘探项目',
  status: 'active',
  source_kind: 'upload',
  workspace_kind: 'user_upload',
  case_type: 'generic',
  created_at: '2026-08-01T00:00:00+00:00',
  featured_result: null,
  capabilities: { data_summary: true, experiments: false, official_result: false, native_volume: false },
  provenance_summary: { value_name: 'density', value_unit: 'g/cm³', coordinate_kind: 'local_linear' },
  links: { detail: '/api/cases/case-user-1', publish_status: null },
}

function workspaceOf(c: CaseSummary, overrides: Partial<CaseWorkspaceSummary> = {}): CaseWorkspaceSummary {
  return {
    ...c,
    workspace_kind: (c.workspace_kind ?? 'builtin_preset') as CaseWorkspaceSummary['workspace_kind'],
    capabilities: (c.capabilities ?? {
      data_summary: true,
      experiments: true,
      official_result: true,
      native_volume: true,
    }) as CaseWorkspaceSummary['capabilities'],
    primary_dataset: {
      id: `ds-${c.case_id}`,
      case_id: c.case_id,
      version: 1,
      status: 'validated',
      profile: {},
      created_at: '2026-08-01T00:00:00+00:00',
    },
    official_result: c.official_result ?? null,
    provenance_summary: c.provenance_summary ?? {},
    links: c.links,
    ...overrides,
  } as CaseWorkspaceSummary
}

function summaryOf(datasetId: string, variable: string, unit: string, sha: string): AnalysisSummaryResponse {
  return {
    dataset_id: datasetId,
    case_id: 'c',
    analysis_profile: unit === 'Ω·m' ? 'resistivity' : unit === 'ml/g' ? 'gas_content' : 'generic_3d',
    profile_version: 1,
    variable: { name: variable, unit },
    quality: {
      row_count: 100,
      valid_count: 96,
      invalid_count: 4,
      duplicate_coordinate_count: 0,
      bounds: { x: [0, 1], y: [0, 1], z: [0, 1] },
    },
    statistics: null,
    modules: [],
    provenance: {
      source_sha256: sha,
      dataset_version: 1,
      generated_at: '2026-08-10T00:00:00+00:00',
      calculation_version: 'analysis.v1',
    },
  }
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

async function mountHome(cases: CaseSummary[]) {
  vi.mocked(client.fetchHealth).mockResolvedValue({
    status: 'ok',
    version: '0.9.0',
    time: '2026-08-10T00:00:00+00:00',
  })
  vi.mocked(client.fetchCases).mockResolvedValue({ cases })
  vi.mocked(client.fetchCaseWorkspace).mockImplementation(async (caseId) => {
    const found = cases.find((c) => c.case_id === caseId)
    if (!found) throw new Error('CASE_NOT_FOUND')
    return workspaceOf(found)
  })
  vi.mocked(client.fetchAnalysisSummary).mockImplementation(async (datasetId) => {
    if (datasetId === 'ds-resistivity') return summaryOf(datasetId, 'RHO', 'Ω·m', 'rho-sha')
    if (datasetId === 'ds-gas') return summaryOf(datasetId, 'CH4_content', 'ml/g', 'gas-sha')
    return summaryOf(datasetId, 'value', 'unit', 'generic-sha')
  })
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
  const wrapper = mount(AppShell, {
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

describe('CommandCenter 指挥舱', () => {
  it('first screen carries rail, scene, findings, evidence dock and global create entry', async () => {
    const { wrapper } = await mountHome([RESISTIVITY_CASE, GAS_CASE])
    expect(wrapper.get('[data-test="case-rail"]')).toBeTruthy()
    expect(wrapper.get('[data-test="command-center-scene"]')).toBeTruthy()
    expect(wrapper.get('[data-test="home-findings"]')).toBeTruthy()
    expect(wrapper.get('[data-test="home-evidence-dock"]')).toBeTruthy()
    expect(wrapper.get('[data-test="global-create-case"]')).toBeTruthy()
  })

  it('switching cases updates variable, unit, accent, findings and result identity together', async () => {
    const { wrapper } = await mountHome([RESISTIVITY_CASE, GAS_CASE])

    // 默认选中首个案例（电阻率）
    const scene = wrapper.get('[data-test="command-center-scene"]')
    expect(scene.text()).toContain('地下电阻率')
    expect(scene.text()).toContain('Ω·m')
    expect(scene.text()).toContain('局部线性米制坐标')
    expect(wrapper.get('[data-test="command-center"]').attributes('data-case-accent')).toBe('gold')
    expect(vi.mocked(client.fetchResultRenderCapability)).toHaveBeenCalledWith('rho-official-1')
    const findings = wrapper.get('[data-test="home-findings"]')
    expect(findings.text()).toContain('有效数据 96/100')

    // 切到瓦斯：全部联动更新
    await wrapper.get('[data-test="case-rail-item"][data-case-id="gas"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-test="command-center"]').attributes('data-case-accent')).toBe('jade')
    const sceneAfter = wrapper.get('[data-test="command-center-scene"]')
    expect(sceneAfter.text()).toContain('煤层瓦斯')
    expect(sceneAfter.text()).toContain('ml/g')
    expect(sceneAfter.text()).toContain('局部线性米制坐标')
    expect(sceneAfter.text()).not.toContain('Ω·m')
    expect(vi.mocked(client.fetchResultRenderCapability)).toHaveBeenCalledWith('gas-official-1')
    const evidence = wrapper.get('[data-test="home-evidence-dock"]')
    expect(evidence.text()).toContain('gas-sha'.slice(0, 8))
  })

  it('official cases never render upload controls', async () => {
    const { wrapper } = await mountHome([RESISTIVITY_CASE])
    const scene = wrapper.get('[data-test="command-center-scene"]')
    expect(scene.text()).not.toContain('上传')
    expect(wrapper.find('[data-test="dataset-upload"]').exists()).toBe(false)
    // 官方卡主命令：进入案例分析（统一工作台）
    const primary = wrapper.get('[data-test="command-primary-action"]')
    expect(primary.text()).toContain('进入案例分析')
  })

  it('user case with unfinished preparation shows 继续数据准备 as the only primary action', async () => {
    const { wrapper } = await mountHome([RESISTIVITY_CASE, USER_PREP_CASE])
    vi.mocked(client.fetchCaseWorkspace).mockResolvedValue(
      workspaceOf(USER_PREP_CASE, {
        primary_dataset: null,
        data_preparation: {
          state: 'needs_quality_review',
          dataset_id: 'ds-user-1',
          latest_validated_dataset_id: null,
          next_action: {
            step: 'quality_review',
            label: '继续质量检查',
            url: '/cases/case-user-1/datasets/ds-user-1/prepare',
          },
          error: null,
        },
      } as Partial<CaseWorkspaceSummary>),
    )
    await wrapper.get('[data-test="case-rail-item"][data-case-id="case-user-1"]').trigger('click')
    await flushPromises()

    const primaries = wrapper.findAll('[data-primary-action="true"]')
    expect(primaries).toHaveLength(1)
    expect(primaries[0].text()).toContain('继续数据准备')
    // 无成果：三维区为解释性空态，不渲染假场景
    expect(wrapper.get('[data-test="command-center-scene"]').text()).toContain('暂无成果')
  })
})
