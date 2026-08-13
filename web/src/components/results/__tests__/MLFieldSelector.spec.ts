import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import MLFieldSelector from '../MLFieldSelector.vue'

describe('MLFieldSelector', () => {
  it('只展示后端声明可用的字段，并使用用户可读名称与单位语义', async () => {
    const wrapper = mount(MLFieldSelector, {
      props: {
        modelValue: 'prediction',
        availableFields: ['prediction', 'model_dispersion', 'residual_correction'],
        propertyUnit: 'Ω·m',
      },
    })
    expect(wrapper.text()).toContain('预测结果')
    expect(wrapper.text()).toContain('模型离散度')
    expect(wrapper.text()).toContain('残差校正')
    expect(wrapper.text()).not.toContain('克里金基线')
    expect(wrapper.text()).toContain('Ω·m')
    await wrapper.get('[data-test="ml-field-residual_correction"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')).toEqual([['residual_correction']])
  })

  it('加载时禁用切换，避免并行点击制造身份竞态', () => {
    const wrapper = mount(MLFieldSelector, {
      props: {
        modelValue: 'prediction',
        availableFields: ['prediction', 'model_dispersion'],
        loading: true,
      },
    })
    expect(wrapper.get('[data-test="ml-field-model_dispersion"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="ml-field-status"]').text()).toContain('正在切换')
  })
})
