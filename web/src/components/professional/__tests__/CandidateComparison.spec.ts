import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '../../../api/client'
import type { CandidateComparisonResult, CandidateRecord } from '../../../api/types'
import CandidateComparison from '../CandidateComparison.vue'

vi.mock('../../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../api/client')>()
  return {
    ...actual,
    createProfessionalComparison: vi.fn(),
  }
})

const FIRST = '11111111-1111-4111-8111-111111111111'
const SECOND_SAME_EXP = '22222222-2222-4222-8222-222222222222'
// 跨实验候选：不在 candidates 列表中，只能经成果 ID 输入进入比较
const EXTERNAL = '33333333-3333-4333-8333-333333333333'

const CANDIDATES: CandidateRecord[] = [
  {
    id: FIRST,
    fingerprint: 'fp-first',
    status: 'succeeded',
    parameters: {},
    metrics: { rmse: 1.2 },
    error: null,
  },
  {
    id: SECOND_SAME_EXP,
    fingerprint: 'fp-second',
    status: 'succeeded',
    parameters: {},
    metrics: { rmse: 1.5 },
    error: null,
  },
  {
    id: 'r-failed',
    fingerprint: 'fp-failed',
    status: 'failed',
    parameters: {},
    metrics: {},
    error: { code: 'RUN_FAILED', message: '失败' },
  },
]

const COMPATIBLE: CandidateComparisonResult = {
  first_result_id: FIRST,
  second_result_id: EXTERNAL,
  compatible: true,
  mismatches: [],
  common_valid_count: 40,
  metric_deltas: { rmse: -0.3, mae: -0.2 },
  grid_difference_available: false,
  grid_difference: null,
  comparison_fingerprint: 'ab'.repeat(32),
}

const INCOMPATIBLE: CandidateComparisonResult = {
  first_result_id: FIRST,
  second_result_id: EXTERNAL,
  compatible: false,
  mismatches: ['dataset_version_id', 'validation_fingerprint'],
  common_valid_count: null,
  metric_deltas: null,
  grid_difference_available: false,
  grid_difference: null,
  comparison_fingerprint: 'cd'.repeat(32),
}

function mountPanel(firstResultId: string = FIRST): VueWrapper {
  return mount(CandidateComparison, { props: { candidates: CANDIDATES, firstResultId } })
}

async function applyExternal(wrapper: VueWrapper, id: string) {
  await wrapper.find('[data-test="comparison-external-input"]').setValue(id)
  await wrapper.find('[data-test="comparison-external-apply"]').trigger('click')
}

async function runComparison(wrapper: VueWrapper) {
  await wrapper.find('[data-test="comparison-run"]').trigger('click')
  await flushPromises()
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('CandidateComparison 跨实验候选输入', () => {
  it('粘贴跨实验成果 ID 后调用后端比较并显示指标差（compatible）', async () => {
    vi.mocked(client.createProfessionalComparison).mockResolvedValue(COMPATIBLE)
    const wrapper = mountPanel()

    // 跨实验候选没有快捷按钮，只能走 ID 输入（含首尾空白，入库前需 trim）
    expect(wrapper.find(`[data-test="comparison-second-${EXTERNAL}"]`).exists()).toBe(false)
    await applyExternal(wrapper, `  ${EXTERNAL}  `)
    expect(wrapper.find('[data-test="comparison-second-current"]').text()).toContain(EXTERNAL)

    await runComparison(wrapper)
    expect(client.createProfessionalComparison).toHaveBeenCalledWith(FIRST, EXTERNAL)
    expect(wrapper.find('[data-test="comparison-compatible"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="common-valid-count"]').text()).toContain('40')
    const deltas = wrapper.findAll('[data-test="metric-delta-row"]')
    expect(deltas).toHaveLength(2)
    expect(wrapper.text()).toContain('-0.3')
    wrapper.unmount()
  })

  it('跨实验 incompatible：兼容结论来自后端，显示 mismatches 且无指标差', async () => {
    vi.mocked(client.createProfessionalComparison).mockResolvedValue(INCOMPATIBLE)
    const wrapper = mountPanel()

    await applyExternal(wrapper, EXTERNAL)
    await runComparison(wrapper)

    expect(client.createProfessionalComparison).toHaveBeenCalledWith(FIRST, EXTERNAL)
    expect(wrapper.find('[data-test="comparison-incompatible"]').exists()).toBe(true)
    const reasons = wrapper.find('[data-test="mismatch-reasons"]')
    expect(reasons.text()).toContain('dataset_version_id')
    expect(reasons.text()).toContain('validation_fingerprint')
    expect(wrapper.find('[data-test="metric-delta-row"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="common-valid-count"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('404（成果 ID 不存在）：显示后端错误封套 code 与 message', async () => {
    vi.mocked(client.createProfessionalComparison).mockRejectedValue(
      new client.ApiError('RESULT_NOT_FOUND', '成果不存在', 404),
    )
    const wrapper = mountPanel()

    await applyExternal(wrapper, EXTERNAL)
    await runComparison(wrapper)

    const error = wrapper.find('[data-test="comparison-error"]')
    expect(error.exists()).toBe(true)
    expect(error.text()).toContain('RESULT_NOT_FOUND')
    expect(error.text()).toContain('成果不存在')
    expect(wrapper.find('[data-test="comparison-compatible"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="comparison-incompatible"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('409（比较同一候选）：前端不自行拦截，透传后端错误封套', async () => {
    vi.mocked(client.createProfessionalComparison).mockRejectedValue(
      new client.ApiError('COMPARISON_SAME_CANDIDATE', '候选不能与自身比较', 409),
    )
    const wrapper = mountPanel()

    // 粘贴基准候选自身 ID：前端不做兼容判断，仍调用后端，由后端 409 拒绝
    await applyExternal(wrapper, FIRST)
    await runComparison(wrapper)

    expect(client.createProfessionalComparison).toHaveBeenCalledWith(FIRST, FIRST)
    const error = wrapper.find('[data-test="comparison-error"]')
    expect(error.text()).toContain('COMPARISON_SAME_CANDIDATE')
    expect(error.text()).toContain('候选不能与自身比较')
    wrapper.unmount()
  })

  it('409（候选非 succeeded）：显示后端错误封套', async () => {
    vi.mocked(client.createProfessionalComparison).mockRejectedValue(
      new client.ApiError('CANDIDATE_NOT_SUCCEEDED', '只有成功候选才能参与比较', 409),
    )
    const wrapper = mountPanel()

    await applyExternal(wrapper, EXTERNAL)
    await runComparison(wrapper)

    const error = wrapper.find('[data-test="comparison-error"]')
    expect(error.text()).toContain('CANDIDATE_NOT_SUCCEEDED')
    expect(error.text()).toContain('只有成功候选才能参与比较')
    wrapper.unmount()
  })

  it('非 UUID 形态输入：禁用设为对比候选并提示，绝不发起比较请求', async () => {
    const wrapper = mountPanel()
    const input = wrapper.find('[data-test="comparison-external-input"]')

    await input.setValue('not-a-uuid')
    expect(wrapper.find('[data-test="comparison-external-invalid"]').exists()).toBe(true)
    expect(
      wrapper.find('[data-test="comparison-external-apply"]').attributes('disabled'),
    ).toBeDefined()
    expect(wrapper.find('[data-test="comparison-run"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-test="comparison-second-current"]').exists()).toBe(false)

    await runComparison(wrapper)
    expect(client.createProfessionalComparison).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('切换基准候选后：second 选择、比较结果、错误与输入框全部清空', async () => {
    vi.mocked(client.createProfessionalComparison).mockResolvedValue(COMPATIBLE)
    const wrapper = mountPanel()

    await applyExternal(wrapper, EXTERNAL)
    await runComparison(wrapper)
    expect(wrapper.find('[data-test="comparison-compatible"]').exists()).toBe(true)

    // 切换 first：结果/second/输入框全部重置
    await wrapper.setProps({ firstResultId: SECOND_SAME_EXP })
    expect(wrapper.find('[data-test="comparison-compatible"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="comparison-second-current"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="comparison-error"]').exists()).toBe(false)
    expect(
      (wrapper.find('[data-test="comparison-external-input"]').element as HTMLInputElement).value,
    ).toBe('')
    expect(wrapper.find('[data-test="comparison-run"]').attributes('disabled')).toBeDefined()

    // 错误态同样被切换清空
    vi.mocked(client.createProfessionalComparison).mockRejectedValue(
      new client.ApiError('RESULT_NOT_FOUND', '成果不存在', 404),
    )
    await applyExternal(wrapper, EXTERNAL)
    await runComparison(wrapper)
    expect(wrapper.find('[data-test="comparison-error"]').exists()).toBe(true)
    await wrapper.setProps({ firstResultId: FIRST })
    expect(wrapper.find('[data-test="comparison-error"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="comparison-second-current"]').exists()).toBe(false)
    wrapper.unmount()
  })
})
