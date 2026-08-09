import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { ComparisonCandidateSummary } from '../../../api/types'
import ParameterDiffTable from '../ParameterDiffTable.vue'

function candidateOf(id: string, parameters: Record<string, unknown>): ComparisonCandidateSummary {
  return {
    candidate_result_id: id,
    experiment_id: 'exp-1',
    run_id: 'run-1',
    algorithm: 'ordinary_kriging',
    parameters,
    selectable: true,
    metrics: { rmse: 1, mae: 1, r2: 0.9, bias: 0 },
    result_url: `/results/${id}`,
    configuration_fingerprint: `fp-${id}`,
  }
}

describe('ParameterDiffTable', () => {
  it('highlights only parameters that actually differ', () => {
    const wrapper = mount(ParameterDiffTable, {
      props: {
        candidates: [
          candidateOf('r1', { variogram_model: 'exponential', neighbor_count: 24, z_scale: 1 }),
          candidateOf('r2', { variogram_model: 'spherical', neighbor_count: 24, z_scale: 1 }),
        ],
      },
    })
    const rows = wrapper.findAll('[data-test="param-diff-row"]')
    expect(rows.length).toBe(3)
    const diffRow = rows.find((r) => r.text().includes('variogram_model'))
    const sameRow = rows.find((r) => r.text().includes('neighbor_count'))
    expect(diffRow?.attributes('data-differs')).toBe('true')
    expect(sameRow?.attributes('data-differs')).toBe('false')
  })
})
