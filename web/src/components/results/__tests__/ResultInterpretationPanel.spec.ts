import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ElementPlus from 'element-plus'
import ResultInterpretationPanel from '../ResultInterpretationPanel.vue'
import {
  RESULT_ANALYSIS_MOCK_2D,
  RESULT_ANALYSIS_MOCK_3D,
  SLICE_ANALYSIS_MOCK,
  SLICE_ANALYSIS_MOCK_NO_THRESHOLDS,
} from '../../../mocks/resultAnalysisMock'

// v0.9.0 Task 6：规则研判面板合同。全部数字/文案只来自后端
// ResultAnalysisSummary 与权威切片响应；前端绝不重算阈值、排序或结论。
// 面板只发射聚焦事件（组件/层段/证据引用），不直接操作渲染器。

function mountPanel(props: Record<string, unknown> = {}) {
  return mount(ResultInterpretationPanel, {
    props: {
      analysis: RESULT_ANALYSIS_MOCK_3D,
      currentSlice: null,
      focusedComponentId: null,
      ...props,
    },
    global: { plugins: [ElementPlus] },
    attachTo: document.body,
  })
}

describe('ResultInterpretationPanel', () => {
  it('renders domain interpretation as a natural narrative with one concrete action', async () => {
    const analysis = structuredClone(RESULT_ANALYSIS_MOCK_3D) as typeof RESULT_ANALYSIS_MOCK_3D & {
      domain_interpretation: Record<string, unknown>
    }
    analysis.domain_interpretation = {
      rule_version: 'geological_interpretation.v1',
      profile: 'resistivity',
      panel_label: '地质研判',
      narrative_label: '地下电性结构',
      status: 'exploratory',
      overview: '共找到 1 个值得复核的区域。先看低阻异常区 低-A。',
      cards: [
        {
          id: 'domain-low-1000001',
          component_id: 1000001,
          direction: 'low',
          title: '低阻异常区 低-A',
          summary: '位于 Z=-610～-420，模型中覆盖约 64000，没有碰到模型边缘',
          evidence: ['覆盖 8 个网格点', '数值 10～12'],
          possible_interpretations: ['这一带的低阻可能与含水、裂隙较多或黏土富集有关'],
          potential_impacts: ['如果钻孔或水文记录也有异常，应优先检查这里'],
          recommended_actions: ['先对照钻孔、水文记录和其他物探结果'],
          confidence: 'exploratory',
          limitations: ['低阻有多种成因，不能只凭低阻结果判断这里有水'],
          spatial_target: { kind: 'component', component_id: 1000001, depth_bin_index: null },
        },
      ],
      global_limitations: ['这些高低值按模型自身的数值分布划分，尚未经过现场确认'],
    }
    const wrapper = mountPanel({ analysis })
    await flushPromises()

    expect(wrapper.get('[data-test="domain-overview"]').text()).toContain('低阻异常')
    const card = wrapper.get('[data-test="domain-card-low-1000001"]')
    expect(card.text()).toContain('这一带的低阻可能与含水')
    expect(card.text()).toContain('如果钻孔或水文记录也有异常')
    expect(card.text()).toContain('建议：先对照钻孔、水文记录')
    expect(card.text()).toContain('注意：低阻有多种成因')
    expect(card.text()).toContain('查看数值')
    expect(card.text()).not.toContain('事实')
    expect(card.text()).not.toContain('可能解释')
    expect(card.text()).not.toContain('潜在影响')
    expect(card.text()).not.toContain('建议核查')
    expect(wrapper.get('[data-test="domain-overview"]').text()).toContain('建议复核')
    expect(wrapper.get('[data-test="technical-evidence"]').text()).toContain('计算说明')
    expect(wrapper.text()).not.toContain('技术证据与模型口径')
    expect(wrapper.text()).not.toContain('证据边界')
    await wrapper.get('[data-test="domain-locate-1000001"]').trigger('click')
    expect(wrapper.emitted('focus-component')).toEqual([[1000001]])
  })

  it('renders backend findings with confidence, limitations and spatial locate emission', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    const findings = wrapper.get('[data-test="interpretation-findings"]')
    expect(findings.text()).toContain('哪个深度层高值最多')
    expect(findings.text()).toContain('最大的连续高值区')
    // 组件空间目标 → focus-component；层段目标 → focus-depth-bin
    await wrapper.get('[data-test="finding-locate-finding-largest-component"]').trigger('click')
    expect(wrapper.emitted('focus-component')).toEqual([[1]])
    await wrapper.get('[data-test="finding-locate-finding-dominant-depth"]').trigger('click')
    expect(wrapper.emitted('focus-depth-bin')).toEqual([[2]])
    // 无空间目标的发现不显示定位按钮
    expect(wrapper.find('[data-test="finding-locate-finding-boundary-contact"]').exists()).toBe(false)
    // 限制文案使用普通表达，同时保留“不是真实体积”的必要提醒
    expect(findings.text()).toContain('这里只表示模型覆盖大小，不是真实地质体积')
    expect(findings.text()).toContain('正式模型：普通克里金')
    expect(findings.text()).not.toContain('Ordinary Kriging')
  })

  it('renders overview with backend composition and thresholds under explicit result-grid label', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    const overview = wrapper.get('[data-test="interpretation-overview"]')
    // 成果网格身份标签必须明确（与输入样本区分）
    expect(overview.text()).toContain('成果网格')
    expect(overview.text()).toContain('电阻率（Ω·m）')
    expect(overview.text()).not.toContain('RHO')
    // 组成比例逐字来自 DTO（25% / 50% / 25%），前端不得重算
    expect(overview.text()).toContain('25.0%')
    expect(overview.text()).toContain('50.0%')
    // 阈值来自后端 thresholds，不显示前端推导的分位值
    expect(overview.text()).toContain('25')
    expect(overview.text()).toContain('70')
    // 统计口径声明为体元节点占比，绝不称储量/真实体积
    expect(overview.text()).toContain('体元节点')
    expect(overview.text()).not.toContain('储量')
    expect(overview.text()).not.toContain('危险等级')
    expect(overview.text()).not.toContain('已确认边界')
  })

  it('renders component rows with support measure, boundary badge and uncertainty; click focuses 3D', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    const block = wrapper.get('[data-test="interpretation-components"]')
    expect(block.text()).toContain('阈值')
    const rowA = wrapper.get('[data-test="component-1"]')
    expect(rowA.text()).toContain('A')
    expect(rowA.text()).toContain('100')
    expect(rowA.text()).toContain('500')
    expect(rowA.text()).toContain('模型覆盖范围估计')
    // A 区不接触边界；B/C 接触边界徽标
    expect(rowA.text()).not.toContain('接触边界')
    expect(wrapper.get('[data-test="component-2"]').text()).toContain('接触边界')
    expect(wrapper.get('[data-test="component-3"]').text()).toContain('接触边界')
    // 不确定性字段：A 有 kriging_std_mean=2.5；B/C 无该字段（null 不渲染）
    expect(rowA.text()).toContain('2.5')
    expect(wrapper.get('[data-test="component-2"]').text()).not.toContain('Kriging')
    // 点击组件行 → 发射 focus-component（三维聚焦由父级落地）
    await wrapper.get('[data-test="component-2"]').trigger('click')
    expect(wrapper.emitted('focus-component')).toEqual([[2]])
  })

  it('highlights the focused component row and clears highlight when selection changes', async () => {
    const wrapper = mountPanel({ focusedComponentId: 2 })
    await flushPromises()
    expect(wrapper.get('[data-test="component-2"]').classes()).toContain('focused')
    expect(wrapper.get('[data-test="component-1"]').classes()).not.toContain('focused')
    await wrapper.setProps({ focusedComponentId: null })
    expect(wrapper.get('[data-test="component-2"]').classes()).not.toContain('focused')
  })

  it('shows typed current-slice empty state, then authoritative slice statistics with full-grid delta', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    expect(wrapper.find('[data-test="slice-empty"]').exists()).toBe(true)
    await wrapper.setProps({ currentSlice: SLICE_ANALYSIS_MOCK })
    await flushPromises()
    const slice = wrapper.get('[data-test="interpretation-slice"]')
    expect(slice.text()).toContain('Z')
    expect(slice.text()).toContain('-400')
    expect(slice.text()).toContain('有效 11')
    // 共享完整网格阈值的组成（夹具：低 3 / 正常 5 / 高 3）
    expect(slice.text()).toContain('按完整模型的 p25/p75 划分')
    expect(slice.text()).toContain('27.3%')
    expect(slice.text()).toContain('45.5%')
    // 与完整场高值占比差值（切片 27.3% - 全场 25.0%）
    expect(slice.text()).toContain('+2.3')
  })

  it('shows typed note when slice statistics lack full-grid thresholds', async () => {
    const wrapper = mountPanel({ currentSlice: SLICE_ANALYSIS_MOCK_NO_THRESHOLDS })
    await flushPromises()
    const slice = wrapper.get('[data-test="interpretation-slice"]')
    expect(slice.text()).toContain('未提供完整网格阈值')
  })

  it('renders model evidence and uncertainty without inventing metrics', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    const model = wrapper.get('[data-test="interpretation-model"]')
    expect(model.text()).toContain('普通克里金')
    expect(model.text()).not.toContain('ordinary_kriging')
    expect(model.text()).toContain('5.2')
    expect(model.text()).toContain('0.92')
    expect(model.text()).toContain('共同参与比较的点 50')
    expect(model.text()).toContain('当前使用的正式模型')
    expect(model.text()).not.toContain('最佳候选')
    expect(model.text()).not.toContain('candidate_valid_count')
    expect(model.text()).not.toContain('candidate_nodata_count')
    expect(model.text()).not.toContain('total_count')
    // 无 null/NaN/undefined 文本泄漏
    expect(model.text()).not.toContain('NaN')
    expect(model.text()).not.toContain('undefined')
    expect(model.text()).not.toContain('null')
  })

  it('normalizes internal grid support units in backend finding copy', async () => {
    const analysis = structuredClone(RESULT_ANALYSIS_MOCK_3D)
    analysis.findings[0].statement = 'A 区网格支持量 500（volume_coordinate_unit3）'
    const wrapper = mountPanel({ analysis })
    await flushPromises()

    const findings = wrapper.get('[data-test="interpretation-findings"]')
    expect(findings.text()).toContain('网格坐标单位³')
    expect(findings.text()).not.toContain('volume_coordinate_unit3')
  })

  it('only presents defined product metrics in the primary model summary', async () => {
    const analysis = structuredClone(RESULT_ANALYSIS_MOCK_3D)
    Object.assign(analysis.model_evidence.metrics, {
      candidate_valid_count: 50,
      candidate_nodata_count: 0,
      total_count: 50,
    })
    const wrapper = mountPanel({ analysis })
    await flushPromises()

    const model = wrapper.get('[data-test="interpretation-model"]')
    expect(model.text()).not.toContain('candidate_valid_count')
    expect(model.text()).not.toContain('candidate_nodata_count')
    expect(model.text()).not.toContain('total_count')
  })

  it('renders formal-selection and 2D depth typed states', async () => {
    const wrapper = mountPanel({ analysis: RESULT_ANALYSIS_MOCK_2D })
    await flushPromises()
    const model = wrapper.get('[data-test="interpretation-model"]')
    expect(model.text()).toContain('未选择正式模型')
    const overview = wrapper.get('[data-test="interpretation-overview"]')
    expect(overview.text()).toContain('深度分层不适用')
    // 2D 支持量口径为面积
    expect(wrapper.get('[data-test="component-1"]').text()).toContain('模型覆盖范围估计')
  })

  it('shows typed empty, loading and error states without stale numbers', async () => {
    const wrapper = mountPanel({ analysis: null })
    await flushPromises()
    expect(wrapper.find('[data-test="interpretation-empty"]').exists()).toBe(true)
    await wrapper.setProps({ loading: true })
    expect(wrapper.find('[data-test="interpretation-loading"]').exists()).toBe(true)
    await wrapper.setProps({ loading: false, error: 'RESULT_NOT_MATERIALIZED：成果未物化' })
    expect(wrapper.get('[data-test="interpretation-error"]').text()).toContain('RESULT_NOT_MATERIALIZED')
    // 错误态绝不残留旧数字
    expect(wrapper.find('[data-test="interpretation-overview"]').exists()).toBe(false)
  })
})
