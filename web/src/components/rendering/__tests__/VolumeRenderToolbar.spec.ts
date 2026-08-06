import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ElementPlus from 'element-plus'
import VolumeRenderToolbar from '../VolumeRenderToolbar.vue'
import type { RenderProfile } from '../../../api/types'
import type { RenderStateV2 } from '../renderProtocol'
import { PALETTES } from '../renderTransferFunctions'

// v0.7.0 Batch 2 Task 9：常驻渲染工具栏（完整状态克隆输出）。

function makeState(overrides: Partial<RenderStateV2> = {}): RenderStateV2 {
  return {
    revision: 1,
    mode: 'volume',
    filter: { min: 1, max: 1000 },
    opacity: 1,
    colorTransferFunction: [
      { value: 1, color: '#440154' },
      { value: 1000, color: '#fde725' },
    ],
    lighting: true,
    gradientOpacity: true,
    boundingBox: true,
    ...overrides,
  }
}

function makeProfile(overrides: Partial<RenderProfile> = {}): RenderProfile {
  return {
    property_name: 'RHO',
    unit: 'unknown',
    default_scale: 'linear',
    default_palette: 'viridis',
    log_available: true,
    value_range: [1, 1000],
    filter_range: [1, 1000],
    lighting: true,
    gradient_opacity: true,
    bounding_box: true,
    opacity: 1,
    ...overrides,
  }
}

function mountToolbar(state = makeState(), profile = makeProfile(), enabled = true) {
  return mount(VolumeRenderToolbar, {
    props: { modelValue: state, profile, enabled, 'onUpdate:modelValue': () => {} },
    global: { plugins: [ElementPlus] },
    attachTo: document.body,
  })
}

describe('VolumeRenderToolbar', () => {
  it('分段模式/常驻控件全部渲染；光照与渐变透明度可用', () => {
    const wrapper = mountToolbar()
    expect(wrapper.find('[data-test="mode-segment"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="palette-select"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="scale-segment"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="filter-min"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="filter-max"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="opacity-slider"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="lighting-toggle"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.get('[data-test="gradient-opacity-toggle"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('[data-test="bounding-box-toggle"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="reset-view"]').exists()).toBe(true)
  })

  it('log_available=false 时对数选项禁用且提示，不得隐藏', () => {
    const wrapper = mountToolbar(makeState(), makeProfile({ log_available: false }))
    const logOption = wrapper.get('[data-test="log-scale"]')
    expect(logOption.classes()).toContain('is-disabled')
  })

  it('色带选择器显示真实 swatch', async () => {
    const wrapper = mountToolbar()
    await wrapper.find('[data-test="palette-select"]').trigger('click')
    const swatches = document.querySelectorAll('[data-test^="palette-swatch-"]')
    expect(swatches.length).toBeGreaterThanOrEqual(5)
    const first = (swatches[0] as HTMLElement).getAttribute('style') ?? ''
    expect(first).toContain(PALETTES['native-spectrum'][0])
  })

  it('修改色带/标度发射完整克隆状态且 revision 不变（面板负责递增）', async () => {
    const wrapper = mountToolbar()
    // 通过 ElSelect 的 update:modelValue 驱动（下拉 teleport 在并行用例间不稳定；
    // swatch 视觉已由独立用例覆盖）
    const select = wrapper.findComponent({ name: 'ElSelect' })
    ;(select.vm as unknown as { $emit: (e: string, v: string) => void }).$emit(
      'update:modelValue',
      'turbo',
    )
    await flushPromises()
    const emitted = wrapper.emitted('update:modelValue')
    expect(emitted).toBeTruthy()
    const next = emitted![0][0] as RenderStateV2
    expect(next.revision).toBe(1)
    expect(next.colorTransferFunction[0].color).toBe(PALETTES.turbo[0])
    expect(next.mode).toBe('volume')
    expect(next).not.toBe(makeState())
  })

  it('受控 palette/scale 优先于 profile 默认；切换同步发射 update:palette/update:scale', async () => {
    // Task 11：面板把色带/标度提升为受控状态（与剖面热力图共享同一份选择）
    const wrapper = mount(VolumeRenderToolbar, {
      props: {
        modelValue: makeState(),
        profile: makeProfile({ default_palette: 'viridis', default_scale: 'linear' }),
        palette: 'turbo',
        scale: 'log',
        enabled: true,
        'onUpdate:modelValue': () => {},
      },
      global: { plugins: [ElementPlus] },
      attachTo: document.body,
    })
    // 受控值优先于 profile 默认（turbo 而非 viridis）
    const select = wrapper.findComponent({ name: 'ElSelect' })
    expect(select.props('modelValue')).toBe('turbo')

    ;(select.vm as unknown as { $emit: (e: string, v: string) => void }).$emit(
      'update:modelValue',
      'coolwarm',
    )
    await flushPromises()
    expect(wrapper.emitted('update:palette')![0][0]).toBe('coolwarm')
    // stops 用受控 log 标度重算（几何间隔），与 3D/剖面热力图一致
    const next = wrapper.emitted('update:modelValue')![0][0] as RenderStateV2
    expect(next.colorTransferFunction[0].color).toBe(PALETTES.coolwarm[0])
    expect(next.colorTransferFunction[2].value).toBeCloseTo(Math.sqrt(1000))

    await wrapper.find('[data-test="linear-scale"] input').setValue(true)
    expect(wrapper.emitted('update:scale')![0][0]).toBe('linear')
  })

  it('无受控 palette/scale 时回退 profile 默认（兼容旧用法）', () => {
    const wrapper = mountToolbar(makeState(), makeProfile({ default_palette: 'turbo' }))
    const select = wrapper.findComponent({ name: 'ElSelect' })
    expect(select.props('modelValue')).toBe('turbo')
  })

  it('切换对数标度重算色带节点（原始值域不变）', async () => {
    const wrapper = mountToolbar()
    await wrapper.find('[data-test="log-scale"] input').setValue(true)
    const emitted = wrapper.emitted('update:modelValue')
    expect(emitted).toBeTruthy()
    const next = emitted![0][0] as RenderStateV2
    expect(next.filter).toEqual({ min: 1, max: 1000 })
    expect(next.colorTransferFunction[2].value).toBeCloseTo(Math.sqrt(1000))
  })

  it('光照/渐变/包围盒开关发射完整状态', async () => {
    const wrapper = mountToolbar()
    await wrapper.find('[data-test="lighting-toggle"] input').setValue(false)
    let next = wrapper.emitted('update:modelValue')![0][0] as RenderStateV2
    expect(next.lighting).toBe(false)
    await wrapper.find('[data-test="gradient-opacity-toggle"] input').setValue(false)
    next = wrapper.emitted('update:modelValue')![1][0] as RenderStateV2
    expect(next.gradientOpacity).toBe(false)
    await wrapper.find('[data-test="bounding-box-toggle"] input').setValue(false)
    next = wrapper.emitted('update:modelValue')![2][0] as RenderStateV2
    expect(next.boundingBox).toBe(false)
  })

  it('滤波 min == max 是退化区间：不发射且不抛异常（buildColorStops 拒绝空值域）', async () => {
    const wrapper = mountToolbar()
    await wrapper.find('[data-test="filter-min"]').setValue('42')
    await wrapper.find('[data-test="filter-max"]').setValue('42')
    await wrapper.find('[data-test="filter-apply"]').trigger('click')
    await flushPromises()
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })

  it('滤波上下限合法时发射；非法时不发射且不报错打断', async () => {
    const wrapper = mountToolbar()
    await wrapper.find('[data-test="filter-min"]').setValue('20')
    await wrapper.find('[data-test="filter-apply"]').trigger('click')
    let emitted = wrapper.emitted('update:modelValue')
    expect(emitted).toBeTruthy()
    expect((emitted![0][0] as RenderStateV2).filter.min).toBe(20)

    await wrapper.find('[data-test="filter-max"]').setValue('10')
    await wrapper.find('[data-test="filter-apply"]').trigger('click')
    emitted = wrapper.emitted('update:modelValue')
    expect(emitted).toHaveLength(1) // min > max 被拒绝，不再发射
  })

  it('重置视角只发 reset-view 事件，不改渲染状态', async () => {
    const wrapper = mountToolbar()
    await wrapper.find('[data-test="reset-view"]').trigger('click')
    expect(wrapper.emitted('reset-view')).toHaveLength(1)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })

  it('enabled=false 时全部控件禁用', () => {
    const wrapper = mountToolbar(makeState(), makeProfile(), false)
    for (const testId of ['lighting-toggle', 'gradient-opacity-toggle', 'bounding-box-toggle']) {
      expect(wrapper.get(`[data-test="${testId}"]`).classes()).toContain('is-disabled')
    }
    const slider = wrapper.findComponent({ name: 'ElSlider' })
    expect(slider.props('disabled')).toBe(true)
  })
})
