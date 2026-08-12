import { describe, expect, it } from 'vitest'
import {
  algorithmLabel,
  coordinateLabel,
  parameterLabel,
  parameterSummary,
  propertyLabel,
  unitLabel,
} from '../modelingLabels'

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

describe('coordinateLabel', () => {
  it('local_linear uses user-facing Chinese wording', () => {
    expect(coordinateLabel('local_linear')).toBe('局部线性米制坐标')
  })
})

describe('propertyLabel', () => {
  it('maps built-in property keys to user-facing names', () => {
    expect(propertyLabel('RHO')).toBe('电阻率')
    expect(propertyLabel('Vx')).toBe('微震速度')
    expect(propertyLabel('CH4_content')).toBe('瓦斯含量')
    expect(propertyLabel('density')).toBe('density')
  })
})

describe('unitLabel', () => {
  it('maps internal unit keys to scientific notation', () => {
    expect(unitLabel('ohm_m')).toBe('Ω·m')
    expect(unitLabel('km/s')).toBe('km/s')
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

  it('DSI-like internal parameter keys map to user-facing labels', () => {
    expect(parameterLabel('init_power')).toBe('初始场幂次')
    expect(parameterLabel('neighbor_connectivity')).toBe('邻域连接数')
    expect(parameterLabel('smoothing_strength')).toBe('平滑强度')
    expect(parameterLabel('max_iterations')).toBe('最大迭代次数')
    expect(parameterLabel('convergence_tolerance')).toBe('收敛容差')
    expect(parameterLabel('hard_constraints')).toBe('观测点约束')
  })
})
