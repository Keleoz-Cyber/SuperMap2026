import { describe, expect, it } from 'vitest'
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
