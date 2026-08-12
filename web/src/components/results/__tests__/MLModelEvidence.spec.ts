import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { MLResultEvidence } from '../../../api/types'
import MLModelEvidence from '../MLModelEvidence.vue'

function evidence(overrides: Partial<MLResultEvidence> = {}): MLResultEvidence {
  return {
    algorithm: 'kriging_rf_residual',
    comparison_status: 'comparable',
    comparison_reason_code: null,
    baseline: {
      result_id: 'kriging-result-1',
      algorithm: 'ordinary_kriging',
      rmse: 6.5,
      mae: 4.2,
      r2: 0.91,
      bias: 0.08,
      common_valid_count: 1722,
      fold_assignments_sha256: 'a'.repeat(64),
    },
    metric_change: {
      rmse_absolute: -0.3,
      rmse_percent: -4.615,
      mae_absolute: -0.1,
      mae_percent: -2.381,
    },
    improved_over_kriging: true,
    available_fields: ['prediction', 'model_dispersion', 'kriging_baseline', 'residual_correction'],
    dispersion_semantics: 'model_dispersion_reference',
    limitations: ['模型离散度仅作参考，不是严格置信区间。'],
    technical_details: {
      feature_version: 'spatial_features.v1',
      sklearn_version: '1.7.2',
      validation_method: 'spatial_kfold',
      common_valid_count: 1722,
      fold_assignments_sha256: 'a'.repeat(64),
    },
    ...overrides,
  }
}

describe('MLModelEvidence', () => {
  it('突出相对普通克里金的真实改善和公共有效集口径', () => {
    const wrapper = mount(MLModelEvidence, { props: { evidence: evidence() } })
    expect(wrapper.get('[data-test="ml-evidence-conclusion"]').text()).toContain('优于普通克里金')
    expect(wrapper.text()).toContain('RMSE 降低 4.6%')
    expect(wrapper.text()).toContain('公共有效点 1,722')
    expect(wrapper.text()).toContain('模型离散度仅作参考')
    const summary = wrapper.get('[data-test="ml-evidence-summary"]')
    expect(summary.text()).not.toContain('sklearn')
    expect(summary.text()).not.toContain('aaaaaaaa')
  })

  it('没有改善时如实说明，不使用最佳或提升等误导措辞', () => {
    const wrapper = mount(MLModelEvidence, {
      props: {
        evidence: evidence({
          improved_over_kriging: false,
          metric_change: {
            rmse_absolute: 0.2,
            rmse_percent: 3.077,
            mae_absolute: 0.1,
            mae_percent: 2.381,
          },
        }),
      },
    })
    const conclusion = wrapper.get('[data-test="ml-evidence-conclusion"]').text()
    expect(conclusion).toContain('未优于普通克里金')
    expect(wrapper.text()).toContain('RMSE 增加 3.1%')
    expect(wrapper.text()).not.toContain('最佳')
  })

  it('不可比时解释原因；瓦斯小样本限制直接呈现', () => {
    const wrapper = mount(MLModelEvidence, {
      props: {
        evidence: evidence({
          comparison_status: 'unavailable',
          comparison_reason_code: 'ML_KRIGING_BASELINE_NOT_COMPARABLE',
          baseline: null,
          metric_change: null,
          improved_over_kriging: null,
          limitations: ['瓦斯案例仅 58 个有效样本，机器学习结果不建议作为主模型。'],
        }),
      },
    })
    expect(wrapper.get('[data-test="ml-evidence-conclusion"]').text()).toContain('暂不能与普通克里金直接比较')
    expect(wrapper.text()).toContain('相同数据版本、验证规则和公共有效集')
    expect(wrapper.text()).toContain('瓦斯案例仅 58 个有效样本')
  })

  it('技术身份只在折叠详情内出现', async () => {
    const wrapper = mount(MLModelEvidence, { props: { evidence: evidence() } })
    const details = wrapper.get('[data-test="ml-evidence-technical"]')
    expect(details.attributes('open')).toBeUndefined()
    expect(details.text()).toContain('scikit-learn 1.7.2')
    expect(details.text()).toContain('aaaaaaaaaaaa')
  })
})
