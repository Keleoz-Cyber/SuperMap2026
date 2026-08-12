import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import EChartBox from '../EChartBox.vue'

const resize = vi.fn()
const dispose = vi.fn()
const observe = vi.fn()
const disconnect = vi.fn()
let resizeCallback: ResizeObserverCallback

vi.mock('echarts/core', () => ({
  init: vi.fn(() => ({ setOption: vi.fn(), resize, dispose })),
  use: vi.fn(),
}))
vi.mock('echarts/charts', () => ({ BarChart: {}, LineChart: {}, PieChart: {} }))
vi.mock('echarts/components', () => ({
  GridComponent: {},
  LegendComponent: {},
  TooltipComponent: {},
}))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))

describe('EChartBox responsive lifecycle', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal(
      'ResizeObserver',
      class {
        constructor(callback: ResizeObserverCallback) {
          resizeCallback = callback
        }
        observe = observe
        disconnect = disconnect
      },
    )
  })

  afterEach(() => vi.unstubAllGlobals())

  it('resizes with its container and disconnects the observer on unmount', async () => {
    const wrapper = mount(EChartBox, { props: { option: {} }, attachTo: document.body })
    expect(observe).toHaveBeenCalledWith(wrapper.element)
    resizeCallback([], {} as ResizeObserver)
    await Promise.resolve()
    expect(resize).toHaveBeenCalled()
    wrapper.unmount()
    expect(disconnect).toHaveBeenCalledTimes(1)
    expect(dispose).toHaveBeenCalledTimes(1)
  })
})
