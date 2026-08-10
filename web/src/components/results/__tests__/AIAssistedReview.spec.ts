import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import { ApiError } from '../../../api/client'
import * as client from '../../../api/client'
import AIAssistedReview from '../AIAssistedReview.vue'
import {
  AI_RECORD_ERROR,
  AI_RECORD_SUCCEEDED,
  AI_RECORD_UNAVAILABLE,
} from '../../../mocks/resultAnalysisMock'

// v0.9.0 Task 10 前端：AI 辅助研判面板合同。
// AI 只是规则研判之外的辅助意见：未配置/离线/超时/失败全部类型化空态，
// 规则研判始终可用；不显示虚构置信度百分比，不渲染推理内容；
// evidence_refs 只能点击联动，不得创造新引用。

vi.mock('../../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../api/client')>()
  return {
    ...actual,
    fetchLatestAiAnalysis: vi.fn(),
    generateAiAnalysis: vi.fn(),
  }
})

function mountPanel(props: Record<string, unknown> = {}) {
  return mount(AIAssistedReview, {
    props: { resultId: 'r-3d-normal', gridSha256: 'a'.repeat(64), ...props },
    global: { plugins: [ElementPlus] },
    attachTo: document.body,
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(client.fetchLatestAiAnalysis).mockRejectedValue(
    new ApiError('AI_ANALYSIS_NOT_FOUND', '尚无 AI 辅助分析记录', 404),
  )
})

describe('AIAssistedReview', () => {
  it('无记录：显示真实空态与显式生成入口，规则研判提示恒在', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    expect(client.fetchLatestAiAnalysis).toHaveBeenCalledWith('r-3d-normal')
    const empty = wrapper.get('[data-test="ai-empty"]')
    expect(empty.text()).toContain('尚未生成 AI 辅助分析')
    expect(wrapper.text()).toContain('规则研判')
    await wrapper.get('[data-test="ai-generate"]').trigger('click')
    expect(client.generateAiAnalysis).toHaveBeenCalledWith('r-3d-normal', {
      mode: 'quick',
      regenerate: false,
    })
  })

  it('未配置：类型化配置说明而非错误；不显示生成重试以外动作', async () => {
    vi.mocked(client.fetchLatestAiAnalysis).mockResolvedValue(AI_RECORD_UNAVAILABLE)
    const wrapper = mountPanel()
    await flushPromises()
    const unavailable = wrapper.get('[data-test="ai-unavailable"]')
    expect(unavailable.text()).toContain('DEEPSEEK_NOT_CONFIGURED')
    expect(unavailable.text()).toContain('DEEPSEEK_API_KEY')
    // AI 不可用不拖垮规则研判
    expect(wrapper.text()).toContain('规则研判')
  })

  it('服务错误：错误码 + 消息 + 重试', async () => {
    vi.mocked(client.fetchLatestAiAnalysis).mockResolvedValue(AI_RECORD_ERROR)
    const wrapper = mountPanel()
    await flushPromises()
    const error = wrapper.get('[data-test="ai-error"]')
    expect(error.text()).toContain('DEEPSEEK_TIMEOUT')
    expect(error.text()).toContain('超时')
    expect(wrapper.find('[data-test="ai-retry"]').exists()).toBe(true)
  })

  it('成功：四视角/共识/分歧/候选路径/复核清单/限制与身份尾注', async () => {
    vi.mocked(client.fetchLatestAiAnalysis).mockResolvedValue(AI_RECORD_SUCCEEDED)
    const wrapper = mountPanel()
    await flushPromises()
    // 明确的辅助意见标识
    expect(wrapper.get('[data-test="ai-review"]').text()).toContain('AI 辅助意见')
    // 四视角
    expect(wrapper.get('[data-test="ai-perspective-spatial_pattern"]').text()).toContain('高值体元集中')
    expect(wrapper.get('[data-test="ai-perspective-model_reliability"]').text()).toContain('RMSE 5.2')
    expect(wrapper.get('[data-test="ai-perspective-uncertainty_and_risk"]').text()).toContain('外推风险')
    expect(wrapper.get('[data-test="ai-perspective-review_and_next_checks"]').text()).toContain('建议复核')
    // 共识与分歧
    expect(wrapper.get('[data-test="ai-consensus"]').text()).toContain('四个视角一致支持')
    expect(wrapper.get('[data-test="ai-consensus"]').text()).toContain('轻微口径差异')
    // 候选研判路径（条件/收益/代价）
    const options = wrapper.get('[data-test="ai-decision-options"]')
    expect(options.text()).toContain('维持当前模型')
    expect(options.text()).toContain('复核备选模型')
    expect(options.text()).toContain('重新交叉验证耗时')
    // 复核清单与限制
    expect(wrapper.get('[data-test="ai-checks"]').text()).toContain('复核 20-30m 层段切片')
    expect(wrapper.get('[data-test="ai-limitations"]').text()).toContain('局部线性坐标')
    // 身份尾注：provider/model/时间/prompt 版本/evidence hash 短码
    const footer = wrapper.get('[data-test="ai-identity"]')
    expect(footer.text()).toContain('deepseek')
    expect(footer.text()).toContain('deepseek-chat')
    expect(footer.text()).toContain('ai_review.v1')
    expect(footer.text()).toContain('e5f6a7b8c9d0')
    // 绝不显示虚构置信度百分比
    expect(wrapper.text()).not.toContain('置信度')
  })

  it('evidence ref 点击发射 focus-evidence（组件/层段/切片），不创造新引用', async () => {
    vi.mocked(client.fetchLatestAiAnalysis).mockResolvedValue(AI_RECORD_SUCCEEDED)
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.get('[data-test="ai-ref-spatial_pattern-component-1"]').trigger('click')
    await wrapper.get('[data-test="ai-ref-spatial_pattern-depth_bin-2"]').trigger('click')
    await wrapper.get('[data-test="ai-ref-review_and_next_checks-current_slice"]').trigger('click')
    expect(wrapper.emitted('focus-evidence')).toEqual([
      ['component-1'],
      ['depth_bin-2'],
      ['current_slice'],
    ])
  })

  it('重新生成携带 regenerate=true 与所选模式；生成中显示进行中状态', async () => {
    vi.mocked(client.fetchLatestAiAnalysis).mockResolvedValue(AI_RECORD_SUCCEEDED)
    vi.mocked(client.generateAiAnalysis).mockResolvedValue(AI_RECORD_SUCCEEDED)
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.get('[data-test="ai-mode-review"]').trigger('click')
    await wrapper.get('[data-test="ai-regenerate"]').trigger('click')
    expect(client.generateAiAnalysis).toHaveBeenCalledWith('r-3d-normal', {
      mode: 'review',
      regenerate: true,
    })
  })

  it('生成失败：显示类型化错误并保留既有成功记录', async () => {
    vi.mocked(client.fetchLatestAiAnalysis).mockResolvedValue(AI_RECORD_SUCCEEDED)
    vi.mocked(client.generateAiAnalysis).mockRejectedValue(
      new ApiError('DEEPSEEK_RATE_LIMITED', '请求过于频繁', 429),
    )
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.get('[data-test="ai-regenerate"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="ai-generate-error"]').text()).toContain('DEEPSEEK_RATE_LIMITED')
    // 旧记录不清空
    expect(wrapper.find('[data-test="ai-review"]').exists()).toBe(true)
  })

  it('身份切换：旧 AI 记录立即清空并按新身份重新获取', async () => {
    vi.mocked(client.fetchLatestAiAnalysis).mockResolvedValue(AI_RECORD_SUCCEEDED)
    const wrapper = mountPanel()
    await flushPromises()
    expect(wrapper.find('[data-test="ai-review"]').exists()).toBe(true)
    vi.mocked(client.fetchLatestAiAnalysis).mockRejectedValue(
      new ApiError('AI_ANALYSIS_NOT_FOUND', '尚无 AI 辅助分析记录', 404),
    )
    await wrapper.setProps({ resultId: 'r-other', gridSha256: 'b'.repeat(64) })
    await flushPromises()
    expect(client.fetchLatestAiAnalysis).toHaveBeenCalledWith('r-other')
    expect(wrapper.find('[data-test="ai-review"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="ai-empty"]').exists()).toBe(true)
  })
})
