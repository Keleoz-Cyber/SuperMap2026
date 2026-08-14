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
    expect(client.fetchLatestAiAnalysis).toHaveBeenCalledWith('r-3d-normal', 'quick')
    const empty = wrapper.get('[data-test="ai-empty"]')
    expect(empty.text()).toContain('尚未生成快速解读')
    expect(wrapper.text()).toContain('地质研判')
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
    expect(wrapper.text()).toContain('地质研判')
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

  it('成功：结论优先、关键判断、行动与方案比较具有明确层级', async () => {
    vi.mocked(client.fetchLatestAiAnalysis).mockResolvedValue(AI_RECORD_SUCCEEDED)
    const wrapper = mountPanel()
    await flushPromises()
    expect(wrapper.get('[data-test="ai-conclusion"]').text()).toContain('几项分析都显示')
    expect(wrapper.get('[data-test="ai-review"]').text()).toContain('快速解读')
    expect(wrapper.get('[data-test="ai-review"]').text()).toContain('需要留意的地方')
    expect(wrapper.get('[data-test="ai-review"]').text()).not.toContain('解释边界')
    // 分项分析
    expect(wrapper.get('[data-test="ai-perspective-spatial_pattern"]').text()).toContain('高值主要集中')
    expect(wrapper.get('[data-test="ai-perspective-model_reliability"]').text()).toContain('RMSE 5.2')
    expect(wrapper.get('[data-test="ai-perspective-uncertainty_and_risk"]').text()).toContain('补充边缘测点')
    expect(wrapper.get('[data-test="ai-perspective-review_and_next_checks"]').text()).toContain('建议复核')
    // 共识与分歧
    expect(wrapper.get('[data-test="ai-consensus"]').text()).toContain('几项分析都显示')
    expect(wrapper.get('[data-test="ai-consensus"]').text()).toContain('略有不同')
    // 候选研判路径（条件/收益/代价）
    const options = wrapper.get('[data-test="ai-decision-options"]')
    expect(options.text()).toContain('维持当前模型')
    expect(options.text()).toContain('复核备选模型')
    expect(options.text()).toContain('重新交叉验证耗时')
    // 复核清单与限制
    expect(wrapper.get('[data-test="ai-checks"]').text()).toContain('复核 20-30m 层段切片')
    expect(wrapper.get('[data-test="ai-limitations"]').text()).toContain('当前使用局部坐标')
    // 身份尾注：provider/model/时间/prompt 版本/evidence hash 短码
    await wrapper.get('[data-test="ai-technical-details"]').trigger('click')
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
    await wrapper.get('[data-test="ai-evidence-spatial_pattern"]').trigger('click')
    expect(wrapper.text()).toContain('异常区域 A')
    expect(wrapper.text()).toContain('深度层段 3')
    expect(wrapper.text()).not.toContain('component-1')
    expect(wrapper.text()).not.toContain('depth_bin-2')
    await wrapper.get('[data-test="ai-ref-spatial_pattern-component-1"]').trigger('click')
    await wrapper.get('[data-test="ai-ref-spatial_pattern-depth_bin-2"]').trigger('click')
    await wrapper.get('[data-test="ai-ref-review_and_next_checks-current_slice"]').trigger('click')
    expect(wrapper.emitted('focus-evidence')).toEqual([
      ['component-1'],
      ['depth_bin-2'],
      ['current_slice'],
    ])
  })

  it('切换模式按模式读取记录，不混用快速解读内容，也不自动触发付费生成', async () => {
    vi.mocked(client.fetchLatestAiAnalysis).mockResolvedValue(AI_RECORD_SUCCEEDED)
    const wrapper = mountPanel()
    await flushPromises()
    vi.mocked(client.fetchLatestAiAnalysis).mockRejectedValue(
      new ApiError('AI_ANALYSIS_NOT_FOUND', '尚无深度复核记录', 404),
    )
    await wrapper.get('[data-test="ai-mode-review"]').trigger('click')
    await flushPromises()
    expect(client.fetchLatestAiAnalysis).toHaveBeenLastCalledWith('r-3d-normal', 'review')
    expect(client.generateAiAnalysis).not.toHaveBeenCalled()
    expect(wrapper.find('[data-test="ai-review"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="ai-empty"]').text()).toContain('尚未生成深度复核')
  })

  it('旧服务忽略 mode 时前端拒绝展示模式不匹配的记录', async () => {
    vi.mocked(client.fetchLatestAiAnalysis).mockResolvedValue(AI_RECORD_SUCCEEDED)
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.get('[data-test="ai-mode-review"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="ai-review"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="ai-empty"]').text()).toContain('尚未生成深度复核')
  })

  it('深度复核生成入口明确说明模式并携带 review', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.get('[data-test="ai-mode-review"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="ai-generate"]').trigger('click')
    expect(client.generateAiAnalysis).toHaveBeenCalledWith('r-3d-normal', {
      mode: 'review',
      regenerate: false,
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
    expect(client.fetchLatestAiAnalysis).toHaveBeenCalledWith('r-other', 'quick')
    expect(wrapper.find('[data-test="ai-review"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="ai-empty"]').exists()).toBe(true)
  })
})
