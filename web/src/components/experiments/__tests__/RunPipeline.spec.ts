import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import RunPipeline from '../RunPipeline.vue'
import { stageFor } from '../RunPipeline.vue'

// v0.9.0 Task 8：真实运行流水线。阶段只从持久化状态与粗进度推导；
// 粗进度推导的阶段必须标注「阶段估计」，绝不编造后端未提供的子阶段计时。

describe('stageFor', () => {
  it('maps persisted statuses only', () => {
    expect(stageFor({ status: 'queued' })).toBe('queued')
    expect(stageFor({ status: 'running', progress: 0.2 })).toBe('validation')
    expect(stageFor({ status: 'running', progress: 0.6 })).toBe('interpolation')
    expect(stageFor({ status: 'succeeded' })).toBe('complete')
    expect(stageFor({ status: 'failed' })).toBe('failed')
  })

  it('running late progress maps to evaluation; canceled/interrupted keep identity', () => {
    expect(stageFor({ status: 'running', progress: 0.9 })).toBe('evaluation')
    expect(stageFor({ status: 'canceled' })).toBe('canceled')
    expect(stageFor({ status: 'interrupted' })).toBe('interrupted')
  })
})

describe('RunPipeline 产品语言', () => {
  it('失败主层显示运行失败，错误码收入技术详情', () => {
    const wrapper = mount(RunPipeline, {
      props: {
        run: {
          id: 'run-1',
          experiment_id: 'exp-1',
          status: 'failed',
          error_code: 'MODEL_EXECUTION_FAILED',
          metrics: { completed: 0, total: 1, failed: 1 },
          retry_of_run_id: null,
          created_at: '2026-08-12T00:00:00Z',
          updated_at: '2026-08-12T00:00:00Z',
          started_at: null,
          finished_at: null,
        },
      },
    })

    expect(wrapper.get('[data-test="pipeline-error"]').text()).toContain('运行失败')
    expect(wrapper.get('[data-test="pipeline-error"]').text()).not.toContain('MODEL_EXECUTION_FAILED')
    expect(wrapper.get('[data-test="pipeline-technical-details"]').text()).toContain('MODEL_EXECUTION_FAILED')
  })
})
