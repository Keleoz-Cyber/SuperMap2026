import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ElementPlus from 'element-plus'
import SearchSummary from '../SearchSummary.vue'
import CandidateLeaderboard from '../CandidateLeaderboard.vue'
import { MAX_GRID_CANDIDATES, WARN_GRID_CANDIDATES } from '../searchSpace'

// v0.7.0 审查轮文案修正：候选范围必须明确为「本实验本次运行」；
// 组合阈值 30 警告 / 50 阻断保持不变；不引入跨实验排行榜。

describe('候选范围文案', () => {
  it('搜索模式标签使用单组参数/参数网格措辞', () => {
    const manual = mount(SearchSummary, {
      props: {
        params: {
          name: 'x',
          case_id: 'c1',
          algorithm: 'idw',
          dataset_version_id: 'ds1',
          search_mode: 'manual',
          parameters: { power: 2.0 },
          validation: { method: 'spatial_kfold', folds: 5, seed: 1, holdout_fraction: 0.2 },
        },
      },
      global: { plugins: [ElementPlus] },
    })
    expect(manual.text()).toContain('单组参数（1 个候选）')
    expect(manual.text()).not.toContain('手动单组')

    const grid = mount(SearchSummary, {
      props: {
        params: {
          name: 'x',
          case_id: 'c1',
          algorithm: 'idw',
          dataset_version_id: 'ds1',
          search_mode: 'grid',
          parameters: { power: [1.0, 2.0] },
          validation: { method: 'spatial_kfold', folds: 5, seed: 1, holdout_fraction: 0.2 },
        },
      },
      global: { plugins: [ElementPlus] },
    })
    expect(grid.text()).toContain('参数网格（自动组合）')
    expect(grid.text()).not.toContain('有限网格搜索')
  })

  it('排行榜标题明确仅比较本实验本次运行的参数组合', () => {
    const wrapper = mount(CandidateLeaderboard, {
      props: {
        candidates: [],
        publicMetrics: {
          common_valid_count: 10,
          candidate_valid_count: 10,
          candidate_nodata_count: 0,
          total_count: 10,
          coverage: 1,
          mae: 0.1,
          rmse: 0.2,
          r2: 0.9,
          bias: 0,
        },
      },
      global: {
        plugins: [ElementPlus],
        stubs: { RouterLink: { template: '<a><slot /></a>' } },
      },
    })
    expect(wrapper.text()).toContain('本实验候选排行榜')
    expect(wrapper.text()).toContain('仅比较当前实验本次运行的参数组合')
    expect(wrapper.text()).not.toContain('跨实验')
  })

  it('组合阈值保持 30 警告 / 50 阻断', () => {
    expect(WARN_GRID_CANDIDATES).toBe(30)
    expect(MAX_GRID_CANDIDATES).toBe(50)
  })
})
