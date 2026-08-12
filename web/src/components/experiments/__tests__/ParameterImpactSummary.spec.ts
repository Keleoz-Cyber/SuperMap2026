import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ParameterImpactSummary from '../ParameterImpactSummary.vue'

describe('ParameterImpactSummary', () => {
  it('states grid nodes, folds, neighborhood and combination count truthfully', () => {
    const wrapper = mount(ParameterImpactSummary, {
      props: {
        algorithm: 'ordinary_kriging',
        searchMode: 'grid',
        combinationCount: 27,
        grid: { bounds: [[0, 100], [0, 80], [-50, 0]], resolution: [10, 10, 5] },
        validation: { method: 'spatial_kfold', folds: 5, seed: 20260723, holdout_fraction: 0.2 },
        parameters: { variogram_model: 'exponential', neighbor_count: 24 },
        warnings: [],
      },
    })
    const text = wrapper.text()
    expect(text).toContain('1,089') // 11×9×11（逐轴间距 → 节点数）
    expect(text).toContain('5') // 折数
    expect(text).not.toContain('20260723') // 随机种子属于高级技术设置
    expect(text).toContain('27') // 组合数
    expect(text).toContain('exponential')
  })

  it('shows explicit warnings and the 50-combination cap risk', () => {
    const wrapper = mount(ParameterImpactSummary, {
      props: {
        algorithm: 'idw',
        searchMode: 'grid',
        combinationCount: 64,
        grid: null,
        validation: null,
        parameters: {},
        warnings: ['组合数 64 超过上限 50，请收窄参数网格'],
      },
    })
    expect(wrapper.text()).toContain('组合数 64 超过上限 50')
    expect(wrapper.find('[data-test="impact-warnings"]').exists()).toBe(true)
  })

  it('without grid/validation shows honest placeholders, never fabricated numbers', () => {
    const wrapper = mount(ParameterImpactSummary, {
      props: {
        algorithm: 'idw',
        searchMode: 'manual',
        combinationCount: 1,
        grid: null,
        validation: null,
        parameters: {},
        warnings: [],
      },
    })
    expect(wrapper.text()).toContain('默认网格')
    expect(wrapper.text()).not.toContain('NaN')
  })
})
