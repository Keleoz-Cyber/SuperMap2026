import { mount, type VueWrapper } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { CandidateRecord } from '../../../api/types'
import CandidateLeaderboard from '../CandidateLeaderboard.vue'

function candidate(id: string, parameters: Record<string, unknown>): CandidateRecord {
  return {
    id,
    fingerprint: `fp-${id}`,
    status: 'succeeded',
    parameters,
    metrics: {},
    error: null,
  }
}

function mountBoard(candidates: CandidateRecord[], algorithm = 'ordinary_kriging'): VueWrapper {
  return mount(CandidateLeaderboard, {
    props: { candidates, publicMetrics: {}, algorithm },
    global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
}

function paramsText(wrapper: VueWrapper): string {
  return wrapper.find('[data-test="candidate-row"] td.mono').text()
}

describe('CandidateLeaderboard 参数列格式化', () => {
  it('显示当前实验的中文算法名，机器学习算法不泄漏内部枚举值', () => {
    const rf = mountBoard([candidate('r1', { n_estimators: 200 })], 'random_forest_spatial')
    expect(rf.get('[data-test="candidate-algorithm"]').text()).toBe('随机森林空间预测')
    expect(rf.text()).not.toContain('random_forest_spatial')
    rf.unmount()

    const residual = mountBoard(
      [candidate('r2', { rf: { n_estimators: 200 } })],
      'kriging_rf_residual',
    )
    expect(residual.get('[data-test="candidate-algorithm"]').text()).toBe('克里金残差校正')
    expect(residual.text()).not.toContain('kriging_rf_residual')
    residual.unmount()
  })

  it('嵌套专业参数（neighborhood/anisotropy）以紧凑可读形式渲染，绝不出现 [object Object]', () => {
    const wrapper = mountBoard([
      candidate('r1', {
        variogram_model: 'spherical',
        neighborhood: { max_neighbors: 16, radii: [800, 800, 800], azimuth_deg: 0 },
        anisotropy: { ratio: 2.5, enabled: true },
      }),
    ])

    const text = paramsText(wrapper)
    expect(text).not.toContain('[object Object]')
    // 顶层与嵌套键均按字典序输出；数组紧凑逗号分隔
    expect(text).toBe(
      'anisotropy={enabled:true,ratio:2.5} ' +
        'neighborhood={azimuth_deg:0,max_neighbors:16,radii:[800,800,800]} ' +
        'variogram_model=spherical',
    )
    wrapper.unmount()
  })

  it('覆盖 object/array/null/boolean/number 各类型；number 去除浮点噪声长尾', () => {
    const wrapper = mountBoard([
      candidate('r1', {
        nested: { z: 1, a: [1, 2] },
        list: [true, null, 'x'],
        nothing: null,
        flag: false,
        ratio: 0.30000000000000004,
        count: 16,
      }),
    ])

    expect(paramsText(wrapper)).toBe(
      'count=16 flag=false list=[true,null,x] nested={a:[1,2],z:1} nothing=null ratio=0.3',
    )
    wrapper.unmount()
  })

  it('键序确定性：不同键序的同一对象输出完全一致', () => {
    const first = mountBoard([candidate('r1', { b: 1, a: { y: 2, x: 3 } })])
    const second = mountBoard([candidate('r1', { a: { x: 3, y: 2 }, b: 1 })])

    expect(paramsText(first)).toBe(paramsText(second))
    expect(paramsText(first)).toBe('a={x:3,y:2} b=1')
    first.unmount()
    second.unmount()
  })

  it('普通标量参数保持原样渲染（回归）', () => {
    const wrapper = mountBoard([
      candidate('r1', { power: 2, variogram_model: 'spherical', range: 800 }),
    ])

    expect(paramsText(wrapper)).toBe('power=2 range=800 variogram_model=spherical')
    wrapper.unmount()
  })
})
