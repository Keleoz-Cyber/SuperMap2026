import { describe, expect, it, vi } from 'vitest'
import router from '../../router'
import { fetchCaseWorkspace } from '../../api/client'

// v0.7.0 Task 5：统一工作台路由与客户端契约。

describe('case workspace router', () => {
  it('resolves /cases/:caseId as case-workspace', () => {
    expect(router.resolve('/cases/resistivity').name).toBe('case-workspace')
    expect(router.resolve('/cases/builtin-microseismic-vx-1911').name).toBe('case-workspace')
  })

  it('redirects the legacy /case/resistivity alias to the workspace', async () => {
    await router.push('/case/resistivity')
    expect(router.currentRoute.value.path).toBe('/cases/resistivity')
    expect(router.currentRoute.value.name).toBe('case-workspace')
  })
})

describe('fetchCaseWorkspace', () => {
  it('requests the workspace endpoint and returns the typed DTO', async () => {
    const payload = {
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
      primary_dataset: null,
      official_result: { result_id: 'r1', url: '/results/r1', materialized: true },
      provenance_summary: { value_unit: 'km/s' },
      links: { detail: '/api/cases/x', publish_status: null },
    }
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    const body = await fetchCaseWorkspace(payload.case_id)
    expect(spy).toHaveBeenCalledWith(
      expect.stringContaining(`/cases/${payload.case_id}/workspace`),
      expect.anything(),
    )
    expect(body.workspace_kind).toBe('builtin_preset')
    expect(body.capabilities.official_result).toBe(true)
    expect(body.official_result?.materialized).toBe(true)
    spy.mockRestore()
  })
})
