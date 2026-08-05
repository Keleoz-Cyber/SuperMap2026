import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ElementPlus from 'element-plus'
import OrthogonalSliceControls from '../OrthogonalSliceControls.vue'
import type { SliceAxis } from '../../../api/types'

// v0.7.0 Batch 2 Task 9：正交切片控制（轴/索引/真实坐标；绝不计算 SDK 相对位置）。

interface AxisMeta {
  length: number
  coordinates: number[]
  unit: string
}

function axes(): Record<SliceAxis, AxisMeta> {
  return {
    x: { length: 2, coordinates: [0, 100], unit: 'm' },
    y: { length: 3, coordinates: [0, 10, 20], unit: 'm' },
    z: { length: 4, coordinates: [0, 1, 2, 3], unit: 'm' },
  }
}

function mountControls(visibleMode: 'volume' | 'slice' | 'contour' = 'slice') {
  return mount(OrthogonalSliceControls, {
    props: { mode: visibleMode, axes: axes() },
    global: { plugins: [ElementPlus] },
    attachTo: document.body,
  })
}

describe('OrthogonalSliceControls', () => {
  it.each(['volume', 'contour'] as const)('%s 模式不渲染切片控件', (mode) => {
    const wrapper = mountControls(mode)
    expect(wrapper.find('[data-test="slice-controls"]').exists()).toBe(false)
  })

  it('slice 模式渲染轴选择与初始索引 floor((len-1)/2)', () => {
    const wrapper = mountControls('slice')
    expect(wrapper.get('[data-test="slice-controls"]').isVisible()).toBe(true)
    // 默认 Z 轴；轴长 2/3/4 → 各轴默认索引 0/1/1（z=4 → 1）
    expect(wrapper.get('[data-test="slice-index-value"]').text()).toBe('1')
    expect(wrapper.get('[data-test="slice-coordinate"]').text()).toContain('1')
  })

  it('切换轴恢复该轴自己的当前索引与真实坐标', async () => {
    const wrapper = mountControls('slice')
    await wrapper.find('[data-test="axis-y"]').trigger('click')
    expect(wrapper.get('[data-test="slice-index-value"]').text()).toBe('1')
    expect(wrapper.get('[data-test="slice-coordinate"]').text()).toContain('10')
    await wrapper.find('[data-test="axis-z"]').trigger('click')
    expect(wrapper.get('[data-test="slice-index-value"]').text()).toBe('1')
    expect(wrapper.get('[data-test="slice-coordinate"]').text()).toContain('1')
    await wrapper.find('[data-test="axis-x"]').trigger('click')
    expect(wrapper.get('[data-test="slice-index-value"]').text()).toBe('0')
  })

  it('change 事件携带轴/索引/真实坐标；commit 携带轴/索引', async () => {
    const wrapper = mountControls('slice')
    await wrapper.find('[data-test="axis-z"]').trigger('click')
    await wrapper.find('[data-test="slice-next"]').trigger('click')
    const changes = wrapper.emitted('change')
    expect(changes).toBeTruthy()
    const last = changes![changes!.length - 1][0] as { axis: string; index: number; coordinate: number }
    expect(last).toEqual({ axis: 'z', index: 2, coordinate: 2 })

    const slider = wrapper.findComponent({ name: 'ElSlider' })
    ;(slider.vm as unknown as { $emit: (e: string, v: number) => void }).$emit('change', 3)
    const commits = wrapper.emitted('commit')
    expect(commits).toBeTruthy()
  })

  it('前后层在轴首尾禁用且不循环', async () => {
    const wrapper = mountControls('slice')
    // 先切到 X（索引 0）：prev 必须禁用
    await wrapper.find('[data-test="axis-x"]').trigger('click')
    expect(wrapper.get('[data-test="slice-prev"]').attributes('disabled')).toBeDefined()
    await wrapper.find('[data-test="slice-next"]').trigger('click')
    expect(wrapper.get('[data-test="slice-index-value"]').text()).toBe('1')
    expect(wrapper.get('[data-test="slice-next"]').attributes('disabled')).toBeDefined()
    // 再点也不越界
    await wrapper.find('[data-test="slice-next"]').trigger('click')
    expect(wrapper.get('[data-test="slice-index-value"]').text()).toBe('1')
  })
})
