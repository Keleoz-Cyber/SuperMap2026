import { describe, expect, it } from 'vitest'
import { algorithmLabel, parameterSummary } from '../modelingLabels'

describe('algorithmLabel', () => {
  it('idw -> IDW（反距离加权）', () => {
    expect(algorithmLabel('idw')).toBe('IDW（反距离加权）')
  })

  it('ordinary_kriging -> 普通克里金', () => {
    expect(algorithmLabel('ordinary_kriging')).toBe('普通克里金')
  })

  it('unknown algorithm returns safe truncated string', () => {
    expect(algorithmLabel('some_unknown_algorithm')).toBe('some_unknown_algorithm')
  })

  it('very long unknown algorithm is truncated to 64 chars', () => {
    const long = 'x'.repeat(100)
    expect(algorithmLabel(long)).toHaveLength(64)
  })
})

describe('parameterSummary', () => {
  it('Kriging known params produce readable labels', () => {
    expect(
      parameterSummary('ordinary_kriging', { neighbor_count: 24, variogram_model: 'spherical' }),
    ).toEqual(['邻域点数 24', '变异函数 球状'])
  })

  it('IDW known params produce readable labels', () => {
    expect(parameterSummary('idw', { power: 2, neighbor_count: 8 })).toEqual([
      '邻域点数 8',
      '幂参数 2',
    ])
  })

  it('variogram model exponential maps to 指数', () => {
    expect(
      parameterSummary('ordinary_kriging', { variogram_model: 'exponential' }),
    ).toEqual(['变异函数 指数'])
  })

  it('unknown params fall back to sorted key value pairs (max 5)', () => {
    const params = { zzz: 1, aaa: 'x', mmm: true }
    expect(parameterSummary('unknown', params)).toEqual(['aaa x', 'mmm 是', 'zzz 1'])
  })

  it('empty params returns empty array', () => {
    expect(parameterSummary('idw', {})).toEqual([])
  })

  it('formats numbers with zh-CN locale', () => {
    expect(parameterSummary('idw', { power: 2.5 })).toEqual(['幂参数 2.5'])
  })
})
