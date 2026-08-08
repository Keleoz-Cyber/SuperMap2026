import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import * as client from '../../api/client'
import type { CaseWorkspaceSummary, DatasetVersionRecord } from '../../api/types'
import CaseWorkspaceView from '../CaseWorkspaceView.vue'
import workspaceViewSource from '../CaseWorkspaceView.vue?raw'

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return { ...actual, fetchCaseWorkspace: vi.fn(), fetchProfessionalDiagnostics: vi.fn() }
})

const PRESET_ID = 'builtin-microseismic-vx-1911'

function workspaceOf(kind: CaseWorkspaceSummary['workspace_kind']): CaseWorkspaceSummary {
  const base: CaseWorkspaceSummary = {
    case_id: kind === 'builtin_preset' ? PRESET_ID : kind === 'builtin_legacy' ? 'resistivity' : 'up-1',
    title: kind === 'builtin_preset' ? '微震速度' : kind === 'builtin_legacy' ? '地下电阻率' : '上传案例',
    status: 'active',
    workspace_kind: kind,
    capabilities: {
      data_summary: kind !== 'builtin_legacy',
      experiments: kind !== 'builtin_legacy',
      official_result: kind === 'builtin_preset',
      native_volume: kind !== 'user_upload',
    },
    primary_dataset:
      kind === 'builtin_legacy'
        ? null
        : ({
            id: 'ds-1',
            case_id: 'x',
            version: 1,
            status: 'validated',
            created_at: '2026-08-05T00:00:00+00:00',
            profile: { mapping: { value_name: 'Vx', value_unit: 'km/s' }, row_count: 1911 },
          } as unknown as CaseWorkspaceSummary['primary_dataset']),
    official_result:
      kind === 'builtin_preset'
        ? { result_id: 'r-1', url: '/results/r-1', materialized: true }
        : null,
    provenance_summary: { value_unit: 'km/s', coordinate_kind: 'local_linear' },
    links: { detail: null, publish_status: null },
  }
  return base
}

const RHO_STUB = { name: 'RhoCaseView', template: '<div data-test="rho-embedded" />', props: ['embedded'] }

async function mountWorkspace(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/cases/:caseId', name: 'case-workspace', component: CaseWorkspaceView },
      { path: '/', name: 'home', component: { template: '<div />' } },
      { path: '/results/:resultId', name: 'result-workbench', component: { template: '<div />' } },
      {
        path: '/cases/:caseId/experiments/new',
        name: 'experiment-create',
        component: { template: '<div />' },
      },
      {
        path: '/datasets/:datasetId/professional-diagnosis',
        name: 'professional-diagnosis',
        component: { template: '<div />' },
      },
      {
        path: '/datasets/:datasetId/candidate-comparison',
        name: 'candidate-comparison',
        component: { template: '<div />' },
      },
    ],
  })
  router.push(path)
  await router.isReady()
  const wrapper = mount(CaseWorkspaceView, {
    global: {
      plugins: [router, ElementPlus],
      stubs: { RhoCaseView: RHO_STUB },
    },
  })
  await flushPromises()
  return { wrapper, router }
}

describe('CaseWorkspaceView', () => {
  it.each(['builtin_legacy', 'builtin_preset', 'user_upload'] as const)(
    '%s renders the shared header and sections',
    async (kind) => {
      vi.mocked(client.fetchCaseWorkspace).mockResolvedValue(workspaceOf(kind))
      const { wrapper } = await mountWorkspace(`/cases/${kind === 'builtin_preset' ? PRESET_ID : kind}`)
      expect(wrapper.find('[data-test="case-workspace-header"]').exists()).toBe(true)
      expect(wrapper.find('[data-test="workspace-overview"]').exists()).toBe(true)
      expect(wrapper.find('[data-test="workspace-data"]').exists()).toBe(true)
      expect(wrapper.find('[data-test="workspace-experiments"]').exists()).toBe(true)
      expect(wrapper.find('[data-test="workspace-results"]').exists()).toBe(true)
    },
  )

  it('new-experiment appears only in experiments section, never overview or data', async () => {
    vi.mocked(client.fetchCaseWorkspace).mockResolvedValue(workspaceOf('user_upload'))
    const { wrapper } = await mountWorkspace('/cases/up-1')
    expect(wrapper.findAll('[data-test="new-experiment"]').length).toBe(1)
    expect(wrapper.find('[data-test="workspace-overview"] [data-test="new-experiment"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="data-preparation-panel"] [data-test="new-experiment"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="workspace-experiments"] [data-test="new-experiment"]').exists()).toBe(true)
  })

  it('preset: official-result in overview, new-experiment in experiments section', async () => {
    vi.mocked(client.fetchCaseWorkspace).mockResolvedValue(workspaceOf('builtin_preset'))
    const { wrapper, router } = await mountWorkspace(`/cases/${PRESET_ID}`)
    await wrapper.find('[data-test="open-official-result"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/results/r-1')
    await router.push(`/cases/${PRESET_ID}`)
    await flushPromises()
    await wrapper.find('[data-test="new-experiment"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe(`/cases/${PRESET_ID}/experiments/new`)
    expect(router.currentRoute.value.query.dataset).toBe('ds-1')
  })

  it('legacy: no new-experiment command (experiments capability false)', async () => {
    vi.mocked(client.fetchCaseWorkspace).mockResolvedValue(workspaceOf('builtin_legacy'))
    const { wrapper } = await mountWorkspace('/cases/resistivity')
    expect(wrapper.find('[data-test="new-experiment"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="workspace-rho-block"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="rho-embedded"]').exists()).toBe(true)
  })

  it('PRESET_NOT_INITIALIZED renders typed error with home action, never upload', async () => {
    const { ApiError } = await import('../../api/client')
    vi.mocked(client.fetchCaseWorkspace).mockRejectedValue(
      new ApiError('PRESET_NOT_INITIALIZED', '预置案例尚未初始化', 409),
    )
    const { wrapper, router } = await mountWorkspace(`/cases/${PRESET_ID}`)
    expect(wrapper.find('[data-test="workspace-not-initialized"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="legacy-import"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('上传')
    await wrapper.find('[data-test="back-home"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/')
  })

  it('快速 A->B->A 连切：stale 响应不得覆盖当前案例状态', async () => {
    const wsA = workspaceOf('builtin_legacy')
    wsA.official_result = { result_id: 'a-r1', url: '/results/a-r1', materialized: true }
    wsA.capabilities = { data_summary: true, experiments: true, official_result: true, native_volume: true }
    const wsB = workspaceOf('builtin_preset')
    const pending = new Map<string, { resolve: (v: CaseWorkspaceSummary) => void; reject: (e: unknown) => void }>()
    vi.mocked(client.fetchCaseWorkspace).mockImplementation((id: string) => {
      if (id === 'resistivity' && pending.size === 0 && !pending.has('a2') && !pending.has('b')) {
        return Promise.resolve(wsA)
      }
      return new Promise<CaseWorkspaceSummary>((resolve, reject) => {
        pending.set(id === 'resistivity' ? 'a2' : 'b', { resolve, reject })
      })
    })

    const { wrapper, router } = await mountWorkspace('/cases/resistivity')
    expect(wrapper.find('[data-test="case-workspace-header"]').text()).toContain('地下电阻率')

    await router.push(`/cases/${PRESET_ID}`)
    await router.push('/cases/resistivity')
    expect(pending.has('b')).toBe(true)
    expect(pending.has('a2')).toBe(true)

    pending.get('a2')!.resolve(wsA)
    await flushPromises()
    expect(wrapper.find('[data-test="case-workspace-header"]').text()).toContain('地下电阻率')

    pending.get('b')!.resolve(wsB)
    await flushPromises()
    const header = wrapper.find('[data-test="case-workspace-header"]')
    expect(header.text()).toContain('地下电阻率')
    expect(header.text()).not.toContain('微震速度')
    expect(wrapper.find('[data-test="workspace-not-initialized"]').exists()).toBe(false)

    await wrapper.find('[data-test="open-official-result"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/results/a-r1')
  })

  it('stale rejection 不显示错误页，stale finally 不提前结束 loading', async () => {
    const wsA = workspaceOf('builtin_legacy')
    const pending = new Map<string, { resolve: (v: CaseWorkspaceSummary) => void; reject: (e: unknown) => void }>()
    let firstA = true
    vi.mocked(client.fetchCaseWorkspace).mockImplementation((id: string) => {
      if (id === 'resistivity' && firstA) {
        firstA = false
        return Promise.resolve(wsA)
      }
      return new Promise<CaseWorkspaceSummary>((resolve, reject) => {
        pending.set(id === 'resistivity' ? 'a2' : 'b', { resolve, reject })
      })
    })

    const { wrapper, router } = await mountWorkspace('/cases/resistivity')
    await router.push(`/cases/${PRESET_ID}`)
    expect(pending.has('b')).toBe(true)
    await router.push('/cases/resistivity')
    expect(pending.has('a2')).toBe(true)

    pending.get('b')!.reject(new Error('network down'))
    await flushPromises()
    expect(wrapper.find('[data-test="workspace-load-error"]').exists()).toBe(false)

    pending.get('a2')!.resolve(wsA)
    await flushPromises()
    expect(wrapper.find('[data-test="case-workspace-header"]').text()).toContain('地下电阻率')
    expect(wrapper.find('[data-test="workspace-load-error"]').exists()).toBe(false)
  })

  it('路由参数变化时重新加载目标案例（不得显示上一个案例的 stale 内容）', async () => {
    vi.mocked(client.fetchCaseWorkspace).mockImplementation(async (id: string) =>
      id === 'resistivity' ? workspaceOf('builtin_legacy') : workspaceOf('builtin_preset'),
    )
    const { wrapper, router } = await mountWorkspace('/cases/resistivity')
    expect(wrapper.find('[data-test="case-workspace-header"]').text()).toContain('地下电阻率')

    await router.push(`/cases/${PRESET_ID}`)
    await flushPromises()
    expect(client.fetchCaseWorkspace).toHaveBeenCalledWith(PRESET_ID)
    expect(wrapper.find('[data-test="case-workspace-header"]').text()).toContain('微震速度')
    expect(wrapper.find('[data-test="case-workspace-header"]').text()).not.toContain('地下电阻率')
  })

  it('user_upload with featured result: 查看成果 primary + results section shows 主打成果', async () => {
    const ws = workspaceOf('user_upload')
    ws.capabilities = {
      data_summary: true,
      experiments: true,
      official_result: true,
      native_volume: true,
    }
    ws.official_result = { result_id: 'up-r1', url: '/results/up-r1', materialized: true }
    vi.mocked(client.fetchCaseWorkspace).mockResolvedValue(ws)
    const { wrapper, router } = await mountWorkspace('/cases/up-1')

    const primary = wrapper.find('[data-test="open-official-result"]')
    expect(primary.exists()).toBe(true)
    expect(primary.text()).toContain('查看成果')
    expect(primary.text()).not.toContain('官方')
    await primary.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/results/up-r1')

    const results = wrapper.find('[data-test="workspace-results"]')
    expect(results.text()).toContain('主打成果')
    expect(results.text()).toContain('已物化')
    expect(wrapper.find('[data-test="new-experiment"]').exists()).toBe(true)
  })

  it('user_upload without result: results section shows 暂无成果 and offers 新建实验', async () => {
    const ws = workspaceOf('user_upload')
    vi.mocked(client.fetchCaseWorkspace).mockResolvedValue(ws)
    const { wrapper, router } = await mountWorkspace('/cases/up-1')

    expect(wrapper.find('[data-test="open-official-result"]').exists()).toBe(false)
    const results = wrapper.find('[data-test="workspace-results"]')
    expect(results.text()).toContain('暂无成果')
    expect(wrapper.text()).not.toContain('调参实验室')
    await wrapper.find('[data-test="new-experiment"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/cases/up-1/experiments/new')
    expect(router.currentRoute.value.query.dataset).toBe('ds-1')
  })

  it('validated_datasets: diagnosis detail navigates with diagnosis ID, reanalyze omits it', async () => {
    const ws = workspaceOf('user_upload')
    const validated: DatasetVersionRecord[] = [
      {
        id: 'ds-v1',
        case_id: 'up-1',
        version: 1,
        status: 'validated',
        profile: { dimension: '3d' },
        created_at: '2026-08-05T00:00:00+00:00',
      },
    ]
    ws.validated_datasets = validated
    vi.mocked(client.fetchCaseWorkspace).mockResolvedValue(ws)
    vi.mocked(client.fetchProfessionalDiagnostics).mockResolvedValue({
      dataset_id: 'ds-v1',
      diagnostics: [
        {
          diagnosis: { id: 'diag1', status: 'succeeded' },
          job: null,
          url: '/datasets/ds-v1/professional-diagnosis?diagnosis=diag1',
          latest_confirmation: null,
        },
      ],
    })
    const { wrapper, router } = await mountWorkspace('/cases/up-1')

    // No new-experiment button in dataset rows
    expect(wrapper.find('[data-test="validated-dataset-ds-v1"] [data-test="new-experiment"]').exists()).toBe(false)

    // Diagnosis detail navigates with diagnosis ID (from item.url)
    await wrapper.find('[data-test="validated-dataset-ds-v1"] [data-test="diagnosis-detail-btn"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('professional-diagnosis')
    expect(router.currentRoute.value.params.datasetId).toBe('ds-v1')
    expect(router.currentRoute.value.query.diagnosis).toBe('diag1')

    // Reanalyze navigates WITHOUT diagnosis ID
    await router.push('/cases/up-1')
    await flushPromises()
    await wrapper.find('[data-test="validated-dataset-ds-v1"] [data-test="reanalyze-btn"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('professional-diagnosis')
    expect(router.currentRoute.value.params.datasetId).toBe('ds-v1')
    expect(router.currentRoute.value.query.diagnosis).toBeUndefined()
    expect(router.currentRoute.value.query.case).toBe('up-1')
    wrapper.unmount()
  })

  it('diagnosis list failure renders 分析状态暂不可用', async () => {
    const ws = workspaceOf('user_upload')
    ws.validated_datasets = [
      {
        id: 'ds-v1',
        case_id: 'up-1',
        version: 1,
        status: 'validated',
        profile: { dimension: '3d' },
        created_at: '2026-08-05T00:00:00+00:00',
      },
    ]
    vi.mocked(client.fetchCaseWorkspace).mockResolvedValue(ws)
    vi.mocked(client.fetchProfessionalDiagnostics).mockRejectedValue(new Error('network'))
    const { wrapper } = await mountWorkspace('/cases/up-1')

    expect(wrapper.find('[data-test="diagnosis-status-ds-v1"]').text()).toContain('分析状态暂不可用')
    expect(wrapper.text()).not.toContain('未分析')
    wrapper.unmount()
  })

  it('recent_experiments and recent_results render in their sections', async () => {
    const ws = workspaceOf('user_upload')
    ws.recent_experiments = [
      {
        id: 'exp-1',
        name: '实验一',
        algorithm: 'idw',
        dataset_version_id: 'ds-1',
        latest_run_status: 'succeeded',
        succeeded_candidate_count: 2,
        created_at: '2026-08-05T00:00:00+00:00',
        url: '/experiments/exp-1',
      },
    ]
    ws.recent_results = [
      {
        result_id: 'r-1',
        experiment_id: 'exp-1',
        algorithm: 'idw',
        materialized: true,
        featured: false,
        created_at: '2026-08-05T00:00:00+00:00',
        url: '/results/r-1',
      },
    ]
    vi.mocked(client.fetchCaseWorkspace).mockResolvedValue(ws)
    const { wrapper } = await mountWorkspace('/cases/up-1')

    expect(wrapper.find('[data-test="recent-experiment-exp-1"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="recent-experiments"]').text()).toContain('IDW')
    expect(wrapper.find('[data-test="recent-result-r-1"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="recent-results"]').text()).toContain('已物化')
    wrapper.unmount()
  })

  it('model-comparison link in experiments section navigates to comparison', async () => {
    const ws = workspaceOf('user_upload')
    vi.mocked(client.fetchCaseWorkspace).mockResolvedValue(ws)
    const { wrapper, router } = await mountWorkspace('/cases/up-1')

    const cmp = wrapper.find('[data-test="model-comparison"]')
    expect(cmp.exists()).toBe(true)
    await cmp.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/datasets/ds-1/candidate-comparison')
    wrapper.unmount()
  })
})

// ---------------------------------------------------------------------------
// v0.8.0：电阻率迁移为 builtin_preset 散点预置后的统一工作台语义。
// 文案全部来自后端 DTO（provenance_summary / data_preparation），前端不按
// case_id 硬编码微震/电阻率分支；旧 legacy/S3M/DAT 语样不得出现在可见操作中。
// ---------------------------------------------------------------------------

const RESISTIVITY_PRESET_WS: CaseWorkspaceSummary = {
  case_id: 'resistivity',
  title: '地下电阻率',
  status: 'active',
  workspace_kind: 'builtin_preset',
  capabilities: {
    data_summary: true,
    experiments: true,
    official_result: true,
    native_volume: true,
  },
  primary_dataset: {
    id: 'ds-rho-1',
    case_id: 'resistivity',
    version: 1,
    status: 'validated',
    created_at: '2026-08-08T00:00:00+00:00',
    profile: {
      mapping: {
        dimension: '3d',
        x: 'X',
        y: 'Y',
        z: 'Z',
        value: 'RHO',
        value_name: 'RHO',
        value_unit: 'RHO 单位待来源确认',
        coordinate_kind: 'local_linear',
      },
      row_count: 17549,
      valid_row_count: 17549,
    },
  } as unknown as CaseWorkspaceSummary['primary_dataset'],
  official_result: { result_id: 'rho-official-1', url: '/results/rho-official-1', materialized: true },
  provenance_summary: {
    badge: '散点预置 · 官方普通克里金成果',
    data_form: '标准化散点 · 17,549 个节点',
    value_unit: 'RHO 单位待来源确认',
    coordinate_kind: 'local_linear',
  },
  // v0.8.0：预置工作台 DTO 携带 data_preparation（state=validated 摘要）
  data_preparation: {
    state: 'validated',
    dataset_id: null,
    latest_validated_dataset_id: 'ds-rho-1',
    next_action: {
      step: 'experiment',
      label: '新建实验',
      url: '/#/cases/resistivity/experiments/new',
    },
    error: null,
  },
  validated_datasets: [],
  abandoned_datasets: [],
  recent_experiments: [],
  recent_results: [],
  links: { detail: '/api/cases/resistivity', publish_status: null },
}

describe('CaseWorkspaceView 电阻率散点预置（v0.8.0）', () => {
  it('电阻率 builtin_preset 工作台：统一文案与操作，无 legacy/S3M/DAT 可见语样', async () => {
    vi.mocked(client.fetchCaseWorkspace).mockResolvedValue(RESISTIVITY_PRESET_WS)
    const { wrapper, router } = await mountWorkspace('/cases/resistivity')

    // 统一预置文案（逐字来自 DTO provenance_summary / primary_dataset）
    const text = wrapper.text()
    expect(text).toContain('标准化散点 · 17,549 个节点')
    expect(text).toContain('散点预置 · 官方普通克里金成果')
    expect(text).toContain('RHO 单位待来源确认')
    expect(text).toContain('X/Y/Z -> RHO')

    // 操作一：查看官方成果直达
    await wrapper.find('[data-test="open-official-result"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/results/rho-official-1')

    // 操作二：新建实验进入统一实验创建页
    await router.push('/cases/resistivity')
    await flushPromises()
    await wrapper.find('[data-test="new-experiment"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/cases/resistivity/experiments/new')
    expect(router.currentRoute.value.query.dataset).toBe('ds-rho-1')

    // 旧 legacy/S3M/DAT 语样与旧页面嵌入块均不可见
    expect(text).not.toContain('S3M')
    expect(text).not.toContain('DAT')
    expect(text).not.toContain('legacy')
    expect(text).not.toContain('Legacy')
    expect(wrapper.find('[data-test="workspace-rho-block"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="rho-embedded"]').exists()).toBe(false)

    // 预置案例无上传恢复状态机：不渲染数据准备面板与上传入口
    expect(wrapper.find('[data-test="data-preparation-panel"]').exists()).toBe(false)
    expect(text).not.toContain('上传数据')

    // 渲染文本不得携带本机绝对路径
    expect(text).not.toMatch(/[A-Za-z]:\\/)
    expect(text).not.toContain('/home/')
    expect(text).not.toContain('/Users/')
    wrapper.unmount()
  })

  it('预置有官方成果：成果区展示官方成果链接与物化状态', async () => {
    vi.mocked(client.fetchCaseWorkspace).mockResolvedValue(RESISTIVITY_PRESET_WS)
    const { wrapper } = await mountWorkspace('/cases/resistivity')

    const results = wrapper.find('[data-test="workspace-results"]')
    expect(results.text()).toContain('官方成果')
    expect(results.text()).toContain('已物化')
    expect(wrapper.find('[data-test="open-official-result"]').text()).toContain('查看官方成果')
    wrapper.unmount()
  })

  it('预置无官方成果：收起成果直达但保留新建实验', async () => {
    const ws: CaseWorkspaceSummary = {
      ...RESISTIVITY_PRESET_WS,
      capabilities: { ...RESISTIVITY_PRESET_WS.capabilities, official_result: false },
      official_result: null,
    }
    vi.mocked(client.fetchCaseWorkspace).mockResolvedValue(ws)
    const { wrapper, router } = await mountWorkspace('/cases/resistivity')

    expect(wrapper.find('[data-test="open-official-result"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="results-empty"]').text()).toContain('暂无成果')
    await wrapper.find('[data-test="new-experiment"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/cases/resistivity/experiments/new')
    wrapper.unmount()
  })

  it('最近实验列表中 dsi_like 使用 DSI-like 产品名', async () => {
    const ws: CaseWorkspaceSummary = {
      ...RESISTIVITY_PRESET_WS,
      recent_experiments: [
        {
          id: 'exp-dsi-1',
          name: '电阻率 DSI 实验',
          algorithm: 'dsi_like',
          dataset_version_id: 'ds-rho-1',
          latest_run_status: 'succeeded',
          succeeded_candidate_count: 1,
          created_at: '2026-08-08T00:00:00+00:00',
          url: '/experiments/exp-dsi-1',
        },
      ],
    }
    vi.mocked(client.fetchCaseWorkspace).mockResolvedValue(ws)
    const { wrapper } = await mountWorkspace('/cases/resistivity')

    expect(wrapper.find('[data-test="recent-experiments"]').text()).toContain('DSI-like')
    expect(wrapper.find('[data-test="recent-experiments"]').text()).not.toContain('dsi_like')
    wrapper.unmount()
  })

  it('电阻率 PRESET_NOT_INITIALIZED：展示后端消息，不出现微震硬编码文案', async () => {
    const { ApiError } = await import('../../api/client')
    vi.mocked(client.fetchCaseWorkspace).mockRejectedValue(
      new ApiError('PRESET_NOT_INITIALIZED', '电阻率预置案例尚未初始化：需由维护者执行文档化 seed 命令', 409),
    )
    const { wrapper } = await mountWorkspace('/cases/resistivity')

    expect(wrapper.find('[data-test="workspace-not-initialized"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('电阻率预置案例尚未初始化')
    expect(wrapper.text()).not.toContain('微震')
    expect(wrapper.text()).not.toContain('上传')
    wrapper.unmount()
  })

  it('工作台按钮与状态均有可访问名称', async () => {
    vi.mocked(client.fetchCaseWorkspace).mockResolvedValue(RESISTIVITY_PRESET_WS)
    const { wrapper } = await mountWorkspace('/cases/resistivity')

    const buttons = wrapper.findAll('button')
    expect(buttons.length).toBeGreaterThan(0)
    for (const btn of buttons) {
      const name = btn.text().trim() || btn.attributes('aria-label') || btn.attributes('title')
      expect(name).toBeTruthy()
    }
    wrapper.unmount()
  })

  it('390x844 移动端：工作台携带窄屏响应式规则（像素级门在 e2e-live）', () => {
    // 单元层锁定响应式规则存在；真实 390x844 无横向溢出断言沿用
    // web/e2e 的 Playwright 模式（setViewportSize + scrollWidth ≤ 390）。
    expect(workspaceViewSource).toContain('@media (max-width: 480px)')
  })
})
