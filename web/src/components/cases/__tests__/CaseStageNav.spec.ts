import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CaseStageNav from '../CaseStageNav.vue'
import type { CaseStage } from '../CaseStageNav.vue'

const STAGES: CaseStage[] = [
  { id: 'data', enabled: true },
  { id: 'experiments', enabled: true },
  { id: 'results', enabled: true },
  { id: 'evidence', enabled: true },
]

describe('CaseStageNav', () => {
  it('renders the four business stages in order', () => {
    const wrapper = mount(CaseStageNav, { props: { stages: STAGES, current: 'data' } })
    const labels = wrapper.findAll('[data-test^="stage-nav-"]').map((x) => x.text())
    expect(wrapper.find('[data-test="stage-nav-data"]').text()).toContain('数据概览')
    expect(wrapper.find('[data-test="stage-nav-experiments"]').text()).toContain('建模实验')
    expect(wrapper.find('[data-test="stage-nav-results"]').text()).toContain('成果分析')
    expect(wrapper.find('[data-test="stage-nav-evidence"]').text()).toContain('证据与报告')
    expect(labels).toHaveLength(4)
  })

  it('marks the current stage and emits named navigation intents', async () => {
    const wrapper = mount(CaseStageNav, { props: { stages: STAGES, current: 'data' } })
    expect(wrapper.get('[data-test="stage-nav-data"]').attributes('aria-current')).toBe('true')
    await wrapper.get('[data-test="stage-nav-results"]').trigger('click')
    expect(wrapper.emitted('navigate')).toEqual([['results']])
  })

  it('disabled stages stay visible with a reason and never emit', async () => {
    const stages: CaseStage[] = [
      { id: 'data', enabled: true },
      { id: 'experiments', enabled: false, reason: '数据版本未验证' },
      { id: 'results', enabled: false, reason: '暂无成果' },
      { id: 'evidence', enabled: true },
    ]
    const wrapper = mount(CaseStageNav, { props: { stages, current: 'data' } })
    const experiments = wrapper.get('[data-test="stage-nav-experiments"]')
    expect(experiments.attributes('disabled')).toBeDefined()
    expect(experiments.text()).toContain('数据版本未验证')
    await experiments.trigger('click')
    expect(wrapper.emitted('navigate')).toBeUndefined()
  })
})
