import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'
import type { RunRecord, RunStatus } from '../../../api/types'
import RunProgress from '../RunProgress.vue'

const T = '2026-08-12T00:00:00Z'

function runOf(status: RunStatus, errorCode: string | null = null): RunRecord {
  return {
    id: '3a7ad2fd-a3a7-4ef8-847b-608f561abd81',
    experiment_id: 'exp-1',
    status,
    error_code: errorCode,
    metrics: { completed: 1, total: 1, failed: status === 'failed' ? 1 : 0 },
    retry_of_run_id: null,
    created_at: T,
    updated_at: T,
    started_at: T,
    finished_at: T,
  }
}

describe('RunProgress 产品语言', () => {
  it('主层显示中文运行状态，不暴露状态枚举、运行 UUID 或错误码', () => {
    const wrapper = mount(RunProgress, {
      props: { run: runOf('failed', 'MODEL_EXECUTION_FAILED'), acting: false },
      global: { plugins: [ElementPlus] },
    })

    const primary = wrapper.get('[data-test="run-progress-primary"]').text()
    expect(primary).toContain('运行失败')
    expect(primary).not.toContain('failed')
    expect(primary).not.toContain('3a7ad2fd')
    expect(primary).not.toContain('MODEL_EXECUTION_FAILED')
    expect(wrapper.get('[data-test="run-technical-details"]').text()).toContain('MODEL_EXECUTION_FAILED')
  })

  it('成功运行显示“验证完成”而不是 succeeded', () => {
    const wrapper = mount(RunProgress, {
      props: { run: runOf('succeeded'), acting: false },
      global: { plugins: [ElementPlus] },
    })

    expect(wrapper.get('[data-test="run-progress-primary"]').text()).toContain('验证完成')
    expect(wrapper.get('[data-test="run-progress-primary"]').text()).not.toContain('succeeded')
  })
})
