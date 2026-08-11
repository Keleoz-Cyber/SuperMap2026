import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import PageContextHeader from '../PageContextHeader.vue'

async function mountHeader() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: { template: '<div />' } }],
  })
  await router.push('/')
  await router.isReady()
  return mount(PageContextHeader, {
    props: { title: '模型比较', subtitle: '同一验证口径下比较候选成果' },
    slots: { actions: '<button>导出</button>' },
    global: { plugins: [router] },
  })
}

describe('PageContextHeader', () => {
  it('provides one page title, readable context and a dedicated action area', async () => {
    const wrapper = await mountHeader()
    expect(wrapper.findAll('h1')).toHaveLength(1)
    expect(wrapper.get('h1').text()).toBe('模型比较')
    expect(wrapper.text()).toContain('同一验证口径下比较候选成果')
    expect(wrapper.get('.page-context__actions').text()).toContain('导出')
  })
})
