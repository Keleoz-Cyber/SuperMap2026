import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ExperimentLabLayout from '../ExperimentLabLayout.vue'

describe('ExperimentLabLayout', () => {
  it('shows params, canvas, summary and queue simultaneously at desktop width', () => {
    const wrapper = mount(ExperimentLabLayout, {
      props: { title: '插值实验', datasetLabel: 'samples.csv · 三维' },
      slots: {
        params: '<div data-test="slot-params">参数区</div>',
        canvas: '<div data-test="slot-canvas">实验画布</div>',
        summary: '<div data-test="slot-summary">候选摘要</div>',
        queue: '<div data-test="slot-queue">实验队列</div>',
        actions: '<button data-test="slot-action">创建实验并运行</button>',
      },
    })
    expect(wrapper.get('[data-test="lab-params"]').text()).toContain('参数区')
    expect(wrapper.get('[data-test="lab-canvas"]').text()).toContain('实验画布')
    expect(wrapper.get('[data-test="lab-summary"]').text()).toContain('候选摘要')
    expect(wrapper.get('[data-test="lab-queue"]').text()).toContain('实验队列')
    expect(wrapper.get('[data-test="lab-actions"]').text()).toContain('创建实验并运行')
    expect(wrapper.text()).toContain('samples.csv · 三维')
  })
})
