import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import type { SliceResponse } from '../../../api/types'
import * as client from '../../../api/client'
import SlicePanel from '../../../components/results/SlicePanel.vue'
import { buildHeatmapData, nearestIndex } from '../../../components/results/fieldData'

vi.mock('../../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../api/client')>()
  return { ...actual, fetchResultSlice: vi.fn() }
})

function makeSlice(axis: 'x' | 'y' | 'z', coordinate: number): SliceResponse {
  return {
    result_id: 'r1',
    fixed_axis: axis,
    fixed_coordinate: coordinate,
    axes_names: axis === 'z' ? ['x', 'y'] : axis === 'x' ? ['y', 'z'] : ['x', 'z'],
    axes: [
      [0, 10, 20],
      [100, 110, 120],
    ],
    matrix: [
      [1, null, 3],
      [4, 5, 6],
    ],
    nodata_mask: [
      [false, true, false],
      [false, false, false],
    ],
    value_range: [1, 6],
  }
}

async function mountPanel(dimension: '2d' | '3d', shape: number[]) {
  const wrapper = mount(SlicePanel, {
    props: { resultId: 'r1', dimension, shape },
    global: { plugins: [ElementPlus] },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('SlicePanel', () => {
  it('3D 默认请求 Z 中间层，滑块标签使用服务端返回的真实坐标', async () => {
    vi.mocked(client.fetchResultSlice).mockResolvedValue(makeSlice('z', -420))
    const wrapper = await mountPanel('3d', [11, 11, 11])
    expect(client.fetchResultSlice).toHaveBeenCalledWith('r1', 'z', 5)
    expect(wrapper.find('[data-test="slice-label"]').text()).toContain('Z = -420 m')
  })

  it('切换轴向时向服务端请求新切片而不是浏览器重算', async () => {
    vi.mocked(client.fetchResultSlice).mockImplementation(async (_id, axis) =>
      makeSlice(axis as 'x' | 'y' | 'z', axis === 'x' ? -132 : axis === 'y' ? 356 : -420),
    )
    const wrapper = await mountPanel('3d', [11, 11, 11])
    await wrapper.find('[data-test="axis-x"]').trigger('click')
    await flushPromises()
    expect(client.fetchResultSlice).toHaveBeenCalledWith('r1', 'x', 5)
    expect(wrapper.find('[data-test="slice-label"]').text()).toContain('X = -132 m')

    await wrapper.find('[data-test="axis-y"]').trigger('click')
    await flushPromises()
    expect(client.fetchResultSlice).toHaveBeenCalledWith('r1', 'y', 5)
    expect(wrapper.find('[data-test="slice-label"]').text()).toContain('Y = 356 m')
  })

  it('拖动滑块按索引请求对应切片', async () => {
    vi.mocked(client.fetchResultSlice).mockResolvedValue(makeSlice('z', -500))
    const wrapper = await mountPanel('3d', [11, 11, 11])
    const slider = wrapper.find('[data-test="slice-slider"]')
    expect(slider.attributes('max')).toBe('10')
    await slider.setValue(2)
    await flushPromises()
    expect(client.fetchResultSlice).toHaveBeenCalledWith('r1', 'z', 2)
    expect(wrapper.find('[data-test="slice-label"]').text()).toContain('Z = -500 m')
  })

  it('NoData 单元不生成图元（保持透明）', async () => {
    vi.mocked(client.fetchResultSlice).mockResolvedValue(makeSlice('z', -420))
    const wrapper = await mountPanel('3d', [11, 11, 11])
    // 6 个单元中 1 个 NoData → 5 个有效图元
    expect(wrapper.find('[data-test="valid-cells"]').text()).toContain('5')
  })

  it('2D 成果只有整场 Z=0，不提供 X/Y 切片', async () => {
    vi.mocked(client.fetchResultSlice).mockResolvedValue(makeSlice('z', 0))
    const wrapper = await mountPanel('2d', [11, 11])
    expect(wrapper.find('[data-test="axis-z"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="axis-x"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="axis-y"]').exists()).toBe(false)
    expect(client.fetchResultSlice).toHaveBeenCalledWith('r1', 'z', 0)
  })
})

describe('fieldData 纯函数', () => {
  it('buildHeatmapData 跳过 NoData 与非有限值', () => {
    const cells = buildHeatmapData(
      [
        [1, null, Number.NaN],
        [4, 5, 6],
      ],
      [
        [false, true, false],
        [true, false, false],
      ],
    )
    expect(cells).toHaveLength(3)
    expect(cells.map((c) => c.value)).toEqual([1, 5, 6])
  })

  it('nearestIndex 吸附最近网格节点', () => {
    expect(nearestIndex([0, 10, 20], 13)).toBe(1)
    expect(nearestIndex([0, 10, 20], -5)).toBe(0)
    expect(nearestIndex([0, 10, 20], 99)).toBe(2)
  })
})
