import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ParameterEditor, { type ParameterSubmit } from '../ParameterEditor.vue'
import { MICROSEISMIC_EXPERIMENT_PRESET } from '../searchSpace'
import type { MLCapability } from '../../../api/types'

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

const SUPPORTED_ML: MLCapability = {
  dataset_id: 'ds-ml',
  level: 'supported',
  valid_sample_count: 240,
  spatial_group_count: 40,
  available_algorithms: ['random_forest_spatial', 'kriging_rf_residual'],
  confirmation_required: false,
  reason_code: null,
  message: '样本量和独立空间分组满足机器学习空间验证要求。',
  validation_requirement: 'spatial_cross_validation',
  dispersion_semantics: 'model_dispersion_reference',
}

describe('ParameterEditor 用户决策层', () => {
  it('用可比较的算法说明展示适用场景、成本和限制', () => {
    const wrapper = mountEditor()
    const choices = wrapper
      .get('[data-test="traditional-algorithm-group"]')
      .findAll('[data-test^="algorithm-choice-"]')
    expect(choices).toHaveLength(3)
    expect(wrapper.get('[data-test="algorithm-choice-idw"]').text()).toContain('快速基线')
    expect(wrapper.get('[data-test="algorithm-choice-ordinary_kriging"]').text()).toContain('空间相关性')
    expect(wrapper.get('[data-test="algorithm-choice-dsi_like"]').text()).toContain('工程近似')
    expect(wrapper.get('[data-test="advanced-experiment-settings"]').text()).toContain('空间验证')
  })

  it('默认使用单组推荐配置，并明确参数网格会产生多个候选', () => {
    const wrapper = mountEditor()
    expect(wrapper.get('[data-test="mode-manual-label"]').text()).toContain('推荐配置')
    expect(wrapper.get('[data-test="mode-grid-label"]').text()).toContain('自动组合')
    expect(wrapper.get('[data-test="count-preview"]').text()).toContain('1 个候选组合')
  })

  it('提交期间显示旋转状态和明确阶段提示', () => {
    const wrapper = mountEditor({ submitting: true })

    expect(wrapper.get('[data-test="exp-submit-spinner"]')).toBeTruthy()
    expect(wrapper.get('[data-test="exp-submit-status"]').attributes('aria-live')).toBe('polite')
    expect(wrapper.get('[data-test="exp-submit-status"]').text()).toContain('正在创建实验并提交运行任务')
  })
})

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
    expect(wrapper.text()).not.toContain('init_power')
    expect(wrapper.text()).not.toContain('neighbor_connectivity')
    expect(wrapper.text()).not.toContain('smoothing_strength')
    expect(wrapper.text()).not.toContain('max_iterations')
    expect(wrapper.text()).not.toContain('hard_constraints')
  })

  it('主操作层不显示后端参数键，但提交载荷仍保留合同字段', async () => {
    const wrapper = mountEditor({ preset: MICROSEISMIC_EXPERIMENT_PRESET })
    await wrapper.get('[data-test="algo-kriging"]').setValue(true)
    await wrapper.get('[data-test="kriging-mode"]').setValue('manual')

    const primary = wrapper.get('[data-test="param-editor"]').text()
    expect(primary).not.toContain('nugget/sill/range')
    expect(primary).not.toContain('z_scale')

    await wrapper.get('[data-test="algo-dsi-like"]').setValue(true)
    await wrapper.get('[data-test="mode-grid"]').setValue(true)
    expect(wrapper.get('[data-test="param-editor"]').text()).not.toContain('convergence_tolerance')
    expect(wrapper.get('[data-test="param-editor"]').text()).not.toContain('hard_constraints')
    await wrapper.get('[data-test="exp-submit"]').trigger('click')
    expect(lastSubmit(wrapper).parameters).toMatchObject({
      convergence_tolerance: [1e-4],
      hard_constraints: [true],
    })
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

describe('ParameterEditor 机器学习空间预测', () => {
  it('按传统建模与机器学习预测分组展示五种算法', () => {
    const wrapper = mountEditor({ mlCapability: SUPPORTED_ML })

    expect(wrapper.get('[data-test="traditional-algorithm-group"]').text()).toContain('传统空间建模')
    expect(wrapper.get('[data-test="ml-algorithm-group"]').text()).toContain('机器学习预测')
    expect(wrapper.findAll('[data-test^="algorithm-choice-"]')).toHaveLength(5)
    expect(wrapper.get('[data-test="algorithm-choice-random_forest_spatial"]').text()).toContain('模型离散度')
    expect(wrapper.get('[data-test="algorithm-choice-kriging_rf_residual"]').text()).toContain('折外残差')
  })

  it('supported 数据允许两种 ML 算法并提交确定性 RF 默认参数', async () => {
    const wrapper = mountEditor({ mlCapability: SUPPORTED_ML })

    await wrapper.get('[data-test="algo-random-forest"]').setValue(true)
    expect(wrapper.get('[data-test="ml-capability-notice"]').text()).toContain('240')
    expect(wrapper.get('[data-test="ml-capability-notice"]').text()).toContain('40')
    await wrapper.get('[data-test="exp-submit"]').trigger('click')

    const submit = lastSubmit(wrapper)
    expect(submit.algorithm).toBe('random_forest_spatial')
    expect(submit.parameters).toEqual({
      n_estimators: 160,
      max_depth: 18,
      min_samples_leaf: 2,
      max_features: 0.8,
      random_state: 20260813,
    })
    expect(submit.ml_experimental_confirmed).toBe(false)
  })

  it('experimental 数据只允许 RF，且确认前不能提交', async () => {
    const experimental: MLCapability = {
      ...SUPPORTED_ML,
      level: 'experimental',
      valid_sample_count: 100,
      spatial_group_count: 20,
      available_algorithms: ['random_forest_spatial'],
      confirmation_required: true,
      reason_code: 'ML_EXPERIMENTAL_DATASET',
      message: '样本规模有限，仅建议将随机森林作为实验性对照。',
    }
    const wrapper = mountEditor({ mlCapability: experimental })

    expect((wrapper.get('[data-test="algo-random-forest"]').element as HTMLInputElement).disabled).toBe(false)
    expect((wrapper.get('[data-test="algo-kriging-rf-residual"]').element as HTMLInputElement).disabled).toBe(true)
    await wrapper.get('[data-test="algo-random-forest"]').setValue(true)
    expect((wrapper.get('[data-test="exp-submit"]').element as HTMLButtonElement).disabled).toBe(true)
    expect(wrapper.get('[data-test="ml-experimental-confirmation"]').text()).toContain('实验性对照')

    await wrapper.get('[data-test="ml-experimental-confirmation-input"]').setValue(true)
    expect((wrapper.get('[data-test="exp-submit"]').element as HTMLButtonElement).disabled).toBe(false)
    await wrapper.get('[data-test="exp-submit"]').trigger('click')
    expect(lastSubmit(wrapper).ml_experimental_confirmed).toBe(true)
  })

  it('not_recommended 数据禁用 ML 并显示具体样本原因', () => {
    const capability: MLCapability = {
      ...SUPPORTED_ML,
      level: 'not_recommended',
      valid_sample_count: 58,
      spatial_group_count: 58,
      available_algorithms: [],
      confirmation_required: false,
      reason_code: 'ML_DATASET_TOO_SMALL',
      message: '样本量或独立空间分组不足，不建议运行机器学习空间预测。',
    }
    const wrapper = mountEditor({ mlCapability: capability })

    expect((wrapper.get('[data-test="algo-random-forest"]').element as HTMLInputElement).disabled).toBe(true)
    expect((wrapper.get('[data-test="algo-kriging-rf-residual"]').element as HTMLInputElement).disabled).toBe(true)
    expect(wrapper.get('[data-test="ml-capability-notice"]').text()).toContain('58 个有效样本')
    expect(wrapper.get('[data-test="ml-capability-notice"]').text()).toContain('不建议')
  })

  it('残差校正提交嵌套克里金与随机森林参数', async () => {
    const wrapper = mountEditor({ mlCapability: SUPPORTED_ML })
    await wrapper.get('[data-test="algo-kriging-rf-residual"]').setValue(true)
    await wrapper.get('[data-test="exp-submit"]').trigger('click')

    const submit = lastSubmit(wrapper)
    expect(submit.algorithm).toBe('kriging_rf_residual')
    expect(submit.parameters).toMatchObject({
      kriging: { variogram_model: 'spherical', neighbor_count: 24 },
      random_forest: { n_estimators: 160, max_depth: 18, random_state: 20260813 },
      inner_folds: 3,
    })
  })
})
