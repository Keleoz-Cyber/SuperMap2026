import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import * as client from '../../api/client'
import type { CaseWorkspaceSummary } from '../../api/types'
import CaseWorkspaceView from '../CaseWorkspaceView.vue'

// v0.7.0 Task 6：统一案例工作台壳（三种身份共用版式与命令位置）。

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return { ...actual, fetchCaseWorkspace: vi.fn() }
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

  it('preset: official-result and new-experiment commands route correctly', async () => {
    vi.mocked(client.fetchCaseWorkspace).mockResolvedValue(workspaceOf('builtin_preset'))
    const { wrapper, router } = await mountWorkspace(`/cases/${PRESET_ID}`)
    await wrapper.find('[data-test="open-official-result"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/results/r-1')
    await router.push(`/cases/${PRESET_ID}`)
    await wrapper.find('[data-test="new-experiment"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe(`/cases/${PRESET_ID}/experiments/new`)
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
    // 不恢复「进入调参实验室」语义；新建实验为显式命令
    expect(wrapper.text()).not.toContain('调参实验室')
    await wrapper.find('[data-test="new-experiment"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/cases/up-1/experiments/new')
  })
})
