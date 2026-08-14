import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { PresentationFinding } from '../../../domain/findings'
import FindingPanel from '../FindingPanel.vue'

const BASE: PresentationFinding = {
  id: 'quality',
  title: '数据质量',
  statement: '有效数据 96/100（96%）',
  evidence: ['重复坐标 0'],
  source: { datasetId: 'ds-1', sourceSha256: 'abc', calculationVersion: 'analysis.v1' },
  confidence: 'verified',
  limitations: ['无效行没有参加插值'],
}

const WITH_TARGET: PresentationFinding = {
  ...BASE,
  id: 'spatial-anomaly',
  title: '空间异常',
  confidence: 'exploratory',
  spatialTarget: { axis: 'xy', xRange: [0, 50], yRange: [0, 40] },
}

describe('FindingPanel', () => {
  it('renders at most five ordered finding cards', () => {
    const many = Array.from({ length: 7 }, (_, i) => ({ ...BASE, id: `f-${i}` }))
    const wrapper = mount(FindingPanel, { props: { findings: many } })
    expect(wrapper.findAll('[data-test="finding-card"]')).toHaveLength(5)
  })

  it('shows an explanatory empty state when no findings are available', () => {
    const wrapper = mount(FindingPanel, { props: { findings: [] } })
    expect(wrapper.get('[data-test="findings-empty"]').text()).toContain('暂无')
  })

  it('emits locate only for findings with a spatial target', async () => {
    const wrapper = mount(FindingPanel, { props: { findings: [BASE, WITH_TARGET] } })
    const cards = wrapper.findAll('[data-test="finding-card"]')
    expect(cards).toHaveLength(2)
    expect(cards[0].find('[data-test="finding-locate"]').exists()).toBe(false)
    await cards[1].get('[data-test="finding-locate"]').trigger('click')
    const events = wrapper.emitted('locate')
    expect(events).toHaveLength(1)
    expect((events?.[0] as [PresentationFinding])[0].id).toBe('spatial-anomaly')
  })

  it('uses a plain-language review label instead of exploratory jargon', () => {
    const wrapper = mount(FindingPanel, { props: { findings: [WITH_TARGET] } })
    expect(wrapper.text()).toContain('建议复核')
    expect(wrapper.text()).not.toContain('探索性')
  })

  it('shows limitations and evidence chips', () => {
    const wrapper = mount(FindingPanel, { props: { findings: [BASE] } })
    expect(wrapper.text()).toContain('无效行没有参加插值')
    expect(wrapper.text()).toContain('重复坐标 0')
  })
})
