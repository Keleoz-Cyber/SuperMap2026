import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AsyncState from '../AsyncState.vue'

describe('AsyncState', () => {
  it.each(['loading', 'empty', 'error', 'offline', 'degraded', 'nodata'] as const)(
    'renders a labelled %s state',
    (kind) => {
      const wrapper = mount(AsyncState, {
        props: { kind, title: '状态标题', impact: '三维暂时不能查看', nextAction: '刷新页面后再试' },
      })
      expect(wrapper.get('[role="status"]').attributes('data-state')).toBe(kind)
      expect(wrapper.text()).toContain('三维暂时不能查看')
      expect(wrapper.text()).toContain('刷新页面后再试')
      expect(wrapper.text()).not.toContain('受影响能力')
      expect(wrapper.text()).not.toContain('下一步：')
    },
  )

  it('loading never invents impact or next-action text', () => {
    const wrapper = mount(AsyncState, { props: { kind: 'loading', title: '加载中' } })
    expect(wrapper.text()).toContain('加载中')
    expect(wrapper.text()).not.toContain('受影响')
    expect(wrapper.text()).not.toContain('下一步')
  })

  it('error surfaces the typed error code when provided', () => {
    const wrapper = mount(AsyncState, {
      props: {
        kind: 'error',
        title: '加载失败',
        impact: '全部能力',
        nextAction: '重试',
        errorCode: 'DATASET_NOT_FOUND',
      },
    })
    expect(wrapper.text()).toContain('DATASET_NOT_FOUND')
  })

  it('exposes the action slot for retry/navigation commands', () => {
    const wrapper = mount(AsyncState, {
      props: { kind: 'offline', title: '服务离线', impact: '三维', nextAction: '稍后重试' },
      slots: { action: '<button data-test="retry">重试</button>' },
    })
    expect(wrapper.get('[data-test="retry"]').text()).toBe('重试')
  })
})
