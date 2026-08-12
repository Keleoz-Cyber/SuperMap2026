import { describe, expect, it } from 'vitest'
import { createAnalysisSelectionController } from '../useAnalysisSelection'

// v0.9.0 Task 12：分析选择控制器合同。上下文切换清空旧选择；
// 身份不匹配/非法区间一律拒绝；控制器不存服务端数据。

describe('useAnalysisSelection', () => {
  it('setContext clears stale selection when dataset/result changes', () => {
    const selection = createAnalysisSelectionController()
    selection.setContext({ datasetId: 'd1', resultId: 'r1' })
    selection.select({ axis: 'z', range: [10, 20], dataset_id: 'd1', result_id: 'r1' })
    expect(selection.current.value?.axis).toBe('z')
    selection.setContext({ datasetId: 'd2', resultId: 'r2' })
    expect(selection.current.value).toBeNull()
  })

  it('rejects selections with mismatched identity', () => {
    const selection = createAnalysisSelectionController()
    selection.setContext({ datasetId: 'd1', resultId: 'r1' })
    const ok = selection.select({ axis: 'z', range: [10, 20], dataset_id: 'd2', result_id: 'r1' })
    expect(ok).toBe(false)
    expect(selection.current.value).toBeNull()
    const badResult = selection.select({ axis: 'z', range: [10, 20], dataset_id: 'd1', result_id: 'r9' })
    expect(badResult).toBe(false)
  })

  it('rejects non-finite or inverted ranges', () => {
    const selection = createAnalysisSelectionController()
    selection.setContext({ datasetId: 'd1', resultId: 'r1' })
    expect(
      selection.select({ axis: 'z', range: [20, 10], dataset_id: 'd1', result_id: 'r1' }),
    ).toBe(false)
    expect(
      selection.select({ axis: 'z', range: [Number.NaN, 10], dataset_id: 'd1', result_id: 'r1' }),
    ).toBe(false)
    expect(
      selection.select({ axis: 'z', range: [Infinity, 10], dataset_id: 'd1', result_id: 'r1' }),
    ).toBe(false)
  })

  it('accepts xy bin selections with both ranges', () => {
    const selection = createAnalysisSelectionController()
    selection.setContext({ datasetId: 'd1', resultId: 'r1' })
    const ok = selection.select({
      axis: 'xy',
      x_range: [0, 50],
      y_range: [0, 40],
      dataset_id: 'd1',
      result_id: 'r1',
    })
    expect(ok).toBe(true)
    expect(selection.current.value?.axis).toBe('xy')
  })

  it('toRouteQuery produces a shareable deep-link query', () => {
    const selection = createAnalysisSelectionController()
    selection.setContext({ datasetId: 'd1', resultId: 'r1' })
    selection.select({ axis: 'z', range: [10, 20], dataset_id: 'd1', result_id: 'r1' })
    const query = selection.toRouteQuery()
    expect(query.axis).toBe('z')
    expect(query.range).toBe('10,20')
    expect(query.dataset).toBe('d1')
  })
})
