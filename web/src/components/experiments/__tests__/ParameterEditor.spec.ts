import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ParameterEditor, { type ParameterSubmit } from '../ParameterEditor.vue'
import { MICROSEISMIC_EXPERIMENT_PRESET } from '../searchSpace'

// v0.8.0：DSI-like 离散平滑插值（工程近似，仅 3D）在统一参数编辑器中的暴露合同。
// 允许值与固定项以后端 DSIParameters 合同为唯一事实来源：
// init_power 1.5/2.0/3.0（默认 2.0）、neighbor_connectivity 6/18/26（默认 6）、
// smoothing_strength 0.25/0.5/0.75（默认 0.5）、max_iterations 25/50（默认 25）、
// convergence_tolerance 固定 1e-4、hard_constraints 固定 true（只读展示，不可关闭）。

function mountEditor(props: Record<string, unknown> = {}) {
  return mount(ParameterEditor, {
    props: { dimension: '3d', submitting: false, ...props },
  })
}

function lastSubmit(wrapper: ReturnType<typeof mountEditor>): ParameterSubmit {
  const events = wrapper.emitted('submit')
  expect(events).toBeTruthy()
  return events![events!.length - 1][0] as ParameterSubmit
}

function selectValues(wrapper: ReturnType<typeof mountEditor>, test: string): string[] {
  return wrapper
    .get(`[data-test="${test}"]`)
    .findAll('option')
    .map((o) => (o.element as HTMLOptionElement).value)
}

function selectValue(wrapper: ReturnType<typeof mountEditor>, test: string): string {
  return (wrapper.get(`[data-test="${test}"]`).element as HTMLSelectElement).value
}

describe('ParameterEditor dsi_like（v0.8.0）', () => {
  it('3D 预置下 dsi_like 出现在 IDW/普通 Kriging 旁，并附工程近似免责声明', () => {
    const wrapper = mountEditor()
    expect(wrapper.find('[data-test="algo-idw"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="algo-kriging"]').exists()).toBe(true)
    const dsi = wrapper.get('[data-test="algo-dsi-like"]')
    expect((dsi.element as HTMLInputElement).disabled).toBe(false)
    expect(wrapper.text()).toContain('DSI-like')
    expect(wrapper.get('[data-test="dsi-like-note"]').text()).toContain(
      '基于 IDW 初始场和离散邻域平滑的工程近似方法，不等同于 GOCAD DSI。',
    )
  })

  it('2D 下 dsi_like 禁用且提交不会静默发出 dsi_like', async () => {
    const wrapper = mountEditor({ dimension: '2d' })
    const dsi = wrapper.get('[data-test="algo-dsi-like"]')
    expect((dsi.element as HTMLInputElement).disabled).toBe(true)

    await wrapper.get('[data-test="exp-submit"]').trigger('click')
    expect(lastSubmit(wrapper).algorithm).toBe('idw')
  })

  it('选择 dsi_like：手动参数控件只提供合同允许值并使用合同默认值', async () => {
    const wrapper = mountEditor()
    await wrapper.get('[data-test="algo-dsi-like"]').setValue(true)

    expect(selectValues(wrapper, 'dsi-init-power')).toEqual(['1.5', '2', '3'])
    expect(selectValues(wrapper, 'dsi-connectivity')).toEqual(['6', '18', '26'])
    expect(selectValues(wrapper, 'dsi-smoothing')).toEqual(['0.25', '0.5', '0.75'])
    expect(selectValues(wrapper, 'dsi-iterations')).toEqual(['25', '50'])

    expect(selectValue(wrapper, 'dsi-init-power')).toBe('2')
    expect(selectValue(wrapper, 'dsi-connectivity')).toBe('6')
    expect(selectValue(wrapper, 'dsi-smoothing')).toBe('0.5')
    expect(selectValue(wrapper, 'dsi-iterations')).toBe('25')
  })

  it('固定 hard_constraints / convergence_tolerance 只读展示，不提供关闭或编辑入口', async () => {
    const wrapper = mountEditor()
    await wrapper.get('[data-test="algo-dsi-like"]').setValue(true)

    const hard = wrapper.get('[data-test="dsi-hard-constraints"]')
    expect(hard.text()).toContain('始终开启')
    expect(hard.find('input').exists()).toBe(false)

    const tolerance = wrapper.get('[data-test="dsi-convergence-tolerance"]')
    expect(tolerance.text()).toContain('1e-4')
    expect(tolerance.find('input').exists()).toBe(false)
  })

  it('dsi_like 手动提交：载荷携带所选允许值与两项固定参数', async () => {
    const wrapper = mountEditor()
    await wrapper.get('[data-test="algo-dsi-like"]').setValue(true)
    await wrapper.get('[data-test="dsi-init-power"]').setValue('3')
    await wrapper.get('[data-test="dsi-connectivity"]').setValue('26')
    await wrapper.get('[data-test="dsi-smoothing"]').setValue('0.75')
    await wrapper.get('[data-test="dsi-iterations"]').setValue('50')
    await wrapper.get('[data-test="exp-submit"]').trigger('click')

    const submit = lastSubmit(wrapper)
    expect(submit.algorithm).toBe('dsi_like')
    expect(submit.search_mode).toBe('manual')
    expect(submit.parameters).toEqual({
      init_power: 3,
      neighbor_connectivity: 26,
      smoothing_strength: 0.75,
      max_iterations: 50,
      convergence_tolerance: 1e-4,
      hard_constraints: true,
    })
  })

  it('切换到其他算法再切回时，dsi_like 参数重置为合同默认值', async () => {
    const wrapper = mountEditor()
    await wrapper.get('[data-test="algo-dsi-like"]').setValue(true)
    await wrapper.get('[data-test="dsi-connectivity"]').setValue('26')
    await wrapper.get('[data-test="dsi-iterations"]').setValue('50')

    await wrapper.get('[data-test="algo-idw"]').setValue(true)
    await wrapper.get('[data-test="algo-dsi-like"]').setValue(true)

    expect(selectValue(wrapper, 'dsi-connectivity')).toBe('6')
    expect(selectValue(wrapper, 'dsi-iterations')).toBe('25')
    expect(selectValue(wrapper, 'dsi-init-power')).toBe('2')
    expect(selectValue(wrapper, 'dsi-smoothing')).toBe('0.5')
  })

  it('dsi_like 网格模式：离散候选复选、组合计数与载荷列表正确', async () => {
    const wrapper = mountEditor()
    await wrapper.get('[data-test="algo-dsi-like"]').setValue(true)
    await wrapper.get('[data-test="mode-grid"]').setValue(true)

    // 默认每个参数仅勾选合同默认值 → 1 组合
    expect(wrapper.get('[data-test="count-preview"]').text()).toContain('1 个候选组合')

    await wrapper.get('[data-test="grid-dsi-connectivity-18"]').setValue(true)
    expect(wrapper.get('[data-test="count-preview"]').text()).toContain('2 个候选组合')

    await wrapper.get('[data-test="exp-submit"]').trigger('click')
    const submit = lastSubmit(wrapper)
    expect(submit.algorithm).toBe('dsi_like')
    expect(submit.search_mode).toBe('grid')
    expect(submit.parameters).toEqual({
      init_power: [2],
      neighbor_connectivity: [6, 18],
      smoothing_strength: [0.5],
      max_iterations: [25],
      convergence_tolerance: [1e-4],
      hard_constraints: [true],
    })
  })

  it('领域预设数据集选择 dsi_like 时不出现 z_scale 控件，也不随载荷提交', async () => {
    const wrapper = mountEditor({ preset: MICROSEISMIC_EXPERIMENT_PRESET })
    expect(wrapper.find('[data-test="z-scale-manual"]').exists()).toBe(true)

    await wrapper.get('[data-test="algo-dsi-like"]').setValue(true)
    expect(wrapper.find('[data-test="z-scale-manual"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="z-scale-hint"]').exists()).toBe(false)

    await wrapper.get('[data-test="exp-submit"]').trigger('click')
    expect(lastSubmit(wrapper).parameters).not.toHaveProperty('z_scale')
  })
})
